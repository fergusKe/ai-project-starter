#!/usr/bin/env python3
from pathlib import Path
import argparse,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'workflow/bin'))
from workflow_state import audit_commit_changes,change_touches_control_plane,control_plane_digest,parse_state_text,installation_baseline,AUDIT_FAIL_CLOSED_PHASE
STATE_PATH='workflow/STATE.md';LOG_PATH='workflow/state-log.md'

def g(*a,text=True):return subprocess.run(['git','-C',str(ROOT),*a],capture_output=True,text=text)

def state_phase_at(commit):
 r=g('show',f'{commit}:{STATE_PATH}')
 if r.returncode==0:
  try:return parse_state_text(r.stdout).phase
  except Exception:pass
 # First-install / damaged history: use first parent if possible; otherwise fail-closed as ENGINEERING policy.
 pr=g('rev-parse',f'{commit}^')
 if pr.returncode==0:
  p=g('show',f'{pr.stdout.strip()}:{STATE_PATH}')
  if p.returncode==0:
   try:return parse_state_text(p.stdout).phase
   except Exception:pass
 return AUDIT_FAIL_CLOSED_PHASE

def log_bytes(commit):
 r=g('show',f'{commit}:{LOG_PATH}',text=False)
 return r.stdout if r.returncode==0 else None

def parent_of(commit):
 r=g('rev-list','--parents','-n','1',commit)
 parts=r.stdout.strip().split() if r.returncode==0 else []
 return parts[1] if len(parts)>1 else None

def log_has_action(commit,action):
 raw=log_bytes(commit)
 if raw is None:return False
 try:txt=raw.decode('utf-8')
 except UnicodeDecodeError:return False
 return re.search(rf'(?m)^- Action:\s*{re.escape(action)}\s*$',txt) is not None

def audit_record_matches(commit,digest):
 raw=log_bytes(commit)
 if raw is None:return False
 try:txt=raw.decode('utf-8')
 except UnicodeDecodeError:return False
 for block in re.split(r'(?m)^## ',txt)[1:]:
  if re.search(r'(?m)^- Action:\s*(?:control-plane-commit|install-adopt-control-plane)\s*$',block) and re.search(rf'(?m)^- Control Plane digest:\s*{re.escape(digest)}\s*$',block):
   return True
 return False

def main():
 ap=argparse.ArgumentParser();ap.add_argument('base');ap.add_argument('head');a=ap.parse_args()
 r=g('rev-list','--reverse',f'{a.base}..{a.head}')
 if r.returncode:print(r.stderr,file=sys.stderr);raise SystemExit(2)
 bad=[]
 for c in [x for x in r.stdout.splitlines() if x]:
  try:changes=audit_commit_changes(ROOT,c)
  except Exception as e:bad.append((c,[f'diff inspection failed: {e}']));continue
  phase=state_phase_at(c)

  # Sanctioned Greenfield/Brownfield Starter installation baseline is not a maintenance commit.
  if installation_baseline(ROOT,changes,c):
   continue

  # Audit continuity: state-log may append, but may never be deleted, renamed, or shortened.
  logchg=[ch for ch in changes if LOG_PATH in ch.paths]
  destructive_log=any(ch.status in {'D','R'} for ch in logchg)
  parent=parent_of(c)
  shortened=False
  if logchg and parent and not destructive_log:
   before=log_bytes(parent) or b'';after=log_bytes(c) or b''
   shortened=not after.startswith(before)
  if destructive_log or shortened:
   bad.append((c,['workflow/state-log.md audit continuity violated']))
   continue

  cp=[ch for ch in changes if change_touches_control_plane(ch,phase) and not all(p in {STATE_PATH,LOG_PATH} for p in ch.paths)]
  if not cp:continue
  exp=control_plane_digest(ROOT,cp,c)
  if not audit_record_matches(c,exp):
   desc=[]
   for ch in cp: desc.append(f'{ch.status}: '+(' -> '.join(ch.paths) if ch.status=='R' else ch.paths[0]))
   bad.append((c,desc))
 if bad:
  # D-7：若被標記的 commit 早於已辨識的 installation baseline，訊息必須自我說明。
  # 安裝點＝第一個把 workflow/STATE.md 帶進 history 的 commit。
  # 這對 greenfield baseline 與 adopt-control-plane 兩條安裝路徑都成立。
  install=None
  for c in [x for x in r.stdout.splitlines() if x]:
   try:
    if any(ch.status=='A' and ch.new_path==STATE_PATH for ch in audit_commit_changes(ROOT,c)):
     install=c;break
   except Exception:pass
  pre_install=[]
  if install:
   anc=g('rev-list','--ancestry-path',f'{install}..{a.head}')
   later=set(x for x in anc.stdout.splitlines() if x)|{install}
   pre_install=[c for c,_ in bad if c not in later]
  print('Unauthorized / unaudited Control Plane commits detected:',file=sys.stderr)
  for c,items in bad:
   print(f'- {c}',file=sys.stderr)
   for item in items:print(f'  {item}',file=sys.stderr)
  if pre_install:
   print('',file=sys.stderr)
   print(f'注意：上列有 {len(pre_install)} 個 commit 早於 Starter 的安裝 baseline（{install[:12]}）。',file=sys.stderr)
   print('這些 commit 在 Starter 存在之前就已建立，當時並不受 Control Plane 規範。',file=sys.stderr)
   print('請改以 merge-base 作為 audit 起點，例如：',file=sys.stderr)
   print('  BASE=$(git merge-base origin/main HEAD)',file=sys.stderr)
   print('  python3 workflow/bin/audit-control-plane.py "$BASE" HEAD',file=sys.stderr)
  raise SystemExit(1)
 print('Control Plane audit: OK')
if __name__=='__main__':main()

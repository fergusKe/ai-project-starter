#!/usr/bin/env python3
from pathlib import Path
import argparse,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'workflow/bin'))
from workflow_state import (audit_commit_changes,change_touches_control_plane,control_plane_digest,
 parse_state_text,installation_baseline,AUDIT_FAIL_CLOSED_PHASE,
 path_is_ai_writable_non_product,evidence_write_allowed,implementation_authorized_at,
 path_is_installation_scaffolding,
 state_hash_text,CORE_EVIDENCE_RE,BROWSER_EVIDENCE_RE)
STATE_PATH='workflow/STATE.md';LOG_PATH='workflow/state-log.md'

def g(*a,text=True):return subprocess.run(['git','-C',str(ROOT),*a],capture_output=True,text=text)

def state_at(commit):
 """該 commit 的完整 STATE。取不到或壞掉回 None。"""
 r=g('show',f'{commit}:{STATE_PATH}')
 if r.returncode!=0:return None
 try:return parse_state_text(r.stdout)
 except Exception:return None

def state_text_at(commit):
 r=g('show',f'{commit}:{STATE_PATH}')
 return r.stdout if r.returncode==0 else None

def workflow_authorization_violations(commit,changes,state,installing=False):
 """逐 commit 的工作流授權稽核 —— 這是 required check 真正的內容。

 沒有這一段的話，`--no-verify` 繞過本機 gate 之後，伺服器端只會看到
 「沒有 Control Plane mutation」而輸出 OK：DISCOVERY 階段、零批准的產品程式碼
 可以直接合併。那會讓 MERGE-PROTECTION.md 的宣稱變成一句沒有機制支撐的話。

 四類（與本機 gate 同源的判準）：
   1. STATE 變更必須同時附上 state-log，且 hash 對得起來
   2. Control Plane transition 不得與產品程式碼同一個 commit
   3. 產品變更必須在該 commit 當下就已被授權
   4. evidence 只能由 active change 在 ENGINEERING/VERIFICATION 寫入
 """
 out=[]
 touches_state=any(STATE_PATH in ch.paths for ch in changes)
 touches_log=any(LOG_PATH in ch.paths for ch in changes)

 if touches_state:
  if not touches_log:
   out.append('STATE 變更沒有同時附上 state-log —— 無法證明這次變更經過任何 transition')
  else:
   stext=state_text_at(commit);raw=log_bytes(commit)
   if stext is None or raw is None:
    out.append('無法讀取此 commit 的 STATE / state-log')
   else:
    try:ltext=raw.decode('utf-8')
    except UnicodeDecodeError:ltext=None
    if ltext is None:
     out.append('state-log 非 UTF-8')
    else:
     hashes=re.findall(r'^- State hash:\s*([0-9a-f]{64})\s*$',ltext,re.M)
     if not hashes or hashes[-1]!=state_hash_text(stext):
      out.append('STATE hash 與 state-log 最後一筆不一致 —— STATE 被改過但沒有對應的稽核紀錄')

 if state is None:
  # STATE 讀不出來就無法判斷授權。fail-closed：只有完全不碰產品/evidence 才放行。
  suspicious=[ch for ch in changes
              if not all(pp in {STATE_PATH,LOG_PATH} for pp in ch.paths)]
  if suspicious:
   out.append('此 commit 的 STATE 無法解析，因此無法證明任何變更被授權')
  return out

 product=[];evidence=[]
 for ch in changes:
  if any(pp in {STATE_PATH,LOG_PATH} for pp in ch.paths):continue
  # Control Plane 自己的檔案不走「實作授權」這條，它們由 control-plane-commit
  # （TTY + audit record）管轄，下面的 cp 檢查會驗。本機 gate 同樣是先攔在
  # exit 20，根本走不到產品迴圈 —— 兩邊的分層必須一致，否則安裝與維護 commit
  # 會被當成未授權的實作。
  if change_touches_control_plane(ch,state.phase):continue
  # 合法的安裝 commit 帶進來的是工具，不是產品功能。沒有這個豁免，Starter 的
  # 安裝動作會被 Starter 自己的稽核判成「DISCOVERY 階段的未授權實作」。
  if installing and all(path_is_installation_scaffolding(pp) for pp in ch.paths):continue
  desc=f'{ch.status}: '+(' -> '.join(ch.paths) if ch.status=='R' else ch.paths[0])
  is_product=False
  for pp in ch.paths:
   if CORE_EVIDENCE_RE.match(pp) or BROWSER_EVIDENCE_RE.match(pp):
    if not evidence_write_allowed(pp,state):evidence.append(desc)
    continue
   if path_is_ai_writable_non_product(pp,state.phase):continue
   is_product=True
  if is_product:product.append(desc)

 if evidence:
  out.append(f'evidence 不在可寫範圍內（change={state.active_change}、phase={state.phase}）：'
             +'、'.join(sorted(set(evidence))))
 if product and touches_state:
  out.append('Control Plane transition 與產品程式碼在同一個 commit：'+'、'.join(product))
 if product:
  ok,why=implementation_authorized_at(ROOT,state,commit)
  if not ok:
   out.append(f'未授權的產品變更（{why}）：'+'、'.join(product))
 return out

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

  # 工作流授權稽核。原本 audit 只比對「Control Plane mutation 與 audit record 是否
  # 一致」，那個宣稱比 MERGE-PROTECTION.md 寫的窄得多：它看不到未經批准的產品變更，
  # 也刻意把 STATE-only 的變更排除在外。兩者都實測可繞過。
  cp=[ch for ch in changes if change_touches_control_plane(ch,phase) and not all(p in {STATE_PATH,LOG_PATH} for p in ch.paths)]
  installing=log_has_action(c,'install-adopt-control-plane')
  problems=workflow_authorization_violations(c,changes,state_at(c),installing)
  if cp:
   exp=control_plane_digest(ROOT,cp,c)
   if not audit_record_matches(c,exp):
    for ch in cp:
     problems.append('Control Plane 變更沒有對應的 audit record：'
                     +(' -> '.join(ch.paths) if ch.status=='R' else ch.paths[0]))
  if problems:bad.append((c,problems))
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
  print('工作流授權稽核失敗（Unauthorized / unaudited commits）：',file=sys.stderr)
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

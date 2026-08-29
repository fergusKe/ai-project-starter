#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from dataclasses import replace
import argparse, os, re, shutil, subprocess, sys, time
from workflow_state import (parse_state,write_state,state_hash_path,now_iso,project_web_status,path_is_control_plane,
 staged_changes,control_plane_digest,change_touches_control_plane,initial_state_hash,
 installation_conflicts,installation_overwrites,installation_preflight,installation_unexpected_changes,staged_state_is_pristine,
 repository_enforcement,enforcement_is_active,GATE_BRIDGE_COMMAND,verification_policy,
 probe_enforcement,probe_head_enforcement,effective_pre_commit_hook,
 probe_fingerprint,finalize_probe_receipt,approved_profile_status,
 ENFORCEMENT_CHAINED_STATIC,profile_resolution,agent_environment_provenance,validate_change_id)
ROOT=Path(__file__).resolve().parents[2];STATE=ROOT/'workflow/STATE.md';LOG=ROOT/'workflow/state-log.md'
CORE_NAME_RE=re.compile(r'^\d{8}T\d{6}(?:\d{6})?Z\.md$')
def die(msg,code):sys.stdout.flush();print(f'ERROR: {msg}',file=sys.stderr);raise SystemExit(code)
def git_sha():
 r=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True);return r.stdout.strip() if r.returncode==0 else 'NO_HEAD'
def append_log(action,actor,old_phase,new_phase,change,reason,extra=None):
 h=state_hash_path(STATE)
 lines=[
  f"## {now_iso()}",f"- Actor: {actor}",f"- Action: {action}",f"- Change: {change}",
  f"- From: {old_phase}",f"- To: {new_phase}",f"- Git SHA: {git_sha()}",f"- State hash: {h}",
 ]
 for k,v in (extra or {}).items(): lines.append(f"- {k}: {v}")
 lines.append(f"- Reason: {reason}")
 with LOG.open('a',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n\n')
def transition(s,ns,action,actor,reason):
 write_state(STATE,ns);append_log(action,actor,s.phase,ns.phase,ns.active_change,reason);print(f'Transition complete: {action}');print('NEXT REQUIRED ACTION: 先獨立提交 workflow/STATE.md 與 workflow/state-log.md，再進行下一階段工作。')
def ensure_change_exists(change):
 p=ROOT/'openspec/changes'/change
 if not p.exists():die(f'找不到 OpenSpec change: {change}',31)
 # 空目錄不算 change。G4 冷啟動實測：agent 為了探明契約而 mkdir 一個空目錄再 start-change，
 # 竟然成功 —— STATE 綁上一個沒有任何內容的 change 名，而 state-log 是 append-only，
 # 那筆誤綁永久留在稽核紀錄裡。start-change 不要求完整 artifact（那是 submit-for-review
 # 的事），但至少要求目錄裡有東西，並在訊息裡把之後會被要求的清單講出來。
 if not any(p.iterdir()):
  die(f'OpenSpec change 目錄是空的: openspec/changes/{change}\n'
      '  請先寫入內容再 start-change。submit-for-review 時會要求：'
      'proposal（檔名含 proposal）、specs（specs/ 目錄或檔名含 spec）、tasks（檔名含 task）。',31)
 return p
def ensure_review_artifacts(change):
 p=ensure_change_exists(change);names=[x.name.lower() for x in p.iterdir() if x.is_file()];missing=[]
 if not any('proposal' in x for x in names):missing.append('proposal')
 if not(any('spec' in x for x in names) or (p/'specs').exists()):missing.append('specs')
 if not any('task' in x for x in names):missing.append('tasks')
 if missing:die('submit-for-review 缺少 artifact: '+', '.join(missing),32)
def tty_human_confirm(action,change,details=None):
 # Local execution boundary only; not cryptographic identity.
 # Must be re-validated with `doctor` in each agent harness.
 if not os.isatty(0):die(f'{action} 需要人類互動終端機；stdin 不是 TTY',20)
 try:fd=os.open('/dev/tty',os.O_RDWR)
 except OSError:die(f'{action} 需要人類互動終端機；/dev/tty 無法開啟',20)
 try:
  if not os.isatty(fd):die('/dev/tty 不是 TTY',20)
  head=f'\nHuman Approval — 確認你要批准的項目\n'
  if details:
   # 人類必須看得到自己正在批准什麼。approve-spec 同時把 PROJECT-PROFILE 的定案
   # 一起收下，不列出來等於要人類批准一份看不見的內容。
   head+=details+'\n'
  os.write(fd,(head+f'請逐字輸入「{change}」以確認: ').encode());reply=b''
  while not reply.endswith(b'\n'):
   c=os.read(fd,1)
   if not c:break
   reply+=c
  got=reply.decode(errors='replace').strip()
  if got!=change:die(f'確認失敗 — 輸入的是「{got[:80]}」，需要「{change}」',21)
  os.write(fd,'Approval actor（你的名字或 handle，這一欄才是簽名）: '.encode());actor=b''
  while not actor.endswith(b'\n'):
   c=os.read(fd,1)
   if not c:break
   actor+=c
  actor=actor.decode(errors='replace').strip()
  if not actor:die('Approved by 不可為空',22)
  return actor
 finally:os.close(fd)
def _sha256(path):
 import hashlib
 h=hashlib.sha256()
 try:h.update(path.read_bytes())
 except OSError:return None
 return h.hexdigest()

def _accepted_evidence_from_log(change):
 """從 state-log 取出最後一次 verification-pass 所接受的 evidence 路徑與 digest。"""
 if not LOG.exists():return None
 blocks=re.split(r'(?m)^## ',LOG.read_text(encoding='utf-8'))[1:]
 for block in reversed(blocks):
  if not re.search(r'(?m)^- Action:[ \t]*verification-pass[ \t]*$',block):continue
  if not re.search(rf'(?m)^- Change:[ \t]*{re.escape(change)}[ \t]*$',block):continue
  path=re.search(r'(?m)^- Core evidence:[ \t]*(.*?)[ \t]*$',block)
  digest=re.search(r'(?m)^- Core evidence sha256:[ \t]*([0-9a-f]{64})[ \t]*$',block)
  if path and digest:return path.group(1),digest.group(1)
  return None
 return None

def edir(change):return ROOT/'workflow/evidence'/change
def core_files(change):
 d=edir(change)/'core'
 if not d.exists():return []
 fs=[p for p in d.glob('*.md') if CORE_NAME_RE.fullmatch(p.name)]
 return sorted(fs,key=lambda p:p.name)
def latest_core(change):
 fs=core_files(change);return fs[-1] if fs else None
def browser_file(change):return edir(change)/'browser.md'
def _evidence_field(text,name):
 m=re.search(rf'^{re.escape(name)}:[ \t]*(.*?)[ \t]*$',text,re.M)
 return m.group(1).strip() if m else None

def core_evidence_status(path,expected_change=None):
 """evidence 是否可被採用 = **語意有效** 且 **來歷可證**。回傳 (ok, reason)。

 兩者刻意分成兩段並依此順序：語意回答「這份 evidence 宣稱了什麼」，
 來歷回答「該不該相信它」。順序反過來的話，一份「PASS 但零檢查」的 evidence
 會先收到「缺少 digest 欄位」，那對使用者沒有幫助；更糟的是來歷檢查會**遮蔽**
 所有語意檢查，讓既有的語意 regression 全部在到達它們的斷言之前就短路。

 兩個呼叫端（verification-pass、archive）都只呼叫這個函式，所以兩段都跑得到。
 拆成兩個公開函式讓呼叫端自己組合的話，就會多出一個「有人只呼叫其中一段」的
 未鎖住路徑。
 """
 ok,why=_core_evidence_semantics(path,expected_change)
 if not ok:return ok,why
 return _core_evidence_provenance(path)

def _core_evidence_provenance(path):
 """evidence 必須自證它依哪一份被批准的 profile 產生。回傳 (ok, reason)。

 為什麼 evidence 要自己帶這個欄位：產生它的 PROJECT-PROFILE 可以在事後被 restore，
 git 因此看不到任何 profile mutation。少了這一欄，沒有任何一層能事後判斷一份
 archived evidence 是依哪一份被批准的政策產生的。
 """
 text=path.read_text(encoding='utf-8')
 ev=_evidence_field(text,'Approved profile digest')
 if ev is None:
  return False,'core evidence 沒有 Approved profile digest 欄位；請重新執行 verify.sh --full'
 if ev=='none':
  return False,'core evidence 產生時 STATE 沒有批准過的 profile digest；請先完成 approve-spec 再重跑'
 try:state_digest=parse_state(STATE).profile_digest
 except ValueError as exc:return False,f'STATE 無法解析：{exc}'
 if ev!=state_digest:
  return False,(f'evidence 的 Approved profile digest 是「{ev[:16]}」，'
                f'與 STATE 的「{state_digest[:16]}」不符')
 return True,''

def _core_evidence_semantics(path,expected_change=None):
 """語意化 evidence validator（R4）。回傳 (ok, reason)。

 PASS 必須 Checks executed >= 1 且 Overall exit code 0；
 NOT_APPLICABLE 必須與 Profile 政策一致且 Exception reason 非空；
 零檢查配 Outcome: PASS 一律拒絕；舊 schema 一律要求重跑。
 """
 if path is None or not path.exists():return False,'core evidence 不存在'
 text=path.read_text(encoding='utf-8')
 schema=_evidence_field(text,'Core evidence schema')
 if schema is None:
  return False,'core evidence 是舊格式（無 schema 欄位）；請重新執行 verify.sh --full'
 if schema!='2':
  return False,f'不支援的 core evidence schema: {schema}'
 if expected_change is not None:
  ch=_evidence_field(text,'Change')
  if ch!=expected_change:return False,f'evidence 的 Change 是「{ch}」，與目前的「{expected_change}」不符'
 overall=_evidence_field(text,'Overall exit code')
 if overall!='0':return False,f'Overall exit code = {overall}'
 outcome=_evidence_field(text,'Outcome')
 executed=_evidence_field(text,'Checks executed')
 try:executed_n=int(executed)
 except (TypeError,ValueError):return False,f'Checks executed 欄位無效: {executed}'
 if outcome=='PASS':
  policy=_evidence_field(text,'Verification policy')
  declared=verification_policy(ROOT)
  if policy not in {'auto','custom'}:
   return False,f'Outcome=PASS 但 Verification policy 是「{policy}」；只有 auto/custom 可產生 PASS'
  if policy!=declared['policy']:
   return False,f'evidence 的 policy 是「{policy}」，與 PROJECT-PROFILE 的「{declared["policy"]}」不符'
  selected=_evidence_field(text,'Checks selected')
  if selected is None:return False,'PASS 的 evidence 必須包含 Checks selected 欄位'
  if selected!=executed:
   return False,f'Checks selected={selected} 與 Checks executed={executed} 不符'
  if executed_n<1:return False,'Outcome=PASS 但 Checks executed=0；零檢查不得視為通過'
  # PASS 必須有與 Checks executed 相符的實際紀錄，且每筆都要有 exit code 0。
  records=re.findall(r'(?m)^Exit code:[ \t]*(\d+)[ \t]*$',text)
  if len(records)!=executed_n:
   return False,f'Checks executed={executed_n} 但實際 check 紀錄有 {len(records)} 筆；evidence 不自洽'
  bad=[r for r in records if r!='0']
  if bad:return False,f'Outcome=PASS 但有 {len(bad)} 筆 check 的 exit code 非 0'
  return True,''
 if outcome=='NOT_APPLICABLE':
  policy=_evidence_field(text,'Verification policy')
  if policy!='not-applicable':
   return False,f'Outcome=NOT_APPLICABLE 但 Verification policy={policy}'
  declared=verification_policy(ROOT)
  if declared['policy']!='not-applicable':
   return False,'evidence 宣告 NOT_APPLICABLE，但 PROJECT-PROFILE 的政策不是 not-applicable'
  if not (_evidence_field(text,'Exception reason') or '').strip():
   return False,'NOT_APPLICABLE 必須填寫非空的 Exception reason'
  return True,''
 return False,f'不支援的 Outcome: {outcome}'

def core_success(path):
 ok,_=core_evidence_status(path);return ok
def validate_browser(change):
 status=project_web_status(ROOT)
 if status=='UNRESOLVED':die('Web Gate 判定未決；請先明確設定 PROJECT-PROFILE',52)
 p=browser_file(change)
 if not p.exists():die('缺少 browser evidence',49)
 t=p.read_text(encoding='utf-8');not_app='Browser Gate: NOT APPLICABLE' in t
 if status=='NON_WEB':
  if not not_app:die('非 Web 專案缺少 NOT APPLICABLE browser evidence',53)
  return
 if not_app:die('Web 專案不可使用 NOT APPLICABLE',49)
 mcore=re.search(r'^Core evidence:\s*(\S+)\s*$',t,re.M);mreport=re.search(r'^Playwright report:\s*(\S+)\s*$',t,re.M)
 if not mcore or not mreport or 'Chrome DevTools' not in t:die('Web browser evidence 缺少 Core evidence / Playwright report / Chrome DevTools',49)
 cp=edir(change)/'core'/Path(mcore.group(1)).name
 if not CORE_NAME_RE.fullmatch(cp.name) or not cp.exists() or not core_success(cp):die('browser.md 引用的 core evidence 無效或未通過',55)
 report=(ROOT/mreport.group(1)).resolve()
 try:report.relative_to(ROOT.resolve())
 except ValueError:die('Playwright report 必須位於 repository 內',56)
 if not report.exists():die('Playwright report artifact 不存在',57)
def cmd_status(_):
 s=parse_state(STATE)
 for k,v in [('Phase',s.phase),('Project mode',s.project_mode),('Active OpenSpec change',s.active_change),('Spec approved',s.spec_approved),('Test design approved',s.test_design_approved),('Verification passed',s.verification_passed),('Approved by',s.approved_by),('Last updated',s.last_updated),('Implementation allowed (derived)','yes' if s.implementation_allowed else 'no'),('Web status',project_web_status(ROOT))]:print(f'{k}: {v}')
def _print_provenance():
 """列出專案版控之外的 agent 指令來源。

 **這是可觀測性訊號，不是 enforcement。** 它不改變上面那行 Repository enforcement 的
 判定 —— 兩者問的問題不同：enforcement 問「clone 之後 gate 還在不在」，
 provenance 問「這台機器上還有誰在對 agent 說話」。把後者混進前者，
 等於讓 Starter 對它無法驗證的東西下判斷。
 """
 p=agent_environment_provenance(ROOT)
 if not p['items']:
  print('Agent environment provenance: NONE_DETECTED（僅就檔案系統可見範圍）')
 else:
  print(f"Agent environment provenance: {p['level']}（不影響上方 Repository enforcement 判定）")
  for it in p['items']:
   tail=f" — {it['detail']}" if it['detail'] else ''
   print(f"  [{it['level']}] {it['kind']}: {it['name']}{tail}")
 print('  註：以上是 filesystem inventory，不是完整的 effective runtime inventory。看不到：'
       +'、'.join(p['unknowns'])+'。')
 print('  要看實際生效的完整清單，用 Claude Code 的 /hooks 與 /status。')

def cmd_doctor(_):
 try:parse_state(STATE);schema='OK'
 except Exception as e:schema=f'FAIL: {e}'
 stdin=os.isatty(0);usable=False;reason=''
 try:
  fd=os.open('/dev/tty',os.O_RDWR);usable=os.isatty(fd);os.close(fd)
  if not usable:reason='/dev/tty 非 TTY'
 except OSError as e:reason=f'/dev/tty 無法開啟: {e}'
 print(f'STATE schema: {schema}');print(f'stdin is TTY: {"YES" if stdin else "NO"}');print(f'/dev/tty usable: {"YES" if usable else "NO"}');print(f'approve-* 可在此環境執行: {"YES" if stdin and usable else "NO"}'+(f'（{reason or "stdin 非 TTY"}）' if not(stdin and usable) else ''));_print_enforcement();_print_provenance();_print_web_tooling();print(f'git: {"OK" if shutil.which("git") else "MISSING"}');print(f'python3: {"OK" if shutil.which("python3") else "MISSING"}');print(f'OpenSpec CLI: {"OK" if shutil.which("openspec") else "MISSING（選用；transition 不依賴它）"}');print('注意：TTY 是已驗證 execution boundary，不是 cryptographic human identity。')
def cmd_set_mode(a):
 s=parse_state(STATE)
 if s.phase!='DISCOVERY':die('set-mode 只允許 DISCOVERY',33)
 transition(s,replace(s,project_mode=a.mode,last_updated=now_iso()),'set-mode','machine-verified',f'Project mode={a.mode}')
def cmd_start_change(a):
 s=parse_state(STATE)
 if s.phase not in {'DISCOVERY','SPECIFICATION'}:die('start-change 只允許 DISCOVERY/SPECIFICATION',34)
 ensure_change_exists(a.change);ns=replace(s,phase='SPECIFICATION',active_change=a.change,spec_approved='no',test_design_approved='no',verification_passed='no',approved_by='none',last_updated=now_iso());transition(s,ns,'start-change','machine-verified','Active change bound')
def cmd_submit(a):
 s=parse_state(STATE)
 if s.phase!='SPECIFICATION':die('submit-for-review 只允許 SPECIFICATION',35)
 if s.project_mode=='UNSET':die('Project mode 尚未設定；請先 set-mode',36)
 if s.active_change!=a.change:die('change 與 STATE 不一致',41)
 ensure_review_artifacts(a.change);transition(s,replace(s,phase='SPEC_REVIEW',last_updated=now_iso()),'submit-for-review','machine-verified','Required OpenSpec artifacts exist')
def cmd_approve_spec(a):
 s=parse_state(STATE)
 if s.phase!='SPEC_REVIEW':die('approve-spec 只允許 SPEC_REVIEW',40)
 if s.active_change!=a.change:die('change 與 STATE 不一致',41)
 # PROJECT-PROFILE 的定案在這個邊界收取。在 TTY 之前檢查，理由有二：
 # 一是 fail fast，不要讓人類打完確認字串才被拒；二是這條規則因此在沒有 TTY 的
 # 環境下也測得到。
 unresolved,invalid,resolved,digest=profile_resolution(ROOT)
 if unresolved:
  die('approve-spec 之前必須先解析 PROJECT-PROFILE.md 的下列欄位：\n'
      +''.join(f'  - {x}\n' for x in unresolved)
      +'UNKNOWN（或 Web verification required: auto）可以進 SPEC_REVIEW，但不能進 ENGINEERING。\n'
      '候選值請先寫成 ADR 與 OpenSpec 的一部分，由本次批准一併定案；'
      '不要在沒有依據時猜測。',44)
 if invalid:
  # 與 unresolved 分開報。「填了無法辨識的值」跟「還沒填」是兩件事，
  # 混在一起會讓人以為自己沒存檔而重打一次同樣的錯字。
  die('PROJECT-PROFILE.md 有無法辨識的值：\n'
      +''.join(f'  - {n}: {v!r} —— {why}\n' for n,v,why in invalid)
      +'打錯字不會被當成未決，會被當成已決定 —— 而錯的值可能靜默關掉某個 Gate。',44)
 details='即將定案的 PROJECT-PROFILE：\n'+''.join(f'  {k}: {resolved[k]}\n' for k in sorted(resolved))
 actor=tty_human_confirm('approve-spec',a.change,details)
 # TTY 是人類速度的等待，視窗以分鐘計。回來之後必須重新比對：人類批准的是畫面上
 # 那份 profile，不是「他打完字時磁碟上剛好是什麼」。沒有這一步，另一個 process
 # 可以在等待期間換掉 PROJECT-PROFILE，而 log 仍記著畫面上那份的 digest。
 _,_,_,after=profile_resolution(ROOT)
 if after!=digest:
  die('PROJECT-PROFILE.md 在你確認期間被修改，批准作廢。\n'
      '  你看到並批准的是修改前的內容；請重新檢視後再執行一次 approve-spec。',44)
 transition(s,replace(s,phase='TEST_DESIGN',spec_approved='yes',approved_by=actor,
                      profile_digest=digest,last_updated=now_iso()),
            'approve-spec',actor,f'Human approved specification; profile digest {digest[:16]}')
def cmd_approve_tests(a):
 s=parse_state(STATE)
 if s.phase!='TEST_DESIGN':die('approve-tests 只允許 TEST_DESIGN',42)
 if s.spec_approved!='yes':die('Spec 尚未批准',43)
 if s.active_change!=a.change:die('change 與 STATE 不一致',41)
 ok,why=approved_profile_status(ROOT,s)
 if not ok:die(f'approve-tests 需要 PROJECT-PROFILE 與人類批准的內容一致。\n{why}',44)
 actor=tty_human_confirm('approve-tests',a.change);transition(s,replace(s,test_design_approved='yes',approved_by=actor,last_updated=now_iso()),'approve-tests',actor,'Human approved test design')
def cmd_start_engineering(a):
 s=parse_state(STATE)
 if s.phase!='TEST_DESIGN':die('start-engineering 只允許 TEST_DESIGN',44)
 if s.spec_approved!='yes' or s.test_design_approved!='yes':die('Spec/Test Design 尚未批准',45)
 if s.active_change!=a.change:die('change 與 STATE 不一致',41)
 # 只看 approval flag 不夠。approve-spec 與 start-engineering 之間可以隔任意長的
 # 時間與任意多的 agent 動作；把 `Core verification policy` 改成 not-applicable
 # 這種放寬，在只檢查 flag 的設計下不會被任何人發現。批准綁的是**內容**，不是旗標。
 ok,why=approved_profile_status(ROOT,s)
 if not ok:die(why,44)
 transition(s,replace(s,phase='ENGINEERING',last_updated=now_iso()),'start-engineering','machine-verified','Approval prerequisites satisfied; profile digest re-verified')
def cmd_verification_pass(a):
 s=parse_state(STATE)
 if s.phase not in {'ENGINEERING','VERIFICATION'}:die('verification-pass 只允許 ENGINEERING/VERIFICATION',46)
 if s.active_change!=a.change:die('change 與 STATE 不一致',41)
 # 必須在跑 verify.sh **之前**擋。verify.sh 會依當下的 PROJECT-PROFILE 決定要不要
 # 執行檢查；profile 若已被換成未經批准的 not-applicable，它會產生一份
 # `Checks executed: 0` 的 evidence，事後把檔案 restore 回去 git 就看不到任何痕跡。
 ok,why=approved_profile_status(ROOT,s)
 if not ok:die(f'verification-pass 需要 PROJECT-PROFILE 與人類批准的內容一致。\n{why}',44)
 # 由 verify.sh 明確回報它建立的路徑，不用「前後檔名集合差」——
 # 後者在同一微秒檔名碰撞（覆寫舊檔）時會得到 0 份，並行執行時會得到多份。
 r=subprocess.run(['bash',str(ROOT/'workflow/bin/verify.sh'),'--full'],cwd=ROOT,capture_output=True,text=True)
 sys.stdout.write(r.stdout);sys.stderr.write(r.stderr)
 if r.returncode!=0:die(f'verify.sh --full 失敗，exit={r.returncode}',47)
 produced_lines=[ln for ln in r.stdout.splitlines() if ln.startswith('Core evidence: ')]
 if len(produced_lines)!=1:
  die(f'verify.sh 未明確回報恰好一份 core evidence（實際 {len(produced_lines)} 行）',48)
 c=Path(produced_lines[0][len('Core evidence: '):].strip())
 if not c.is_absolute():c=ROOT/c
 if not c.exists():die(f'verify.sh 回報的 core evidence 不存在：{c}',48)
 try:rel_check=c.resolve().relative_to((ROOT/'workflow/evidence'/a.change/'core').resolve())
 except ValueError:die(f'verify.sh 回報的 core evidence 不在 canonical 位置：{c}',48)
 if len(rel_check.parts)!=1:die(f'core evidence 必須是 core/ 的直接子檔案，不得位於子目錄：{rel_check}',48)
 if not CORE_NAME_RE.fullmatch(rel_check.name):die(f'core evidence 檔名不符格式：{rel_check.name}',48)
 ok,why=core_evidence_status(c,a.change)
 if not ok:die(f'本次產生的 core evidence 未通過：{why}',54)
 digest=_sha256(c)
 if digest is None:die('無法計算 core evidence digest',54)
 validate_browser(a.change)
 rel=str(c.relative_to(ROOT))
 write_state(STATE,replace(s,phase='VERIFICATION',verification_passed='yes',last_updated=now_iso()))
 append_log('verification-pass','machine-verified',s.phase,'VERIFICATION',a.change,'Core/browser evidence validated',
            extra={'Core evidence':rel,'Core evidence sha256':digest})
 print('Transition complete: verification-pass')
 print(f'Accepted core evidence: {rel}')
 print('NEXT REQUIRED ACTION: 先獨立提交 workflow/STATE.md 與 workflow/state-log.md，再進行下一階段工作。')
def cmd_archive(a):
 s=parse_state(STATE)
 if s.phase!='VERIFICATION' or s.verification_passed!='yes':die('archive 需要 VERIFICATION 且 Verification passed=yes',50)
 if s.active_change!=a.change:die('change 與 STATE 不一致',41)
 ok,why=approved_profile_status(ROOT,s)
 if not ok:die(f'archive 需要 PROJECT-PROFILE 與人類批准的內容一致。\n{why}',44)
 accepted=_accepted_evidence_from_log(a.change)
 if accepted is None:die('state-log 找不到 verification-pass 所接受的 core evidence 記錄；請重跑 verification-pass',51)
 rel,expected=accepted
 canonical=f'workflow/evidence/{a.change}/core/'
 if not rel.startswith(canonical) or '..' in rel:
  die(f'state-log 記錄的 evidence 路徑不在 canonical 位置（{canonical}）：{rel}',51)
 tail=rel[len(canonical):]
 if '/' in tail:die(f'core evidence 必須是 core/ 的直接子檔案，不得位於子目錄：{rel}',51)
 c=ROOT/rel
 if not CORE_NAME_RE.fullmatch(tail):
  die(f'state-log 記錄的 evidence 檔名不符 core evidence 格式：{rel}',51)
 if not c.exists():die(f'verification-pass 接受的 core evidence 已不存在：{rel}',51)
 actual=_sha256(c)
 if actual!=expected:die(f'core evidence 已被更動：{rel}（digest 不符）',51)
 ok,why=core_evidence_status(c,a.change)
 if not ok:die(f'core evidence 未通過：{why}',51)
 validate_browser(a.change);transition(s,replace(s,phase='ARCHIVE',last_updated=now_iso()),'archive','machine-verified','Evidence complete')
def cmd_revert(a):
 s=parse_state(STATE)
 if s.phase=='ARCHIVE':die('已 ARCHIVE 的 change 不可 revert；請建立新的 OpenSpec change',58)
 if s.active_change!=a.change:die('change 與 STATE 不一致',41)
 bf=browser_file(a.change)
 if bf.exists():
  stale=bf.with_name('browser.'+now_iso().replace(':','').replace('+','_')+'.stale.md')
  bf.replace(stale);print(f'Browser evidence marked stale: {stale.name}')
 transition(s,replace(s,phase='SPECIFICATION',spec_approved='no',test_design_approved='no',verification_passed='no',approved_by='none',last_updated=now_iso()),'revert-to-spec','ai-or-human',a.reason or 'Spec gap discovered')

def cmd_control_plane_commit(args):
 s=parse_state(STATE)
 try: changes=staged_changes(ROOT)
 except Exception as e: die(f"無法取得 staged changes: {e}",70)
 if not changes: die("沒有 staged 檔案",71)
 # Every side of every mutation must remain inside Control Plane.
 invalid=[]
 for ch in changes:
  for p in ch.paths:
   if not path_is_control_plane(p,s.phase): invalid.append(f"{ch.status}: {p}")
 # STATE and state-log cannot be deleted or renamed, even through the maintenance path.
 protected=[]
 for ch in changes:
  if ch.status in {'D','R'} and any(p in {'workflow/STATE.md','workflow/state-log.md'} for p in ch.paths):
   protected.append(f"{ch.status}: "+" -> ".join(ch.paths))
 if protected: die('STATE/state-log 不得刪除或改名:\n  - '+'\n  - '.join(protected),74)
 if invalid: die('control-plane-commit 只能包含 Control Plane mutations:\n  - '+'\n  - '.join(invalid),72)
 print("Control Plane mutations to commit:")
 for ch in changes: print(f"  - {ch.status}: "+(" -> ".join(ch.paths) if ch.status=='R' else ch.paths[0]))
 if getattr(args,"dry_run",False):
  print("DRY RUN: 未進行 commit。");return
 actor=tty_human_confirm("control-plane-commit","CONTROL-PLANE")
 cp=[ch for ch in changes if not all(p in {'workflow/STATE.md','workflow/state-log.md'} for p in ch.paths)]
 digest=control_plane_digest(ROOT,cp,'staged')
 parent=git_sha()
 before=LOG.read_text(encoding="utf-8") if LOG.exists() else ""
 append_log('control-plane-commit',actor,s.phase,s.phase,s.active_change,'Human-authorized Control Plane maintenance',extra={'Parent SHA':parent,'Control Plane digest':digest})
 subprocess.run(["git","-C",str(ROOT),"add","workflow/state-log.md"],check=True)
 cr=subprocess.run(["git","-C",str(ROOT),"commit","--no-verify","-m","chore(control-plane): authorized maintenance"],capture_output=True,text=True)
 if cr.returncode!=0:
  LOG.write_text(before,encoding="utf-8")
  subprocess.run(["git","-C",str(ROOT),"add","workflow/state-log.md"],capture_output=True)
  die(f"Control Plane commit 失敗，audit log 已回滾，exit={cr.returncode}",73)
 print("Control Plane commit completed with TTY authorization and audit log.")

def _fmt_change(c):
 return c.status+': '+(' -> '.join(c.paths) if c.status=='R' else c.paths[0])

def _playwright_status():
 import json
 pkg=ROOT/'package.json'
 declared=False
 if pkg.exists():
  try:
   d=json.loads(pkg.read_text(encoding='utf-8'))
   deps={**(d.get('dependencies') or {}),**(d.get('devDependencies') or {})}
   declared='@playwright/test' in deps
  except Exception:declared=False
 installed=(ROOT/'node_modules/@playwright/test').exists() or bool(shutil.which('playwright'))
 if declared and installed:return 'OK',''
 if declared and not installed:return 'DECLARED_NOT_INSTALLED','package.json 已宣告 @playwright/test，但尚未安裝（npm install）'
 return 'MISSING','尚未安裝 @playwright/test；Web 專案的 Browser Gate 需要它'

def _devtools_mcp_status():
 if not shutil.which('claude'):return 'UNKNOWN','找不到 claude CLI，無法確認 Chrome DevTools MCP'
 try:
  r=subprocess.run(['claude','mcp','list'],capture_output=True,text=True,timeout=20)
 except Exception as e:return 'UNKNOWN',f'無法查詢 MCP 清單: {e}'
 if r.returncode!=0:return 'UNKNOWN','claude mcp list 執行失敗'
 return ('OK','') if 'chrome-devtools' in r.stdout.lower() else ('MISSING','未設定 Chrome DevTools MCP')

def _print_web_tooling():
 if project_web_status(ROOT)!='WEB':return
 pw,pw_why=_playwright_status();mcp,mcp_why=_devtools_mcp_status()
 print(f'Web verification — Playwright: {pw}'+(f'（{pw_why}）' if pw_why else ''))
 print(f'Web verification — Chrome DevTools MCP: {mcp}'+(f'（{mcp_why}）' if mcp_why else ''))
 if pw!='OK' or mcp!='OK':
  print('注意：Web 專案在 Browser Gate 之前必須備妥上述工具；MCP 不可用時的替代做法見 workflow/BROWSER-VERIFICATION.md。')

def _print_enforcement():
 info=repository_enforcement(ROOT)
 print(f"Repository enforcement: {info['state']}")
 if info['hook']:
  # 用 lexical relpath，不 resolve()：symlink 情況下 resolve() 會顯示目標檔，
  # 與下一行「這是 symlink」的理由自相矛盾，正好在使用者最需要看清楚時誤導。
  rel=os.path.relpath(info['hook'],str(ROOT))
  if rel.startswith('..'):rel=info['hook']
  print(f"Effective pre-commit: {rel}")
  if info.get('symlink'):print(f"Effective pre-commit is a symlink to: {info.get('resolved')}")
  print(f"Hook executable: {'YES' if info['executable'] else 'NO'}")
  if info['index_mode']:print(f"Hook index mode: {info['index_mode']}")
  if info['head_mode']:print(f"Hook HEAD mode: {info['head_mode']}")
  if info['chained'] is not None:print(f"Starter Gate chained: {'YES' if info['chained'] else 'NO'}")
 if info['reason']:print(f"Reason: {info['reason']}")
 if info['fix']:print(f"Fix: {info['fix']}")
 if not enforcement_is_active(info):
  print('注意：本機 Repository enforcement 未生效；目前只剩 CI audit 與 PR review 兩層防護。')
 return info

def cmd_enforcement_status(args):
 if getattr(args,'probe',False):
  hook=effective_pre_commit_hook(ROOT)
  if hook is None or not hook.is_file():die('找不到有效的 pre-commit hook；無法進行行為驗證',5)
  # F0 必須在**任何 probe 執行之前**捕獲。hook 是會被實際執行的程式，probe 之後
  # 才採樣等於讓被驗證的對象決定 receipt 的內容。見 finalize_probe_receipt。
  before=probe_fingerprint(ROOT,hook)
  print(f'正在對 {hook} 執行行為驗證（使用暫時 index，不動真實 index/worktree）…')
  r=probe_enforcement(ROOT)
  if not r['ok']:
   if r['output']:print('--- hook 輸出 ---');print(r['output'])
   die(f"行為驗證失敗：{r['reason']}",5)
  print('✓ 本機行為驗證通過：hook 確實攔下了 Control Plane mutation')
  # 第二次驗證是必要的，不是加強。本機 probe 跑的是 worktree，fresh clone 拿到的是 HEAD；
  # 兩者可以不同（只 staged、HEAD 存空轉版、worktree 用 symlink 指向真 gate、
  # HEAD 的 checker 被換成空轉），而那四種本機 probe 全部會通過。
  info=repository_enforcement(ROOT)
  if not info.get('hooks_dir_rel'):
   # 有效 hook 對應不到 worktree 內的路徑（例如它在 .git/hooks 裡）。此時 HEAD 快照
   # 根本沒有這個 hook，probe 會失敗於「找不到 hook」而不是真正的原因。直接報結構理由。
   die(f"{info['reason']}\n（本機 hook 可執行，但它不是版本控管的檔案，clone 之後不存在）",5)
  print('正在對 HEAD 快照執行同一套行為驗證（fresh clone 拿到的就是這份）…')
  h=probe_head_enforcement(ROOT,info.get('hooks_dir_rel'))
  if not h['ok']:
   if h['output']:print('--- HEAD 快照 hook 輸出 ---');print(h['output'])
   die(f"HEAD 快照行為驗證失敗：{h['reason']}\n"
       '本機 hook 有效，但 clone 之後不生效 —— Repository enforcement 不成立。',5)
  print('✓ HEAD 快照行為驗證通過：clone 之後 gate 仍然生效')
  ok,why=finalize_probe_receipt(ROOT,hook,before)
  if not ok:die(why,5)
 info=_print_enforcement()
 if not enforcement_is_active(info):raise SystemExit(4)

def cmd_check_install_conflicts(_):
 conflicts,overwrites=installation_preflight(ROOT)
 if conflicts:
  print('Brownfield Starter detected existing Control Plane conflicts:',file=sys.stderr)
  for c in conflicts: print('  - '+_fmt_change(c),file=sys.stderr)
  print('\nStarter will not auto-overwrite tracked Control Plane files.',file=sys.stderr)
  print('請先人工合併後 stage Starter + resolved files，再執行：',file=sys.stderr)
  print('  python3 workflow/bin/workflow_transition.py adopt-control-plane --dry-run',file=sys.stderr)
  print('  python3 workflow/bin/workflow_transition.py adopt-control-plane',file=sys.stderr)
 if overwrites:
  if conflicts: print('',file=sys.stderr)
  print('Brownfield Starter detected tracked Starter-file overwrites:',file=sys.stderr)
  for c in overwrites: print('  - '+_fmt_change(c),file=sys.stderr)
  print('\nStarter will not silently overwrite tracked project documentation/configuration.',file=sys.stderr)
  print('\n每個檔案請擇一處理：',file=sys.stderr)
  print('  (a) 採用 Starter 版本：保持目前 Starter 內容，執行 git add <path>',file=sys.stderr)
  print('  (b) 保留原專案版本：執行 git restore --source=HEAD -- <path>',file=sys.stderr)
  print('  (c) 合併兩者：手動編輯後執行 git add <path>',file=sys.stderr)
  print('\n全部處理完成後，以一般 commit 保存（此時 Gate 尚未啟用）：',file=sys.stderr)
  print('  git commit -m "chore: reconcile starter files"',file=sys.stderr)
  print('\n完成後重新執行：',file=sys.stderr)
  print('  bash workflow/bin/bootstrap.sh',file=sys.stderr)
 if conflicts or overwrites:
  raise SystemExit(2 if conflicts else 3)
 print('No tracked Brownfield installation conflicts or overwrites detected.')

def cmd_adopt_control_plane(args):
 s=parse_state(STATE)
 if git_sha()=='NO_HEAD' or subprocess.run(['git','-C',str(ROOT),'cat-file','-e','HEAD:workflow/STATE.md'],capture_output=True).returncode==0:
  die('adopt-control-plane 只適用於 Brownfield 首次安裝且 HEAD 尚未包含 workflow/STATE.md',75)
 try: changes=staged_changes(ROOT)
 except Exception as e: die(f'無法取得 staged changes: {e}',70)
 if not changes: die('沒有 staged 檔案',71)
 unexpected=installation_unexpected_changes(changes)
 print('Brownfield adoption staged mutations:')
 for c in changes: print('  - '+c.status+': '+(' -> '.join(c.paths) if c.status=='R' else c.paths[0]))
 if unexpected:
  detail='\n  - '.join(c.status+': '+(' -> '.join(c.paths) if c.status=='R' else c.paths[0]) for c in unexpected)
  die('adopt-control-plane 不得包含非 Starter staged mutations:\n  - '+detail,79)
 conflicts=installation_conflicts(ROOT)
 if not conflicts: die('目前沒有需要 adopt 的既有 Control Plane mutation；請使用正常 bootstrap installation baseline',76)
 cp=[c for c in changes if change_touches_control_plane(c,s.phase)]
 state_add=[c for c in changes if c.status=='A' and c.new_path=='workflow/STATE.md']
 if len(state_add)!=1 or not staged_state_is_pristine(ROOT): die('adopt 安裝必須新增 pristine staged workflow/STATE.md',77)
 if getattr(args,'dry_run',False): print('DRY RUN: 未進行 commit。');return
 actor=tty_human_confirm('adopt-control-plane','ADOPT-CONTROL-PLANE')
 # R5：安裝 commit 就必須是 100755，否則 clone 之後 git 不會執行這個 hook。
 hook=ROOT/'.githooks/pre-commit'
 if hook.is_file():
  hook.chmod(hook.stat().st_mode|0o111)
  ur=subprocess.run(['git','-C',str(ROOT),'update-index','--add','--chmod=+x','.githooks/pre-commit'],capture_output=True,text=True)
  if ur.returncode!=0:die(f'無法將 .githooks/pre-commit 標記為可執行：{ur.stderr.strip()}',80)
 digest=control_plane_digest(ROOT,[c for c in cp if not all(x in {'workflow/STATE.md','workflow/state-log.md'} for x in c.paths)],'staged')
 before=LOG.read_text(encoding='utf-8') if LOG.exists() else ''
 append_log('install-adopt-control-plane',actor,s.phase,s.phase,s.active_change,'Human-reviewed Brownfield Control Plane adoption',extra={'Control Plane digest':digest})
 subprocess.run(['git','-C',str(ROOT),'add','workflow/state-log.md'],check=True)
 cr=subprocess.run(['git','-C',str(ROOT),'commit','--no-verify','-m','chore(control-plane): adopt AI project starter'],capture_output=True,text=True)
 if cr.returncode!=0:
  LOG.write_text(before,encoding='utf-8');subprocess.run(['git','-C',str(ROOT),'add','workflow/state-log.md'],capture_output=True)
  die(f'adopt-control-plane commit 失敗，audit log 已回滾，exit={cr.returncode}',78)
 print('Brownfield Control Plane adoption committed with audit record.')

def main():
 ap=argparse.ArgumentParser();sp=ap.add_subparsers(dest='cmd',required=True);sp.add_parser('status').set_defaults(fn=cmd_status);sp.add_parser('doctor').set_defaults(fn=cmd_doctor)
 p=sp.add_parser('set-mode');p.add_argument('mode',choices=['GREENFIELD','BROWNFIELD']);p.set_defaults(fn=cmd_set_mode)
 p=sp.add_parser('start-change');p.add_argument('change');p.set_defaults(fn=cmd_start_change)
 p=sp.add_parser('submit-for-review');p.add_argument('change');p.set_defaults(fn=cmd_submit)
 for n,f in [('approve-spec',cmd_approve_spec),('approve-tests',cmd_approve_tests),('start-engineering',cmd_start_engineering),('verification-pass',cmd_verification_pass),('archive',cmd_archive)]:p=sp.add_parser(n);p.add_argument('change');p.set_defaults(fn=f)
 p=sp.add_parser('revert-to-spec');p.add_argument('change');p.add_argument('--reason',default='');p.set_defaults(fn=cmd_revert)
 p=sp.add_parser('control-plane-commit');p.add_argument('--dry-run',action='store_true');p.set_defaults(fn=cmd_control_plane_commit)
 sp.add_parser('check-install-conflicts').set_defaults(fn=cmd_check_install_conflicts)
 p=sp.add_parser('enforcement-status');p.add_argument('--probe',action='store_true',
  help='實際執行有效 hook 並確認它會攔下 Control Plane mutation；通過後才能標為 ACTIVE_CHAINED');p.set_defaults(fn=cmd_enforcement_status)
 p=sp.add_parser('adopt-control-plane');p.add_argument('--dry-run',action='store_true');p.set_defaults(fn=cmd_adopt_control_plane)
 a=ap.parse_args()
 # 單一驗證點，涵蓋**所有**接受 change 參數的子指令。刻意不做成 argparse 的 type=：
 # 那條路徑會以 exit 2 結束，跟 Starter 其他 gate 的專屬 exit code 混在一起，
 # 呼叫端分不出「參數打錯」與「gate 拒絕」。
 change=getattr(a,'change',None)
 if change is not None:
  err=validate_change_id(change)
  if err:die(err,31)
 try:
  a.fn(a)
 except ValueError as exc:
  # STATE.md 內容不合法（含歷史上被污染的檔案）必須是可讀的錯誤，不是 traceback。
  # 之前這裡會直接噴 stack trace，讓「Control Plane 壞掉」看起來像「工具壞掉」。
  die(f'workflow/STATE.md 無法解析：{exc}\n'
      '  Control Plane 檔案已損壞或被污染，請由人類檢視 git 歷史後修復。',42)
if __name__=='__main__':main()

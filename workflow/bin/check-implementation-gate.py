#!/usr/bin/env python3
from pathlib import Path
import re,subprocess,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'workflow/bin'))
from workflow_state import (
    parse_state,path_is_control_plane,path_is_ai_writable_non_product,
    state_hash_text,initial_state_hash,CORE_EVIDENCE_RE,BROWSER_EVIDENCE_RE,evidence_write_allowed,
    staged_changes,change_touches_control_plane,installation_baseline,installation_unexpected_changes,
    implementation_authorized,
)
STATE=ROOT/'workflow/STATE.md';LOG=ROOT/'workflow/state-log.md'
STATE_PATH='workflow/STATE.md';LOG_PATH='workflow/state-log.md'

def fail(msg,code):print(f'DENY: {msg}',file=sys.stderr);sys.exit(code)
try:s=parse_state(STATE)
except Exception as e:fail(f'STATE invalid (fail-closed): {e}',10)
if '--staged' not in sys.argv:sys.exit(0)
head=subprocess.run(['git','-C',str(ROOT),'rev-parse','--verify','HEAD'],capture_output=True,text=True)
if head.returncode!=0:print('NOTE: initial commit (repo has no HEAD); gate bypassed once',file=sys.stderr);sys.exit(0)
try:changes=staged_changes(ROOT)
except Exception as e:fail(f'git diff failed (fail-closed): {e}',13)

# Track both sides of rename/delete, not just the destination path.
def touches(ch,path): return path in ch.paths
state_changes=[c for c in changes if touches(c,STATE_PATH)]
log_changes=[c for c in changes if touches(c,LOG_PATH)]
state_changed=bool(state_changes);log_changed=bool(log_changes)

# STATE/state-log are special audit assets: deletion or rename is never a normal commit.
for label,items in [('workflow/STATE.md',state_changes),('workflow/state-log.md',log_changes)]:
    destructive=[c for c in items if c.status in {'D','R'}]
    if destructive:
        fail(f'{label} 不得刪除或改名；這會破壞 workflow/audit continuity',26 if label==STATE_PATH else 17)

# Starter first-install baseline in an existing repo is allowed only before STATE exists in HEAD and with pristine staged STATE.
state_in_head=subprocess.run(['git','-C',str(ROOT),'cat-file','-e','HEAD:workflow/STATE.md'],capture_output=True).returncode==0
first_install=not state_in_head and any(c.status=='A' and c.new_path==STATE_PATH for c in changes)
if first_install:
    if not installation_baseline(ROOT,changes,'staged'):
        cp_fail=[c for c in changes if change_touches_control_plane(c,'ENGINEERING') and c.status!='A']
        details='\n  - '.join(f"{c.status}: {' -> '.join(c.paths) if c.status=='R' else c.paths[0]}" for c in cp_fail) or '(none)'
        fail('workflow/STATE.md 不在 Git history 中，但 staged mutations 不符合 sanctioned Starter installation baseline。\n造成失敗的 Control Plane mutations:\n  - '+details+'\n若這些是既有 Control Plane，請人工合併後使用 adopt-control-plane；不要反覆重跑 bootstrap。',24)
    unexpected=installation_unexpected_changes(changes)
    if unexpected:
        detail='\n  - '.join(c.status+': '+(' -> '.join(c.paths) if c.status=='R' else c.paths[0]) for c in unexpected)
        fail('Starter installation baseline 不得混入產品變更\n  - '+detail,25)
    print('NOTE: existing-repo Starter installation baseline allowed before Gate activation',file=sys.stderr);sys.exit(0)

# state-log may only append; actual file deletion/rename was rejected above.
if log_changed:
    d=subprocess.run(['git','-C',str(ROOT),'diff','--cached','--unified=0','--','workflow/state-log.md'],capture_output=True,text=True)
    if d.returncode!=0:fail('state-log diff failed',16)
    for line in d.stdout.splitlines():
        if line.startswith('-') and not line.startswith('---'):fail('state-log 必須 append-only',17)

if state_changed:
    if not log_changed:fail('STATE 變更必須同時包含 state-log',14)
    ss=subprocess.run(['git','-C',str(ROOT),'show',':workflow/STATE.md'],capture_output=True,text=True)
    sl=subprocess.run(['git','-C',str(ROOT),'show',':workflow/state-log.md'],capture_output=True,text=True)
    if ss.returncode!=0 or sl.returncode!=0:fail('無法讀 staged Control Plane',18)
    hashes=re.findall(r'^- State hash:\s*([0-9a-f]{64})\s*$',sl.stdout,re.M)
    if not hashes or hashes[-1]!=state_hash_text(ss.stdout):fail('STATE hash 與 state-log 最後一筆不一致',19)

# Any mutation touching a Control Plane path on either side of rename/delete needs the dedicated human path.
control=[]
for c in changes:
    if any(p in {STATE_PATH,LOG_PATH} for p in c.paths):continue
    if change_touches_control_plane(c,s.phase):
        control.append(f'{c.status}: '+(' -> '.join(c.paths) if c.status=='R' else c.paths[0]))
if control:
    fail('Control Plane 變更不可透過一般 commit；請由人類執行 workflow_transition.py control-plane-commit:\n  - '+'\n  - '.join(control),20)

# Evidence 的可寫範圍由「哪一個 change、在哪一個階段」決定，不由全域 phase 決定。
# 原本 core/browser evidence 在下面的 product 判定裡被無條件豁免（它們由 machine 產生、
# 不算產品程式碼），而那個豁免完全沒有分階段也沒有分 change。第一版修法用
# `s.phase=='ARCHIVE'` 補洞，但那只擋住「archive 完就地改」這一種；只要執行
# `start-change B`，phase 離開 ARCHIVE，change A 的已封存 evidence 立刻又可寫，
# 而 A 不會再被任何 archive 或 verification 比對。判準必須是所有權，見
# workflow_state.evidence_write_allowed。
frozen=[]
for c in changes:
    for pth in c.paths:
        if not (CORE_EVIDENCE_RE.match(pth) or BROWSER_EVIDENCE_RE.match(pth)):continue
        if evidence_write_allowed(pth,s):continue
        frozen.append(f'{c.status}: '+(' -> '.join(c.paths) if c.status=='R' else pth))
        break
if frozen:
    fail('不得修改不屬於目前工作範圍的 evidence：\n  - '+'\n  - '.join(frozen)
         +f'\n目前 change={s.active_change}、phase={s.phase}。'
         '\nevidence 只能由目前 active change 在 ENGINEERING/VERIFICATION 期間寫入；'
         '\n已封存的、以及其他 change 的 evidence 一律凍結。',16)

# Determine product impact from every side of a mutation. This prevents renaming product/CP out to an AI-writable destination.
product=[]
for c in changes:
    if any(p in {STATE_PATH,LOG_PATH} for p in c.paths):continue
    mutation_product=False
    for p in c.paths:
        # evidence 走 ownership 判準；不合格的在上面已經硬性失敗，到不了這裡。
        if path_is_ai_writable_non_product(p,s.phase) or evidence_write_allowed(p,s):
            continue
        mutation_product=True
    if mutation_product:
        product.append(f'{c.status}: '+(' -> '.join(c.paths) if c.status=='R' else c.paths[0]))
if state_changed and product:fail('Control Plane transition 與產品程式碼不得同 commit',15)
if product:
    # 不能只看 s.implementation_allowed —— 那是 STATE 內部的推導，看不到
    # PROJECT-PROFILE 是否已經被換成人類沒批准過的內容。共用判準見
    # approved_profile_status 的說明（兩個實測繞過）。
    ok,why=implementation_authorized(ROOT,s)
    if not ok:fail(why+'；blocked:\n  - '+'\n  - '.join(product),12)

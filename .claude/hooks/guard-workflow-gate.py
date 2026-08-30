#!/usr/bin/env python3
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'workflow/bin'))
from workflow_state import (parse_state,path_is_control_plane,path_is_ai_writable_non_product,
 evidence_write_allowed,is_evidence_path,project_web_status,implementation_authorized,
 api_verification_required,CORE_EVIDENCE_RE,BROWSER_EVIDENCE_RE,API_EVIDENCE_RE)
def deny(msg):print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':msg}},ensure_ascii=False));sys.exit(0)

def main():
    try:payload=json.load(sys.stdin)
    except Exception:payload={}
    try:s=parse_state(ROOT/'workflow/STATE.md')
    except Exception as e:deny(f'STATE invalid; fail-closed: {e}')
    raw=(payload.get('tool_input') or {}).get('file_path') or (payload.get('tool_input') or {}).get('path')
    if not raw:deny('無法判定寫入路徑；fail-closed')
    try:rel=Path(raw).resolve().relative_to(ROOT.resolve()).as_posix()
    except Exception:deny('禁止寫入 Repository 外部/未知位置')
    if CORE_EVIDENCE_RE.match(rel):deny(f'Machine-owned core evidence 不允許 AI Write/Edit：{rel}')
    if BROWSER_EVIDENCE_RE.match(rel) and project_web_status(ROOT)!='WEB':deny(f'只有 WEB 專案允許 AI 寫 browser.md：{rel}')
    if API_EVIDENCE_RE.match(rel) and not api_verification_required(ROOT):deny(f'只有 API 專案允許 AI 寫 api.md：{rel}')
    if path_is_control_plane(rel,s.phase):deny(f'Control Plane 不允許一般 AI Write/Edit：{rel}')
    if path_is_ai_writable_non_product(rel,s.phase):sys.exit(0)
    # evidence 走所有權判準，與 pre-commit gate 同源。
    if is_evidence_path(rel) and evidence_write_allowed(rel,s):sys.exit(0)
    # 必須與 pre-commit gate 用同一條判準。只看 derived flag 的話，這個 hook 會說
    # 「可以寫」，然後 pre-commit 說「不能 commit」—— agent 白做一整輪工。
    # 這一層是即時回饋不是 enforcement（見 GATES.md），但回饋錯了比沒有回饋更糟。
    ok,why=implementation_authorized(ROOT,s)
    if ok:sys.exit(0)
    deny(f'{why}；目前不得修改產品程式碼：{rel}')

# **這一層自己也要 fail-closed。**
# PreToolUse hook 非零退出（非 exit 2）不會阻擋工具呼叫 —— 也就是說
# guard 崩掉時等於放行。實際踩到過：改 import 時漏掉一個名稱，NameError 讓整支
# 程式沒有輸出，而所有寫入都被視為允許。守衛壞掉必須是拒絕，不是沉默。
try:
    main()
except SystemExit:
    raise
except BaseException as e:
    deny(f'guard hook 發生未預期錯誤；fail-closed: {type(e).__name__}: {e}')

#!/usr/bin/env python3
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'workflow/bin'))
from workflow_state import parse_state,path_is_control_plane,path_is_ai_writable_non_product,CORE_EVIDENCE_RE,BROWSER_EVIDENCE_RE,project_web_status
def deny(msg):print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':msg}},ensure_ascii=False));sys.exit(0)
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
if path_is_control_plane(rel,s.phase):deny(f'Control Plane 不允許一般 AI Write/Edit：{rel}')
if path_is_ai_writable_non_product(rel,s.phase):sys.exit(0)
if s.implementation_allowed:sys.exit(0)
deny(f'Derived Implementation allowed=no；目前不得修改產品程式碼：{rel}')

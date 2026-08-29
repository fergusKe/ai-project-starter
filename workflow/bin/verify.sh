#!/usr/bin/env bash
set -u
MODE="${1:---pre-commit}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

STATE_PY="${ROOT}/workflow/bin/workflow_state.py"

# --- Core verification 政策 -------------------------------------------------
policy_line="$(python3 "$STATE_PY" --verification-policy)" || {
  echo "ERROR: Core verification policy 無效；請檢查 PROJECT-PROFILE.md" >&2; exit 34; }
policy="$(printf '%s' "$policy_line" | cut -f1)"
custom_command="$(printf '%s' "$policy_line" | cut -f2)"
exception_reason="$(printf '%s' "$policy_line" | cut -f3)"

# --- Web Gate ---------------------------------------------------------------
web_status="UNRESOLVED";web_rc=0
web_status="$(python3 "$STATE_PY" --is-web)" || web_rc=$?
if [[ "$MODE" == "--full" && "$web_rc" == "2" ]];then echo "ERROR: Web Gate 判定未決；請先完成 PROJECT-PROFILE" >&2;exit 33;fi
if [[ "$MODE" == "--full" && "$web_status" == "WEB" ]];then
 [[ -f package.json ]] || { echo "ERROR: Web 專案找不到 package.json" >&2;exit 31; }
 if ! python3 - <<'PY'
import json,sys,pathlib
try: s=json.loads(pathlib.Path('package.json').read_text(encoding='utf-8')).get('scripts') or {}
except Exception: s={}
sys.exit(0 if any(k in s for k in ('test:e2e','e2e','playwright')) else 1)
PY
 then echo "ERROR: Web 專案缺少 Playwright E2E script" >&2;exit 30;fi
fi

# --- 組出要執行的 checks ----------------------------------------------------
names=();cmds=()
plan_mode="pre-commit"; [[ "$MODE" == "--full" ]] && plan_mode="full"
unavailable=""

if [[ "$policy" == "not-applicable" ]]; then
  if [[ -z "$exception_reason" ]]; then
    echo "ERROR: Core verification policy=not-applicable 必須填寫 Verification exception reason" >&2
    exit 35
  fi
elif [[ "$policy" == "custom" ]]; then
  if [[ -z "$custom_command" ]]; then
    echo "ERROR: Core verification policy=custom 必須填寫 Custom verification command" >&2
    exit 36
  fi
  names+=("custom");cmds+=("$custom_command")
else
  while IFS=$'\t' read -r st nm cm rs; do
    [[ -z "${st:-}" ]] && continue
    if [[ "$st" == "unavailable" ]]; then
      unavailable+="  - ${nm}: ${cm}"$'\n'"      ${rs}"$'\n'
    else
      names+=("$nm");cmds+=("$cm")
    fi
  done < <(python3 "$STATE_PY" --verification-plan "$plan_mode")
fi

if [[ -n "$unavailable" ]]; then
  echo "ERROR: 下列 check 已在專案中配置，但目前環境無法執行：" >&2
  printf '%s' "$unavailable" >&2
  echo "  請安裝／啟用對應工具後重跑；不得以「沒有適用檢查」略過。" >&2
  exit 37
fi

if [[ "$MODE" == "--full" && "${STARTER_SELF_TESTS:-0}" == "1" && -d workflow/tests ]]; then
  names+=("starter-self-tests")
  cmds+=("PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s workflow/tests -t .")
fi

selected=${#cmds[@]}
if [[ "$MODE" == "--full" && "$policy" != "not-applicable" && $selected -eq 0 ]]; then
  echo "ERROR: full verification 至少需要一個可執行的 automated check，目前為 0。" >&2
  echo "  若本 repo 確實沒有任何自動化檢查，請在 PROJECT-PROFILE.md 明確宣告：" >&2
  echo "    Core verification policy: not-applicable" >&2
  echo "    Verification exception reason: <非空理由>" >&2
  exit 38
fi

# --- 執行 -------------------------------------------------------------------
failed=0;records="";executed=0
if [[ $selected -eq 0 ]];then echo "No checks selected (policy=${policy}).";else
 echo "Running ${selected} check(s) (${MODE}, policy=${policy})..."
 for i in "${!cmds[@]}";do
  echo;echo "=== ${names[$i]} ===";bash -c "${cmds[$i]}";st=$?
  executed=$((executed+1))
  records+=$'\n'"### ${names[$i]}"$'\n\n'"Command: ${cmds[$i]}"$'\n'"Exit code: ${st}"$'\n'
  if [[ $st -ne 0 ]];then echo "✗ ${names[$i]} failed (${st})";failed=1;else echo "✓ ${names[$i]} passed";fi
 done
fi

# --- Evidence（schema 2）----------------------------------------------------
if [[ "$MODE" == "--full" ]];then
 change="$(grep '^Active OpenSpec change:' workflow/STATE.md | sed 's/^Active OpenSpec change:[[:space:]]*//')"
 [[ -n "$change" && "$change" != "none" ]] || { echo "ERROR: full verification 需要 Active OpenSpec change" >&2;exit 32; }
 outcome="PASS"
 if [[ "$policy" == "not-applicable" ]]; then outcome="NOT_APPLICABLE"; fi
 if [[ $failed -ne 0 ]]; then outcome="FAIL"; fi
 ts="$(python3 -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))')"
 edir="${ROOT}/workflow/evidence/${change}";mkdir -p "${edir}/core";core="${edir}/core/${ts}.md"
 {
   echo "# Core Verification Evidence"
   echo
   echo "Core evidence schema: 2"
   echo "Change: ${change}"
   echo "Timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
   echo "Verification policy: ${policy}"
   echo "Checks selected: ${selected}"
   echo "Checks executed: ${executed}"
   [[ "$policy" == "not-applicable" ]] && echo "Exception reason: ${exception_reason}"
   [[ -n "$records" ]] && printf '%s\n' "$records"
   echo
   echo "Outcome: ${outcome}"
   echo "Overall exit code: ${failed}"
 } > "$core"
 if [[ "$web_status" == "NON_WEB" ]];then cat > "${edir}/browser.md" <<EOF
# Browser Verification Evidence

Browser Gate: NOT APPLICABLE
Reason: PROJECT-PROFILE 明確判定為非 Web 專案。
EOF
 fi
 echo "Core evidence: ${core}"
fi
exit $failed

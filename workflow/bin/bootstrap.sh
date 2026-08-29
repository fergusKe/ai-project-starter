#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)";cd "$ROOT"

# Hook mode is part of repository enforcement; set it before any baseline commit.
if [[ -f "$ROOT/.githooks/pre-commit" ]]; then
  chmod +x "$ROOT/.githooks/pre-commit"
fi

verify_starter_baseline() {
 local missing=0
 for required in workflow/STATE.md workflow/bin/workflow_transition.py .githooks/pre-commit; do
  if ! git cat-file -e "HEAD:$required" 2>/dev/null; then echo "✗ Starter installation incomplete: $required not in Git history" >&2; missing=1; fi
 done
 [[ "$missing" -eq 0 ]] || { echo "  Gate 尚未正確安裝，請修正後重跑 bootstrap。" >&2; return 1; }
}

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1;then git init;echo "✓ initialized git";else echo "✓ git repository detected";fi
command -v node >/dev/null 2>&1 && echo "✓ node $(node -v)" || echo "! Node not found"
command -v openspec >/dev/null 2>&1 && echo "✓ OpenSpec detected" || echo "! OpenSpec not found; install @fission-ai/openspec"

# Gate must enter history before it is activated.
if ! git rev-parse --verify HEAD >/dev/null 2>&1;then
 git add -A
 if git commit -q -m "chore: bootstrap AI project starter baseline";then verify_starter_baseline || exit 1; echo "✓ new-repo Starter baseline committed and verified";else echo "✗ baseline commit failed; configure git user.name/user.email and rerun bootstrap" >&2; exit 1;fi
elif ! git cat-file -e HEAD:workflow/STATE.md >/dev/null 2>&1;then
 # Brownfield preflight: never silently overwrite tracked Control Plane files.
 set +e
 conflict_out="$(python3 workflow/bin/workflow_transition.py check-install-conflicts 2>&1)"
 conflict_rc=$?
 set -e
 if [[ $conflict_rc -eq 2 || $conflict_rc -eq 3 ]]; then
  printf '%s\n' "$conflict_out" >&2
  exit $conflict_rc
 elif [[ $conflict_rc -ne 0 ]]; then
  printf '%s\n' "$conflict_out" >&2
  exit $conflict_rc
 fi
 paths=()
 while IFS= read -r manifest_path || [[ -n "$manifest_path" ]]; do
  manifest_path="${manifest_path%$'\r'}"
  [[ -z "$manifest_path" || "$manifest_path" == \#* ]] && continue
  paths+=("${manifest_path%/}")
 done < workflow/SHIPPED-MANIFEST.txt
 present=()
 for p in "${paths[@]}"; do [[ -e "$p" ]] && present+=("$p"); done
 if [[ ${#present[@]} -eq 0 ]]; then echo "✗ 找不到可安裝的 Starter files" >&2; exit 1; fi
 git add -- "${present[@]}"
 if git diff --cached --quiet;then echo "! no Starter files staged for Brownfield install";else
  if git commit -q -m "chore: install AI project starter control plane";then verify_starter_baseline || exit 1; echo "✓ Brownfield Starter baseline committed and verified before Gate activation";else echo "✗ Brownfield Starter baseline commit failed; configure git user.name/user.email and rerun bootstrap before enabling Gate" >&2; exit 1;fi
 fi
fi
set +e
bash "${ROOT}/workflow/bin/setup-git-hooks.sh"
hooks_rc=$?
set -e
if [[ ${hooks_rc} -ne 0 ]]; then
  echo "" >&2
  echo "✗ Bootstrap 未完成：Repository enforcement 尚未生效。" >&2
  echo "  Starter files 已進入 Git history，但本機 gate 不會執行。" >&2
  echo "  請依上方指示串接後重跑 bootstrap。" >&2
  exit ${hooks_rc}
fi
python3 -m py_compile .claude/hooks/guard-dangerous-commands.py .claude/hooks/guard-workflow-gate.py workflow/bin/*.py
echo "✓ hook/control-plane syntax OK"
bash "$ROOT/workflow/bin/setup-web-verification.sh" || true
python3 "$ROOT/workflow/bin/workflow_transition.py" doctor || true
echo "Next: python3 workflow/bin/workflow_transition.py status"

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)";cd "$ROOT"
PROBE=0
[[ "${1:-}" == "--probe" ]] && PROBE=1

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Git 尚未初始化，略過 hooks。";exit 0; }

# 既有 hook framework 一律不覆蓋（AGENTS.md 政策）。但不得靜默成功 ——
# 未串接 Starter gate 時 Repository enforcement 是失效的，必須讓使用者知道。
report_not_chained() {
  local why="$1"
  echo "" >&2
  echo "⚠ ${why}" >&2
  echo "  Starter 不會覆蓋既有 hook framework，因此 Repository enforcement 目前未生效。" >&2
  echo "" >&2
  python3 workflow/bin/workflow_transition.py enforcement-status >&2 || true
  echo "" >&2
  echo "請在既有的 pre-commit hook 中加入下列一行，把 Starter gate 串接進去：" >&2
  echo "" >&2
  echo "    bash .githooks/pre-commit || exit 1" >&2
  echo "" >&2
  echo "依你的 framework 選一種：" >&2
  echo "" >&2
  echo "  Husky —— 在 .husky/pre-commit 加入這一行：" >&2
  echo "      bash .githooks/pre-commit || exit 1" >&2
  echo "" >&2
  echo "  Lefthook —— 在 lefthook.yml 加入：" >&2
  echo "      pre-commit:" >&2
  echo "        commands:" >&2
  echo "          starter-gate:" >&2
  echo "            run: bash .githooks/pre-commit" >&2
  echo "" >&2
  echo "  pre-commit（framework）—— 在 .pre-commit-config.yaml 加入：" >&2
  echo "      - repo: local" >&2
  echo "        hooks:" >&2
  echo "          - id: starter-gate" >&2
  echo "            name: AI Project Starter gate" >&2
  echo "            entry: bash .githooks/pre-commit" >&2
  echo "            language: system" >&2
  echo "            pass_filenames: false" >&2
  echo "            always_run: true" >&2
  echo "" >&2
  echo "串接之後**必須先 commit**，再執行行為驗證：" >&2
  echo "" >&2
  echo "    git add <你的 hook 檔案> && git commit -m 'chain starter gate'" >&2
  echo "    bash workflow/bin/setup-git-hooks.sh --probe" >&2
  echo "" >&2
  echo "先 commit 不是額外要求：Repository enforcement 的定義是 clone 之後 gate 仍然生效，" >&2
  echo "而 clone 拿到的是 HEAD。還沒 commit 的 bridge，clone 之後不存在。" >&2
  exit 4
}

check_or_probe() {
  local why="$1"
  if python3 workflow/bin/workflow_transition.py enforcement-status >/dev/null 2>&1; then
    echo "✓ Starter gate 已串接且通過行為驗證；Repository enforcement 生效中。"
    exit 0
  fi
  # 靜態找到 bridge 但尚未行為驗證 → 提供明確的一步，不自動執行第三方 hook。
  # 先取出輸出再比對；直接 pipe 會因為 set -o pipefail 取到左側的非零離開碼。
  local status_out
  status_out="$(python3 workflow/bin/workflow_transition.py enforcement-status 2>&1 || true)"
  if printf '%s' "${status_out}" | grep -q "CHAINED_STATIC"; then
    if [[ "${PROBE}" == "1" ]]; then
      if python3 workflow/bin/workflow_transition.py enforcement-status --probe; then
        echo "✓ Starter gate 已串接且通過行為驗證；Repository enforcement 生效中。"
        exit 0
      fi
      echo "" >&2
      echo "✗ 行為驗證失敗：bridge 存在於檔案中，但實際執行時沒有攔下 Control Plane mutation。" >&2
      echo "  請確認該行不在註解、不可達分支或字串中。" >&2
      exit 4
    fi
    echo "" >&2
    echo "⚠ 已在既有 hook 中找到 Starter gate bridge，但尚未做行為驗證。" >&2
    echo "  靜態比對無法證明那一行真的會被執行。請執行：" >&2
    echo "" >&2
    echo "    bash workflow/bin/setup-git-hooks.sh --probe" >&2
    echo "" >&2
    echo "  它會以暫時 index 造一個 Control Plane mutation、實際執行你的 hook，" >&2
    echo "  並確認 gate 會拒絕它。不會動到真實 index 或 worktree。" >&2
    exit 4
  fi
  report_not_chained "${why}"
}

existing="$(git config --get core.hooksPath || true)"

if [[ -n "${existing}" && "${existing}" != ".githooks" ]]; then
  echo "已有 core.hooksPath=${existing}；不覆蓋。"
  check_or_probe "既有 core.hooksPath=${existing}"
fi

if [[ -d .husky || -f lefthook.yml || -f .pre-commit-config.yaml ]]; then
  echo "偵測到既有 hook framework；不覆蓋。"
  check_or_probe "偵測到既有 hook framework"
fi

chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
echo "Git hooks 已啟用：.githooks"

# managed hook 是 Starter 自己的；對未修改的 hook，probe 不會執行第三方流程。
# （probe 仍會寫入 Git object database 與 .git/ 內的 receipt —— 見 workflow_state.probe_enforcement）
if python3 workflow/bin/workflow_transition.py enforcement-status --probe >/dev/null 2>&1; then
  echo "✓ 行為驗證通過：Repository enforcement 生效中。"
else
  echo "" >&2
  echo "✗ hooks 已設定，但行為驗證未通過 —— gate 不會攔下 Control Plane 變更。" >&2
  echo "  請檢查 .githooks/pre-commit 與 workflow/bin/check-implementation-gate.py 是否被修改過。" >&2
  echo "  診斷：python3 workflow/bin/workflow_transition.py enforcement-status --probe" >&2
  exit 4
fi

# 環境設定

先執行：
```bash
bash ./workflow/bin/bootstrap.sh
```

Starter 使用 grill-with-docs（需求探索）、OpenSpec（正式規格）、Superpowers（工程執行）、Playwright（critical E2E）、Chrome DevTools MCP（真實瀏覽器檢查）。

Claude Code project skills 位於 `.claude/skills/`。GitHub CI 依實際 stack/scripts 建立，不套固定模板。

詳細工作規則只以 `AGENTS.md` 為準。

## 人類批准要在哪裡執行

`approve-spec` 與 `approve-tests` **需要真正的 controlling terminal**：

```bash
python3 workflow/bin/workflow_transition.py approve-spec <change>
```

| 執行環境 | 可以嗎 |
|---|---|
| Terminal.app / iTerm / VS Code 內建終端機 | ✅ |
| Claude Code 對話框的 `!` 前綴 | ❌ stdin 不是 TTY |
| 一般 `subprocess` / CI / 腳本 | ❌（這正是重點） |

**這是刻意的。** 如果一般程式呼叫也能通過，整個 Human Approval 就只是一個
可以被腳本填答的表單。

但要把話說準：**這不是「程式絕對拿不到 controlling terminal」。** 刻意配置 pty
的程式可以（Starter 自己的 `workflow/bin/acceptance.py` 就是這樣跑 release
驗收的）。它擋的是**沒有刻意去繞的非互動執行環境** —— 也就是絕大多數 agent
與 CI 的預設形狀。

先用 `doctor` 確認你的環境可以批准：

```bash
python3 workflow/bin/workflow_transition.py doctor | grep 'approve-\*'
# approve-* 可在此環境執行: YES
```

能力邊界：TTY 是**已驗證的非互動邊界**，不是不可偽造的人類身分認證。
團隊情境的真正授權來自 CODEOWNERS + required review，見 `workflow/MERGE-PROTECTION.md`。


### Brownfield 既有 Control Plane
若專案已追蹤 `.claude/settings.json`、`.claude/hooks/**`、`.githooks/**` 或 `workflow/**`，bootstrap 會在 commit 前停止，不會自動覆蓋。請人工合併、stage 後使用 `python3 workflow/bin/workflow_transition.py adopt-control-plane --dry-run` 檢查，再由人類執行 `adopt-control-plane`。

Brownfield 可先執行 `python3 workflow/bin/workflow_transition.py check-install-conflicts` 檢查已追蹤的 Control Plane 衝突。不要在檢查前直接覆蓋既有、未追蹤或被 ignore 的 `.claude/` / `.githooks/` 檔案。

若檢查結果是 tracked Starter-file overwrite，請對每個檔案擇一：`git add <path>` 採用 Starter 版本、`git restore --source=HEAD -- <path>` 保留原版、或手動合併後 `git add <path>`。全部處理後先執行 `git commit -m "chore: reconcile starter files"`，再重跑 bootstrap。

## 外部工具與安裝

**最後人工核對日期：2026-08-29。** 外部工具版本與安裝方式可能變動；Starter CI 不會透過網路持續驗證這些指令，重大版本釋出前應重新人工核對。

以下指令於 2026-08-29 依官方來源重新核對。

### OpenSpec（SPECIFICATION 的建議工具，非 Gate 硬依賴）

需求：Node.js 20.19.0 以上。

```bash
npm install -g @fission-ai/openspec@latest
openspec --version
openspec init
```

Transition CLI **不會呼叫 `openspec` 執行檔** —— 它只檢查 `openspec/changes/<change>/` 目錄與 proposal/spec/tasks 檔案是否存在。因此未安裝 OpenSpec CLI 仍可完整走完 SPECIFICATION 與 SPEC_REVIEW；安裝它是為了更好的撰寫體驗與一致的 artifact 結構。官方來源：https://github.com/Fission-AI/OpenSpec/blob/main/install.md

### grill-with-docs（Discovery 推薦工具，非 Gate 硬依賴）

```bash
npx skills@latest add mattpocock/skills --skill=grill-with-docs
```

之後在 coding agent 中輸入 `/grill-with-docs`。若選擇性安裝，該 skill 依賴 grilling/domain-modeling；安裝整套 skills 可避免缺 primitive。官方來源：https://www.aihero.dev/grill-with-docs

### Superpowers（Engineering 推薦工具，非 Gate 硬依賴）

Claude Code 官方 marketplace：

```text
/plugin install superpowers@claude-plugins-official
```

Codex App / CLI：開啟 `/plugins`，搜尋 `superpowers`，選擇 Install Plugin。官方來源：https://github.com/obra/superpowers

### Playwright（Web Browser Gate 的硬依賴）

Node Web 專案：

```bash
npm install -D @playwright/test@latest
npx playwright install --with-deps
```

`workflow/bin/setup-web-verification.sh` 只協助 Node 專案；其他 stack 需自行接好 `test:e2e` 與 report。官方來源：https://playwright.dev/docs/browsers

### Chrome DevTools MCP（Web Browser Gate 的 runtime inspection 依賴）

MCP client 標準設定：

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

需求：Node.js LTS、Chrome stable、npm。若目前 agent harness 沒有 Chrome DevTools MCP，Web Browser Gate 必須改由具備該能力的 agent/人類完成並留下 evidence；不可假裝已檢查。官方來源：https://github.com/ChromeDevTools/chrome-devtools-mcp

## 既有 linter 的專案：必須排除 Starter 路徑

Starter 自身的 Python 檔案（`workflow/bin/**`、`workflow/tests/**`、`.claude/hooks/**`）
屬於 **Control Plane**，採用者不得以一般 commit 修改。若專案的 linter 掃描整個 repo，
這些檔案會產生大量無法修復的錯誤，導致 VERIFICATION 卡死。

實測數據（G3-B，Python + ruff 專案）：`ruff check .` 產生 168 個錯誤，
其中 **164 個在 Control Plane 檔案裡**，採用者自己的程式碼只有 4 個。
嘗試 `ruff --fix` 後提交會得到 `DENY: Control Plane 變更不可透過一般 commit`。

請在你的 linter 設定中排除下列路徑：

**ruff**（`pyproject.toml`）

```toml
[tool.ruff]
extend-exclude = ["workflow/", ".claude/", ".githooks/"]
```

**flake8**（`.flake8` 或 `setup.cfg`）

```ini
[flake8]
exclude = workflow,.claude,.githooks
```

**ESLint**（`eslint.config.js`）

```js
export default [
  { ignores: ['workflow/**', '.claude/**', '.githooks/**'] },
];
```

**mypy**（`pyproject.toml`）

```toml
[tool.mypy]
exclude = '^(workflow|\.claude|\.githooks)/'
```

Starter 自身的品質由它自己的 regression suite 負責
（`STARTER_SELF_TESTS=1 bash workflow/bin/verify.sh --full`），不由採用者的 linter 把關。

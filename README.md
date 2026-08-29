# AI Project Starter

> Release candidate: **v1.0.0-rc.5**  
> G3 兩場端對端試跑已完成（見 G3-A / G3-B run report）。
> Final v1.0 仍需完成：G4 文件 cold-start，以及 rc.5 diff 的 scoped reviewer sign-off。

給 Claude Code、Codex 與其他 AI Coding Agent 使用的規格驅動開發 Starter。

**不知道下一步該做什麼？** 先執行 `python3 workflow/bin/workflow_transition.py status`，
再看 `START-HERE.md` 的「每個階段該做什麼」對照表。

```text
Discovery → OpenSpec → Human Spec Review → Test Design
→ Superpowers Engineering → Verification → Archive
```

Web 專案在 Engineering 期間可反覆執行 Browser Verification；最後的 Final Verification 只檢查其 evidence，不重複做同一件事。

## 開始

```bash
bash ./workflow/bin/bootstrap.sh
```

然後：

```bash
python3 workflow/bin/workflow_transition.py doctor
python3 workflow/bin/workflow_transition.py status
```

讓 AI 讀取 `AGENTS.md`、`workflow/STATE.md`、`PROJECT-PROFILE.md`、`CONTEXT.md` 與 active OpenSpec change。

## 核心責任

- `AGENTS.md`：唯一 normative workflow 規範
- `workflow/STATE.md`：Control Plane state
- `workflow/state-log.md`：transition audit log
- `workflow/bin/workflow_transition.py`：唯一合法 state transition 入口
- `workflow/GATES.md`：Gate 判準與信任邊界
- `PROJECT-PROFILE.md`：Project mode/type/critical journeys
- `workflow/evidence/`：verification evidence
- `.claude/hooks/`：Claude 即時回饋層
- pre-commit：Repository enforcement layer

OpenSpec 管「要做什麼」；Superpowers 管「怎麼可靠地做出來」。


相容別名：`bash workflow/bin/check-workflow.sh` 等同 transition CLI 的 `status`。


Starter 維護者自我測試：`STARTER_SELF_TESTS=1 bash workflow/bin/verify.sh --full`。採用者一般 commit 預設不執行 Starter self-tests。


### Brownfield 既有 Control Plane
若專案已追蹤 `.claude/settings.json`、`.claude/hooks/**`、`.githooks/**` 或 `workflow/**`，bootstrap 會在 commit 前停止，不會自動覆蓋。請人工合併、stage 後使用 `python3 workflow/bin/workflow_transition.py adopt-control-plane --dry-run` 檢查，再由人類執行 `adopt-control-plane`。

Brownfield 可先執行 `python3 workflow/bin/workflow_transition.py check-install-conflicts`；它會分開列出既有 Control Plane conflicts 與 tracked Starter-file overwrites。不要在檢查前直接覆蓋既有、未追蹤或被 ignore 的 `.claude/` / `.githooks/` 檔案。

若屬 tracked Starter-file overwrite（例如既有 `README.md` / `.gitignore` / `CLAUDE.md`），每個檔案可選擇採用 Starter 版本、保留原版或手動合併；處理後必須先以一般 commit 保存，例如 `git commit -m "chore: reconcile starter files"`，再重新執行 bootstrap。只 stage 而不 commit 會再次被 preflight 擋下。


## 已知限制
完整信任邊界與限制見 `workflow/GATES.md`。特別注意：Playwright HTML report 是本機 artifact、`.claude/**` 即時 hook 只保證 Claude Code 層、非 Node/Python stack 需自行擴充 `verify.sh` checks。

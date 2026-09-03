# CLAUDE.md

**先確認你在哪裡。** 這個 repo 如果有 `DEVELOPING.md`，你在 **Starter 的原始碼**裡，
不在一個「使用 Starter 的專案」裡 —— 兩者規則不同，而且原始碼是**功能凍結**的
（不得新增 gate 或 enforcement layer）。**先讀 `DEVELOPING.md` 再繼續。**

下游專案不會有那個檔案（它刻意不在 `workflow/SHIPPED-MANIFEST.txt` 裡），
所以看不到就代表這一段不適用你，直接往下。

Claude Code 進入此 Repository 後：
1. 先讀 `AGENTS.md`；它是唯一 normative workflow 規範。
2. 再讀 `workflow/STATE.md`、`PROJECT-PROFILE.md`、`CONTEXT.md` 與 active OpenSpec change。
3. 遵守 `.claude/settings.json` 與 hooks。
4. 可使用 `.claude/skills/` 的 project skills。
5. Session 重啟或 context 壓縮後重新讀 STATE，不假設 Gate 已通過。
6. Hook 拒絕操作時修正 state/操作範圍，不要繞過。
7. 除非使用者指定其他語言，對人類使用繁體中文。

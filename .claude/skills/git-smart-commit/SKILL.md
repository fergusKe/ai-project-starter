---
name: git-smart-commit
description: 當使用者提到「commit」、「提交」、「幫我 commit」、「這些改動要怎麼寫 message」時觸發；檢查 workflow state 與 staged diff 之後產生聚焦的 commit message。commit 是不可逆操作，本 skill 一定先取得確認。
---

# Git Smart Commit

## 前置檢查

依序確認，**任何一項不成立就停下來，照右欄回覆**：

| 前提 | 怎麼確認 | 不成立時說什麼 |
|---|---|---|
| 有東西可提交 | `git status --porcelain` 非空 | 「working tree 乾淨，沒有東西可以提交。」 |
| 變更未混入 Control Plane | staged 檔案是否含 `workflow/STATE.md`、`workflow/state-log.md`、`.githooks/**`、`.claude/settings.json` | 「這批變更含 Control Plane 檔案 `<list>`。Control Plane 必須單獨提交，且走 `control-plane-commit`。我先把它們從這批拆出來。」 |
| transition 後的狀態已單獨提交 | 若 `workflow/STATE.md` 有未提交變更且同時有產品變更 | 「STATE 變更必須先單獨提交，再提交產品變更。」 |
| 適用的檢查已跑過 | 依 `PROJECT-PROFILE.md` 的 `Core verification policy` 判斷 | 「尚未執行 `<check>`。我可以先跑，或你確認要跳過並說明理由。」 |

## 規則

| 規則 | 理由 |
|---|---|
| 一個 commit 只做一件事 | 混合的 commit 無法單獨 revert，也讓 review 失焦 |
| 使用 Conventional Commit（`type(scope): subject`） | 與 branch type、PR 標題同一套詞彙 |
| subject 用祈使句、不加句號、50 字元內 | Git 慣例，`--oneline` 不被截斷 |
| body 說明**為什麼**，不重述 diff 做了什麼 | diff 本身已經說明「做了什麼」；review 時缺的是動機 |
| 引用 active OpenSpec change | 讓 commit 反查得到規格 |
| 語言跟隨 repository 既有 commit 慣例 | 一份歷史裡不要中英混雜 |

## 範例

| 情境 | 建議 message | 判斷依據 |
|---|---|---|
| 新增邀請成員 API endpoint | `feat(invites): add member invitation endpoint` | 新增使用者可見行為 → `feat`；scope 取自模組 |
| 修正重複扣款 | `fix(payment): make charge idempotent by request id`<br><br>`同一個 request id 重試時會建立第二筆扣款。` | 修正既有錯誤行為 → `fix`；body 說明為什麼而非「加了 if」 |
| 只改排版與命名，行為不變 | `refactor(invoice): extract line item builder` | proposal 明說行為不變 → `refactor`，**不可**寫成 `feat` |
| 只動 `workflow/STATE.md` | `chore(workflow): transition to SPEC_REVIEW` | Control Plane 單獨提交；不與產品變更混在一起 |

## 確認關卡

commit 之前，**一律**先輸出下列格式並等待使用者點頭，不要直接執行：

```
即將提交
  分支：<branch>
  檔案：<n> 個
    <path>
    ...
  訊息：
    <subject>

    <body>

確認提交？
```

得到明確同意才執行 `git commit`。使用者只說「幫我看一下」時，輸出提案後停止。

## 邊界情況處理

- **staged 與 unstaged 混雜** → 只描述 **staged** 的內容，並列出未 staged 的檔案提醒使用者，
  **不要**自作主張 `git add -A`。
- **變更跨越多個不相關主題** → 提出拆分建議並列出各自的檔案分組，
  **不要**寫一個「and」串起來的 message 硬湊成一個 commit。
- **偵測到疑似密鑰**（`.env`、`*.pem`、含 `SECRET`／`TOKEN`／`PASSWORD` 的新增行）→ 停止，
  指名檔案與行號，要求先移除；即使使用者說「沒關係」也要再確認一次。
- **使用者要求 `--no-verify`** → 拒絕並說明它會跳過 Control Plane gate；
  只有在使用者明確說明理由且該理由不是「hook 擋住我」時才照辦，並在 body 記錄原因。
- **pre-commit hook 拒絕** → 讀懂拒絕理由並修正操作範圍，**不要**改用 `--no-verify` 繞過，
  也不要修改 hook 本身。
- **產生的 message 需要提到尚未存在的 evidence** → 不要寫「已通過測試」；
  沒有 `workflow/evidence/` 的檔案就不能這樣宣稱。

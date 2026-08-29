---
name: git-branch-name
description: 當使用者提到「開分支」、「建立 branch」、「新 branch」、「這個 change 要叫什麼分支」時觸發；依 active OpenSpec change 產生可追溯的 branch name。本 skill 只建議名稱，不會替你建立或切換分支。
---

# Git Branch Name

## 前置檢查

依序確認，**任何一項不成立就停下來，照右欄回覆，不要猜一個名字**：

| 前提 | 怎麼確認 | 不成立時說什麼 |
|---|---|---|
| 有 active OpenSpec change | `python3 workflow/bin/workflow_transition.py status` 的 `Active OpenSpec change` 不是 `none` | 「目前沒有 active change，branch name 無從追溯。請先 `start-change <change>`。」 |
| Phase 已到 ENGINEERING | 同上的 `Phase` | 「目前在 `<phase>`，尚未進入實作。若只是想先看名字，我可以給建議，但先不要建立分支。」 |
| change 名稱可讀 | 目錄名不是 `tmp`、`test`、`probe` 這類佔位字 | 「change 名稱是 `<name>`，看起來像佔位字。branch name 會進 Git 歷史，建議先正名。」 |

本 skill **不執行任何 git 寫入操作**（不 `checkout`、不 `branch`）。

## 規則

| 規則 | 理由 |
|---|---|
| 格式為 `<type>/<change-slug>` | 兩段式在 `git branch` 列表裡可掃視，type 一眼看出變更性質 |
| `type` 取自 `feat` / `fix` / `refactor` / `chore` / `docs` / `test` | 與 Conventional Commit 對齊，PR 與 commit 用同一套詞彙 |
| slug 盡量沿用 OpenSpec change 名 | 讓 Git 歷史反查得到規格；重新發明名字就斷了追溯 |
| 全小寫 kebab-case，不含底線與中文 | 跨平台與工具相容 |
| 長度控制在 40 字元內 | 過長會在 CI 與 PR 標題被截斷 |

## 範例

| Active change | 建議 branch | 判斷依據 |
|---|---|---|
| `add-team-invites` | `feat/add-team-invites` | change 描述新增使用者可見行為 → `feat`；slug 直接沿用 |
| `fix-payment-idempotency` | `fix/payment-idempotency` | 修正既有行為 → `fix`；slug 已含 `fix-`，去掉避免 `fix/fix-` |
| `rework-invoice-module`（proposal 明說行為不變） | `refactor/invoice-module` | 行為不變只改結構 → `refactor`，不是 `feat` |
| `add-audit-log-docs` | `docs/audit-log` | 產出物只有文件 → `docs`；`-docs` 後綴與 type 重複，去掉 |

## 邊界情況處理

- **change 名稱已含 type 前綴**（`fix-...`、`feat-...`）→ 去掉重複的那一段，不要產生 `fix/fix-payment`。
- **一個 change 要拆成多條 branch** → 用 `<type>/<change-slug>-<part>`（例：`feat/add-team-invites-api`），
  **不要**發明與 change 無關的新名字。並提醒使用者：多條 branch 各自的 PR 都要引用同一個 OpenSpec change。
- **change 同時含修正與新增** → 以 proposal 裡「主要目的」那一句為準；若 proposal 本身沒說清楚，
  停下來問，不要自己選。
- **branch 已存在** → 回報已存在並附上 `git log -1` 的摘要，讓使用者判斷要接續還是換名，
  **不要**自動加 `-v2`、`-new` 這類後綴。
- **使用者只說「幫我開分支」而沒有 active change** → 不要退化成用 commit message 猜名字；
  照前置檢查停下來。

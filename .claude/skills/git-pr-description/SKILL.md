---
name: git-pr-description
description: 當使用者提到「開 PR」、「PR 說明」、「pull request 描述」、「幫我寫 PR」時觸發；依 active OpenSpec change、實際 diff 與 evidence 產生可審查的 PR 說明。本 skill 只產生文字，不建立 PR。
---

# Git PR Description

## 前置檢查

| 前提 | 怎麼確認 | 不成立時說什麼 |
|---|---|---|
| 有 active OpenSpec change | `workflow_transition.py status` | 「沒有 active change，PR 無從引用規格。」 |
| 有實際 diff 可讀 | `git diff <base>...HEAD --stat` | 「與 base 之間沒有差異，先確認 branch 與 base 是否正確。」 |
| evidence 狀態已知 | 檢查 `workflow/evidence/<change>/` 是否存在 | 不存在時**不要**停止，但「測試與驗證」節必須寫「尚未執行」 |

本 skill **不執行 `gh pr create`**，只產生說明文字。

## 流程

1. 讀 `references/pr-template.md`。**它是唯一事實來源**，區塊順序與規則以它為準。
2. 依模板的 HTML 註解逐區填寫。
3. 用不到的區塊整段刪除，不要留空標題。
4. **產出不保留任何註解。**

## 規則

| 規則 | 理由 |
|---|---|
| 禁止 Markdown 連結格式與任何 URI scheme | AI 產 PR 文最常噴出在他人機器上無效的本機路徑 |
| 測試節只引用 `workflow/test-cases/` 與 `workflow/evidence/`，不重寫測試規格 | PR 不是第二份測試文件，重寫必然走鐘 |
| 沒有 evidence 檔案就寫「尚未執行」 | evidence 的擁有權在 `verify.sh`，skill 不得代為宣稱通過 |
| 環境變數只列 key 與範例值位置 | 避免把 secret 寫進 PR |
| 「切換 branch 後需執行的指令」依模板的產生條件判斷 | 有條件才產生，避免每個 PR 都掛一段空區塊 |

## 範例

| 情境 | 該怎麼做 | 判斷依據 |
|---|---|---|
| diff 只改了 `README.md` | 刪除「切換 branch 後需執行的指令」整節 | 沒有命中任何產生條件 |
| diff 含 `pnpm-lock.yaml` 變動 | 產生該節，指令為 `pnpm install`，症狀寫「`Cannot find module 'xxx'`」 | 命中「lockfile 變動」 |
| diff 新增 `workflow/bin/setup-web-verification.sh` | 產生該節，指令含 `bash workflow/bin/setup-web-verification.sh` | 命中 Starter 專屬條件 |
| `workflow/evidence/<change>/` 不存在 | 測試節寫「尚未執行」並列出應執行的指令 | 沒有 evidence 不得宣稱通過 |

## 邊界情況處理

- **base branch 不明確** → 問，不要預設 `main`。搞錯 base 會讓「修改內容」整段失真。
- **diff 過大（超過 50 檔）** → 先回報規模並建議拆 PR；若使用者堅持，依模組分組描述，
  **不要**逐檔列出。
- **diff 含 Control Plane 檔案** → 在「授權與安全影響」明確指出是哪些檔案、
  以及對應的 `control-plane-commit` 紀錄，這是 review 者最需要看到的部分。
- **evidence 存在但顯示失敗** → 如實寫失敗，並在「風險與回滾」說明。
  **不得**只挑通過的部分寫。
- **使用者要求「寫得漂亮一點」** → 可以調整措辭，但不得移除「授權與安全影響」
  或把「尚未執行」改寫成模糊的正面語句。

# Browser Verification

適用條件與 critical journeys 由 `PROJECT-PROFILE.md` 決定。

Playwright 負責可重複的 critical user journeys。新專案統一優先使用 npm script `test:e2e`；既有專案可沿用 `e2e` 或 `playwright`。Web 專案在 full verification 找不到這三種 script 時必須失敗。

Chrome DevTools MCP 負責實際頁面操作與適用的 console、network、DOM/runtime、auth/session/cookie/storage、redirect/CORS、responsive/layout、performance 檢查。

Browser evidence 寫入 `workflow/evidence/<change>/browser.md`，包含 Playwright command/exit code/report path、已驗證 journeys、DevTools 摘要與問題處理結果。


## Evidence ownership

- Browser evidence：`workflow/evidence/<change>/browser.md`。
- Core evidence：`workflow/evidence/<change>/core/<UTC timestamp>.md`，由 machine verification 產生，屬 machine-owned，不應由 AI 手寫。
- `playwright-report/` 是本機 runtime artifact，預設被 `.gitignore` 排除。`browser.md` 只記錄其相對路徑；換機器 clone 後不保證 report 本體存在。


## 工具不可用時的 fallback

Chrome DevTools MCP 在某些環境無法運作（例如 agent 程序取不到 GUI session 時，
headful Chrome 會在啟動後立即被系統中止）。遇到這種情況：

**可以**改用等價的 Chrome DevTools Protocol（CDP）直連，例如以 Playwright 啟動 headless
Chrome 後開啟 `context.newCDPSession()`，啟用 `Runtime` / `Log` / `Network` / `DOMStorage`
等 domain 進行檢查。這與 MCP wrapper 內部使用的是同一組協定與資料來源。

**必須**在 `browser.md` 中明確記載：實際使用的方式、為何未使用 MCP、以及檢查範圍是否有縮減。

**不可以**在未實際檢查的情況下寫下結論。`browser.md` 只驗證格式，不驗證你真的看過 console
與 network —— 這一條靠的是誠實，不是機制。

`doctor` 會在 `Web status: WEB` 時回報 Playwright 與 Chrome DevTools MCP 的可用性；
請在進入 ENGINEERING 之前先確認，不要做到最後一關才發現工具不通。

## 非 Web 專案

`Web verification required: no` 的專案不啟用 Browser Gate，`browser.md` 標記
NOT APPLICABLE。這只表示不需要瀏覽器，**不表示不需要真的把服務跑起來打一次**。

本文件的核心主張（自動測試通過但實際流程失敗，視為未完成）對 API 專案一樣成立，
只是工具不同。端點驗證應涵蓋正確／錯誤／權限三類情境，做法見 `workflow/DEPLOYMENT.md`。

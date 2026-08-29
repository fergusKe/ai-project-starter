# Test Database Safety Template

Use this section in project docs when a database is introduced.

- Development database variable: `<DATABASE_URL or equivalent>`
- Test database variable: `<TEST_DATABASE_URL or equivalent>`
- Test reset command: `<safe command>`
- Safety assertion before reset: `<how the test harness proves it is a test DB>`
- Production protection: `<how prod credentials/data are excluded>`

A destructive reset MUST abort if the target cannot be proven to be test-only.

### 可執行形狀（executable shape）

上面的欄位是宣告。宣告不會保護任何東西，**保護來自一個真的會跑、會失敗的斷言**。

最低要求：

1. 有一個**具名的 guard**（function、script 或 fixture），在任何破壞性操作
   （drop、清空資料表、migrate reset）之前執行。
2. Guard 的判準必須來自**目標本身**，不是來自呼叫端的意圖。可接受的例子：
   - 連線字串的 database 名稱符合約定前綴（如 `test_`）
   - 目標 DB 有一張只在測試環境建立的 marker table
   - 連線字串等於 `TEST_DATABASE_URL` 且該變數與 `DATABASE_URL` 不同值

   不可接受：「因為我們在 CI 裡」、「因為 NODE_ENV=test」—— 這些是呼叫端宣稱，
   呼叫端可以說謊，目標不會。
3. Guard 失敗時**中止並回非零 exit code**，不是印警告後繼續。
4. Guard 本身要有一條測試：餵它一個看起來像 production 的目標，斷言它中止。
   沒有這條測試，guard 隨時可能在重構中被改成永遠通過而沒人發現。

### 為什麼要求第 4 點

這是 Starter 在自己身上學到的：一個防禦層可以在測試全綠的情況下被拿掉，只要
沒有任何測試單獨驗證那一層。Guard 尤其容易 —— 正常路徑永遠不會觸發它，所以
「測試都過」對 guard 完全沒有證據力。

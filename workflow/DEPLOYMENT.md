# 上線與部署

## 先講管轄範圍

**Starter 的 gate 到 ARCHIVE 為止。部署不在 Control Plane 的管轄內。**

這是刻意的：部署平台、環境變數、雲端權限差異太大，Starter 無法對它們做出
可驗證的斷言，強行加一個 gate 只會產生一個假的綠燈。

所以這份文件是**準則層**，不是 gate。**它裡面的「必須」不影響 archive 的完成判定** ——
Starter 不會因為你沒寫 Dockerfile 而擋住任何 transition。

這是刻意的分工，而且判準明確：**normative 的東西必須有機制，沒有機制的就要明說是
建議。** 唯一的例外是 API 端點驗證 —— 那條原本寫在 `AGENTS.md` 是 normative 的，
所以它現在有 gate（見 `workflow/GATES.md`〈API 專案的端點驗證〉），
其餘留在這裡的都是建議。

但 ARCHIVE 不等於上線。下面這些事沒做，「完成」在產品意義上是不完整的 ——
只是那個判斷由人做，不由 Starter 做。

## 能在 localhost 跑，不等於能上線

上雲之前先用 Dockerfile 把打包方式固定下來，理由是可重現：

- **環境一致**：Node 版本、套件、設定寫成明確步驟，避免「在我電腦可以跑」
- **本地與雲端 build 出同一個 image**：出問題時能分辨是程式還是環境
- **每次部署從同一份設計圖建出來**

### 打包的最低要求

**以下只在專案選擇 container deployment 時適用。** 不是所有部署都需要 Dockerfile
（靜態站、函式即服務、平台原生 buildpack 都不需要），也不是所有服務都需要一份
production compose 檔。Starter 不預設你的部署形態。

1. **Multi-stage build**：build 階段裝套件、編譯；最終 image 只保留執行所需檔案。
   最終 image 不含編譯工具 —— 體積更小，攻擊面也更小。

   基底 image 要**釘住不可變的識別**（digest 或至少完整版本 tag）。
   `node:24-alpine` 這種 tag 會隨時間指向不同 image，重現性就沒了。
   另外 Alpine 用 musl，含 native dependency 的專案不一定適用 ——
   選 base image 是專案決策，不是預設值。
2. **`.dockerignore` 必須排除 `node_modules`、`.env*`、`.git`**。
   這是上線前最容易踩的雷：把 `.env` 打包進 image，等於把金鑰發給每一個
   拿得到 image 的人。

   但要清楚它的能力邊界：**排除 `.env` 只是最低限度的靜態檢查，不足以證明
   秘密沒有進到 image。** build args 與 build 期間的環境變數同樣會留在
   image layer 或 build history 裡。需要在 build 期間取用秘密時，
   用 build secret mount，不要用 `ARG` / `ENV` 傳。
3. **production compose 檔**（例如 `docker-compose-prod.yml`）：能完整啟動
   前端 + 後端 + 資料庫，**只有需要對外的服務開 port**。
4. **先在本地 build 並跑起來驗證**。本地起不來，丟到雲端只會更難 debug。

有了 production compose 檔，換哪個平台都好處理 —— 託管平台、AWS、GCP 皆然。

## 部署完成只是下一個開始

上線前在意「功能做不做得出來」，上線後會發現「能跑」只是基礎。
以下三類問題通常不會在第一天發生，但等它發生才開始學就太晚了。

### 有人在暴力嘗試登入

- **暴力破解**：程式一秒試幾百組密碼
- **撞庫（憑證填充）**：拿別的網站外洩的帳密來你家試 ——
  因為多數人到處用同一組密碼
- **對策**：登入失敗數次即鎖定一段時間（rate limiting）、封鎖惡意 IP、
  重要操作加兩步驟驗證

### 使用者變多，服務變慢

- **垂直擴充**：換更大台的機器。最簡單，但有上限
- **水平擴充**：多開幾台分流，搭配 load balancer

### 資料庫越查越慢

資料從一千筆變一百萬筆之後，沒建索引的查詢就像在沒有目錄的字典裡逐頁翻。

- 常查的欄位建立索引
- 讀寫分離分散壓力
- 熱門資料放進 Redis 這類快取

> 這些不必現在就會，但要知道它們存在。遇到時把情境描述給 AI，
> 讓它依你的實際規模給方案 —— 不要一開始就套用大公司的架構。

## API 專案的真實驗證

`PROJECT-PROFILE.md` 填 `Web verification required: no` 的專案（API / CLI /
LIBRARY），Browser Gate 不啟用，`browser.md` 會標記 NOT APPLICABLE。

**這只表示「不需要瀏覽器」，不表示「不需要真的跑一次」。**

`workflow/BROWSER-VERIFICATION.md` 的核心主張是：自動測試通過但實際流程失敗，
視為未完成。這句話對 API 專案一樣成立，只是工具不同 —— 瀏覽器的 F12 只看得到
前端**觸發**的請求，要驗證後端本身，需要一個能主動發出 request、能重複執行、
能切換身份的工具（Postman、Bruno、`curl` 腳本皆可）。

建議在 VERIFICATION 階段對每個對外端點涵蓋三類情境：

| 類別 | 例子 | 期待 |
|---|---|---|
| 正確情境 | 帶合法參數 | `200 / 201` |
| 錯誤情境 | 缺欄位、值不在允許選項內、查無資料 | `400 / 404` |
| 權限情境 | 不帶 token、用低權限 token 打管理端點 | `401 / 403` |

**權限那一列最容易被跳過，也最容易出事。** 前端把選單做成下拉式，不代表後端
擋得住手動送出的非法值；前端把按鈕藏起來，不代表後端擋得住直接打 API。
測試必須從 API 這一層送出前端不會送的東西，確認後端自己會拒絕。

這些 request 存成一組集合之後，它同時也是一份可執行的 API 文件 ——
比寫在 wiki 裡、跟程式漸行漸遠的那種有用得多。

## 相關文件

- `workflow/MERGE-PROTECTION.md`：合併之前的伺服器端執法層
- `workflow/DEV-ENVIRONMENT.md`：多任務並行、pnpm、套件定期升級
- `workflow/CI.md`：CI 的涵蓋範圍與形狀要求

## 已知邊界

- Starter 不驗證部署是否成功、不驗證 image 是否安全、不驗證雲端權限設定。
- 部署後的安全與效能屬於持續維運，不是一次性檢查；本文件只列出該知道它存在的
  項目，不構成完整的上線檢查表。
- 若專案有正式的上線流程（release 分支、變更管理、回滾程序），
  請寫進 `CONTEXT.md`，Starter 不代為決定。

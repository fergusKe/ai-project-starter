# 開發環境

本文件講「怎麼同時處理多件事而不互相干擾」。它是準則層，不是 gate ——
**裡面沒有任何一條會影響 archive 的完成判定**。但選錯做法的代價會在專案變大之後
每天付一次。

唯一有 gate 的是它們的**後果**（見文末）：`Package manager` 是被批准的 profile
欄位、測試必須真的通過、CI 必須是 required check。做法自由，結果要能被檢查。

## Worktree：與其切來切去，不如多開幾個資料夾

一個資料夾只能停在一個分支。所以當你正在寫 `feature/A`，同事要你 review
`feature/B`，QA 又回報 `release/1.0.0` 有 bug，你只能 `git stash` → 切分支 →
處理 → 切回來 → `stash pop`。

**同時處理多個任務時，`git stash` 暫存的東西很容易在切來切去的過程中搞丟。**

`git worktree` 讓同一個 repository 多開幾個資料夾，各自停在一個分支，
共用同一份 Git 紀錄 —— 是輕量的分身，不是把整包再 clone 一次。
寫到一半的東西原封不動留在原資料夾。

```bash
git worktree add ../proj-review feature/B     # 既有分支
git worktree add -b feature/C ../proj-c       # 順便開新分支
git worktree list
git worktree remove ../proj-review            # 用完要移除
```

### 它主要不是為了「平行開發」

AI 執行的效率已經很高，與其平行開發後解衝突，不如把精力放在 review 上。
**worktree 真正的價值是處理不同性質的任務** —— 開發、review、修 bug 三線並行，
互不打斷。

Starter 自己也用它：突變測試在 worktree 裡跑，因為要的是「乾淨且隔離的同一份
程式碼」，而 worktree 給的正是這個，又不用複製整份歷史。

### 用完要移除

worktree 省的是 `.git` 歷史，不是工作檔案。成熟系統光程式檔案就可能上百 MB，
一個人手上又常有數個系統各開幾個 worktree —— 硬碟很快就滿。

## pnpm：讓多個 worktree 不會吃爆硬碟

Node 專案的 `node_modules` 動輒上百 MB。**worktree 有幾個，就有幾份。**

pnpm 把所有套件存在電腦上的一個共用儲存區，各專案的 `node_modules` 用連結
指向同一份。worktree 開幾個都不會等比例增加磁碟用量。

```bash
npm install -g pnpm
pnpm install
```

### 但不要讓兩份 lockfile 並存

導入新工具要以最小影響範圍進行 —— **但「兩份 lockfile 並行」不是最小影響，
是兩個 source of truth。** `package-lock.json` 與 `pnpm-lock.yaml` 可能解析出
不同的相依圖，於是「在我機器上可以跑」換了個形式回來，而且更難查。

遷移期要明確選定**唯一**權威的 package manager，只提交它的 lockfile，
CI 用 frozen / immutable install（安裝失敗好過安靜地裝成另一套）。

版本本身也要釘住。`npm install -g pnpm` 沒有指定版本，跟可重現性的目標相反 ——
用 `package.json` 的 `packageManager` 欄位宣告版本，讓每個人與 CI 拿到同一個。

`PROJECT-PROFILE.md` 的 `Package manager` 欄位記錄專案採用哪一個。
它是被批准的 profile 的一部分，改它要走 SPECIFICATION。

## 同一條原則：沒有依賴關係的事就同時做

`workflow/CI.md` 對 CI 的要求是分層 + 平行。那條原則不只適用於 CI：

| 場景 | 序列的代價 | 做法 |
|---|---|---|
| 多個任務 | stash 來回、東西搞丟 | worktree |
| 多個 worktree 的套件 | 磁碟等比例膨脹 | pnpm 共用儲存區 |
| 互相獨立的測試 | 子行程排隊 | 平行執行 |

Starter 自己的測試是第三種：29 個測試類別彼此完全獨立，序列跑 640 秒、
平行跑 78 秒。

```bash
python3 workflow/bin/run-tests.py          # 平行，並回報最慢的類別
python3 workflow/bin/run-tests.py -j 4
python3 workflow/bin/run-tests.py -k Round16
```

**一條要等十分鐘的測試套件，開發者會想辦法不跑它。** 這跟 CI.md 說「一條要等
30 分鐘的 CI，工程師會想盡辦法繞過它」是同一件事 —— 速度不是舒適度問題，
是「這道防線會不會被實際使用」的問題。

## 套件升級：從「不划算」變成例行維護

過去大家能拖就拖，因為相依性地獄、breaking changes、要啃 changelog，
而且升完「畫面長一樣」看不到商業價值 —— 更關鍵的是**沒有測試就是賭博**，
升級後不知道壞了什麼。

但拖越久越貴：小版本一路跟只需每次改一點；拖到被迫一次跳好幾個大版本，
就是把小手術拖成大刀。而舊版套件的漏洞是公開資訊。

有了自動化測試與 CI 之後，這個算式變了：壞了什麼馬上看得到，而啃 changelog、
改 breaking changes 正好是 AI 最擅長的苦工。**升級因此應該排成定期維護，
不是等到不得已才做。**

實務上：

- 用 Context7 之類的工具取得套件的**最新**文件，不要依賴模型的訓練資料
- **依影響決定流程，不要一律走完整 OpenSpec。** 會改變可觀察行為、安全契約或
  被批准範圍的升級（大版本、行為有 breaking change、換掉驗證相關的相依）
  要回 OpenSpec 重新 review；純維護性升級（patch、安全修補、無行為變更）
  走工程 maintenance change 即可。一律要求完整流程只會讓人不做升級。
- 升完不要只看測試綠燈，**親手跑一次**啟動與主要流程

## 為什麼這些不是 gate

Starter 無法驗證你有沒有用 worktree，也不該管你用 npm 還是 pnpm ——
那些是團隊偏好，強制它們只會製造繞過。

有 gate 的是它們的**後果**：`Package manager` 是被批准的 profile 欄位、
測試必須真的通過、CI 必須是 required check。做法自由，結果要能被檢查。

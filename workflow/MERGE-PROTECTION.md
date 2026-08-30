# Merge Protection —— 伺服器端執法層

本機 gate 不是終點，是**快速回饋**。真正的閘門在伺服器端。

## 為什麼需要這一層

Starter 的所有本機防線 —— `check-implementation-gate.py`、`verify.sh`、
PreToolUse hook —— 都掛在 `.githooks/pre-commit` 上。而 pre-commit 有一個
一行就能關掉的開關：

```bash
git commit --no-verify -m "whatever"
```

`workflow/GATES.md` 對此的規定是「Agent / 人類 / 一般 script **不得**直接使用」。

**那是一條規範，不是一個機制。** 而這整套架構存在的理由，就是「規範對一個有
shell 權限的 AI 不構成約束」。我們對自己的最後一道防線用了架構本身否定的東西。

這份文件負責把它變成機制。

## 三層執法點，各司其職

| 層 | 位置 | 擋得住什麼 | 擋不住什麼 |
|---|---|---|---|
| PreToolUse hook | `.claude/hooks/` | Claude Code 的即時誤動作 | Bash 直接繞過；其他 agent harness 不執行 |
| pre-commit | 本機 `.githooks/` | 絕大多數日常錯誤，回饋最快 | `--no-verify`、`push` 到別的地方 |
| **CI required check** | **GitHub runner** | 它**實際檢查到**的 repository mutation | 已經發生的本機副作用；有 admin 權限的人手動 override |
| CODEOWNERS + review | GitHub | 「機器覺得沒問題但人覺得有問題」 | 人類蓋章不看 |

**注意第三層的位置。** CI runner 的 checkout 起始於受測 commit 的**乾淨
materialization** —— worktree 與 index 都存在（`actions/checkout` 會建立），
但它們一開始就與該 commit 一致，不存在開發機上那種「worktree 是 A、index 是 B」
的三態分裂。

**但要說清楚 required check 做得到什麼、做不到什麼：**

- 它能拒絕**它實際檢查到**的 repository mutation。GitHub ruleset 只保證指定的
  check 必須成功；check 裡面檢查什麼，仍然完全由 workflow 決定。
  一個什麼都不查的 required check，是一個比較慢的 lint。
- 它**不能撤銷本機已經發生的副作用**。PreToolUse 要防的是「AI 在你的磁碟上做了
  不該做的事」，那件事一旦發生，CI 只能拒絕它進入受保護分支。
- 它**不是身份認證**。它證明的是內容與歷史的性質，不是誰做的。

## 設定步驟

### 前置：把 audit workflow 放進去

```bash
mkdir -p .github/workflows
cp templates/github-workflow-control-plane-audit.yml \
   .github/workflows/control-plane-audit.yml
```

依 `workflow/CI.md` 另外建立專案自己的測試 workflow（Starter 不 ship 固定 YAML，
理由見該文件）。

推一次，到 GitHub 的 **Actions** 分頁確認有觸發、且 job 名稱記下來 ——
下一步要用名稱來指定 required check。

### 建立 Branch Ruleset

GitHub → **Settings** → **Rules** → **Rulesets** → **New branch ruleset**

> 免費方案需要 **Public** repository 才能設定 ruleset。Private repo 需付費方案。

| 欄位 | 值 |
|---|---|
| Ruleset Name | `Protect main/develop` |
| Enforcement status | **Active**（留在 Disabled 等於沒設） |
| Target branches | Add target → Include by pattern → `main`，再加一次 → `develop` |

Branch rules 勾選：

- **Require a pull request before merging** —— 不能直接 push 進受保護分支
- **Require status checks to pass**
  - **Require branches to be up to date before merging**
  - Add checks → 加入 `control-plane-audit`
  - Add checks → 加入專案自己的測試 job
- **Require review from Code Owners**（團隊專案；搭配下面的 CODEOWNERS）

> 加 check 時如果搜尋結果出現同名的多筆，選**最近一次 Actions 實際使用的那個**。
> 選錯會設定出一個永遠不會回報的 check，PR 會卡住或形同虛設。

### CODEOWNERS

```bash
cp templates/CODEOWNERS.example .github/CODEOWNERS
```

**把 `@YOUR_TEAM` 換成真的 GitHub user 或 team**，留著範例值等於沒設。

## 驗證：沒實測過的防線不算防線

設定完**必須實際跑一次失敗情境**。這是 Starter 一貫的判準 —— receipt 要綁 probe、
gate 要被突變測試打過 —— branch protection 沒有理由例外。

```bash
git checkout -b test/merge-protection-check

# 故意讓一個測試失敗（改一個斷言的期望值即可）
# 然後刻意繞過本機 gate，模擬「AI 用 --no-verify 硬推」
git commit --no-verify -am "deliberately failing test"
git push --set-upstream origin test/merge-protection-check
```

到 GitHub 開一個 PR 回 `develop`，確認：

1. CI 跑起來並且**紅燈**
2. **Merge pull request 按鈕是灰的、點不下去**

看到灰色按鈕才算設定成功。確認完把分支刪掉。

> 這個動作正是在驗證「`--no-verify` 繞得過本機、繞不過伺服器」。
> 如果按鈕還是綠的，代表 ruleset 沒 Active、target 沒涵蓋這個分支、
> 或 required check 名稱選錯 —— 三個都要回頭查。

## 已知邊界

- **Starter 查不到這一層的狀態。** ruleset 存在 GitHub 上，`doctor` 只能檢查本機。
  設定完請自行記錄在 `CONTEXT.md`，並在 PR review 時人工確認。
- **Repository admin 可以 override。** required check 紅燈時，admin 仍可強制合併
  （視 ruleset 的 bypass list 設定）。要收緊就把 bypass list 清空 ——
  包含把自己排除在外。
- **只保護被列入 target 的分支。** `main`、`develop` 之外的分支不受保護，
  這是刻意的：feature 分支本來就該能自由推送。
- **CI 通過不等於需求完成。** 這一層證明的是「合得起來、測試會過」，
  不證明「做的是被批准的那件事」—— 那是 `control-plane-audit` 與 OpenSpec
  compliance verification 的職責。

## 與 Control Plane 的關係

`control-plane-audit` 驗證的是 **PR 裡的 Control Plane mutation 與 audit record
是否一致**，它不證明 audit record 一定由人類產生（見 `workflow/GATES.md`
〈Control Plane audit 能力邊界〉）。

所以真正的人類授權是三件事疊起來的：

1. `approve-spec` / `approve-tests` 的 **TTY 要求** —— 這是一道**已驗證的
   非互動邊界**（`subprocess.run` 拿不到 controlling terminal），
   不是不可偽造的人類身份認證
2. **CODEOWNERS + required review** —— Control Plane 檔案的變更要人看過
3. **required status check** —— 上面兩件事的紀錄要能被機器複驗

少任何一件，剩下兩件都會被繞過。

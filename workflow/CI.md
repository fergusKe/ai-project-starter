# CI 規範

CI 是 Verification / Merge Gate 的一部分，但 Starter 不預先綁死某一份 GitHub Actions YAML。

## AI 應如何處理

當 Repository 使用 GitHub 且專案準備進入穩定開發時：

1. 偵測實際技術 Stack、package manager、monorepo 結構與既有 scripts。
2. 先讀取現有 `.github/workflows/`，不要重複建立衝突的 workflow。
3. 根據專案實際命令建立或更新 GitHub Actions。
4. CI 至少涵蓋適用的：
   - lint
   - typecheck
   - unit tests
   - integration tests
   - build
   - Web 專案的 Playwright critical E2E
5. Integration/E2E 需要 DB 時，必須使用隔離的測試資料庫。
6. PR 合併前 required checks 必須通過。

## CI 的形狀要求

上面列的是**涵蓋範圍**，這裡是**形狀**。兩者都要滿足；一個把所有檢查塞進單一
job 的 workflow 即使涵蓋範圍完整，仍然不合格。

1. **分層（staged）**：便宜且高頻失敗的檢查排在前面（lint、typecheck），昂貴的排
   後面（integration、E2E、build）。前層失敗時後層不應該還在燒 runner 時間。
2. **平行（parallel）**：彼此沒有依賴的 job 必須平行跑。「lint 等 typecheck 等
   unit test」這種串接是浪費，不是分層。
3. **時間預算**：PR 的 required checks 目標在 **5–10 分鐘**內回覆。超過就要處理
   （切分、快取、縮小 matrix），而不是接受。這是**目標不是 gate** —— Starter 不
   會因為 CI 慢而擋 merge，但 AI 建立或修改 CI 時必須報告實測時間。
4. **Coverage 是 artifact**：coverage 產出必須是可下載的 artifact 或 job summary，
   不能只存在於 log 裡。**不要**把 coverage 門檻設成 required check，除非人類明確
   要求 —— 覆蓋率門檻會誘導為了數字而寫的測試。

### 為什麼寫成準則而不是 YAML

Starter 不知道採用者的 stack、runner 數量或既有 workflow。給一份固定 YAML 只會
被複製後改壞。準則可以被檢查（AI 報告實測時間與 job 圖），YAML 不行。

## 原則

- 不要從 Starter 複製一份與 Stack 無關的通用 CI。
- CI 應由 AI 根據 Repository 真實狀態產生。
- CI 通過仍不等於需求完成；最後仍須做 OpenSpec compliance verification。


## Control Plane Audit
Audit 驗證 PR 中的 Control Plane mutation 與 audit record 是否一致；它不證明 record 一定由人類產生。真正的人類授權請使用 CODEOWNERS + branch protection + required review。

### Audit range
一般 PR 建議先取得 merge-base，再審查該範圍：

```bash
BASE=$(git merge-base origin/main HEAD)
python3 workflow/bin/audit-control-plane.py "$BASE" HEAD
```

首次 Greenfield root commit 可使用 Git empty-tree hash 作 base；Brownfield 一般使用 `git merge-base origin/main HEAD` 作 base；audit 會自行辨識 sanctioned installation baseline。Sanctioned Starter installation baseline 會由 audit 共用 policy 自動辨識並放行。


## GitHub Actions 範本

Starter 不直接 ship `.github/workflows/`，因為 Brownfield 專案可能已有自己的 CI；請將 `templates/github-workflow-control-plane-audit.yml` 複製到採用者 repo 的 `.github/workflows/control-plane-audit.yml`。

範本使用版本化的 `actions/checkout@vN` 並設定 `fetch-depth: 0`，因為 `audit-control-plane.py` 需要完整 Git 歷史。範本中的 checkout major version 最後人工核對日期為 2026-08-29；外部 Action 版本需在重大 Starter 釋出前重新確認。PR 中以 `git merge-base origin/$GITHUB_BASE_REF HEAD` 作 base。

建議把 `control-plane-audit` 設成 branch protection 的 required check。首次 Greenfield root commit 若沒有 parent，手動驗證時可用 Git empty-tree hash 作 base。Brownfield 不需要特別找安裝 commit 的前一筆；audit 會辨識 sanctioned installation baseline。

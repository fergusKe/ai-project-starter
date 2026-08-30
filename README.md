# AI Project Starter

> **v1.0** — 經 20 輪對抗審查（12 次拒簽）後由審查者正式 sign-off。
> 功能凍結：只收 release blocker 修正、回歸測試與文件一致性修正。

給 Claude Code、Codex 與其他 AI Coding Agent 使用的**規格驅動開發 Starter**。

它解決的問題很具體：AI 寫程式會**做了你沒要求的事**，也會**沒做完就說做完了**，
而你不可能盯著每一個動作。一般做法是在 CLAUDE.md 寫「請先取得批准再實作」——
但那是一句話，AI 讀得到，也可以說服自己這次情況特殊。**規勸不是機制。**

這個 Starter 把規勸換成閘門：**沒有人類批准，產品程式碼 commit 不進去。**

## 假想敵是誰

**是那個有 shell 權限的 AI 助理本身**，不是外部駭客。這決定了整個設計 ——
每一層都假設「被守的東西碰得到守衛」：

- 批准要**在真實終端機**輸入 —— 擋掉一般非互動的 agent / CI / 腳本呼叫
  （這是**已驗證的非互動邊界**，不是人類身分認證，見 `SETUP.md`）
- 批准綁的是**內容的指紋**，不是 yes/no 旗標 —— 不能先批一份小規格再換掉檔案
- 閘門從 **HEAD** 重新驗，不看工作目錄 —— 本機改檔案騙不到它
- 狀態檔用雜湊串成 append-only 日誌，改了會對不上

它做不到的事同樣要講清楚：**擋不死有完整 shell 權限的東西。**
它做到的是**讓繞過必須是一個刻意的、留下痕跡的動作**，而不是不小心或自我說服就發生。

## 流程

```text
DISCOVERY → SPECIFICATION → SPEC_REVIEW → TEST_DESIGN
→ ENGINEERING → VERIFICATION → ARCHIVE →（下一輪 change）
```

`SPEC_REVIEW` 與 `TEST_DESIGN` 各有一道**人類批准**；其餘由 CLI 自行驗證 artifact，
不接受 AI 的「已經完成」宣稱。

## 三層執法點

| 層 | 擋得住 | 擋不住 |
|---|---|---|
| PreToolUse hook（`.claude/hooks/`） | Claude Code 的即時誤動作 | Bash 直接繞過；其他 agent 不執行它 |
| pre-commit（`.githooks/`） | 絕大多數日常錯誤，回饋最快 | `git commit --no-verify` |
| **CI required check** | 它**實際檢查到**的 repository mutation | 已發生的本機副作用；admin override |

**第三層不是選配。** 本機所有防線都掛在 pre-commit 上，而 `--no-verify` 一行就能關掉它。
設定步驟與**必做的失敗實測**見 `workflow/MERGE-PROTECTION.md`。

## 快速開始

### 1. 取得出貨檔案

**從 `v1.0` tag 取，不要複製工作目錄。** 直接 `cp -R` 整個目錄會帶走 `.git`、
`__pycache__` 與開發用的 review 文件 —— 那些不是出貨內容，而且會讓新專案的
第一個 commit 就髒掉。`workflow/SHIPPED-MANIFEST.txt` 是唯一的出貨清單。

```bash
# 取一份 v1.0 的乾淨副本（放哪裡都行，用完可刪）
git clone --depth 1 --branch v1.0 \
  https://github.com/fergusKe/ai-project-starter.git /tmp/starter-v1.0

# 依出貨清單複製進你的專案（清單裡都是 repo 根層的路徑）
cd /path/to/your-project
while IFS= read -r p; do
  p="${p%$'\r'}"; [ -z "$p" ] && continue; case "$p" in "#"*) continue;; esac
  cp -R "/tmp/starter-v1.0/${p%/}" ./
done < /tmp/starter-v1.0/workflow/SHIPPED-MANIFEST.txt
```

### 2. 安裝與確認

```bash
bash ./workflow/bin/bootstrap.sh

# 確認 gate 真的生效
python3 workflow/bin/workflow_transition.py doctor    # 要看到 Repository enforcement: ACTIVE
python3 workflow/bin/workflow_transition.py status    # 目前在哪個階段
```

**既有專案（Brownfield）先跑這個**，不要直接 bootstrap：

```bash
python3 workflow/bin/workflow_transition.py check-install-conflicts
```

然後讓 AI 讀 `AGENTS.md` → `workflow/STATE.md` → `PROJECT-PROFILE.md` → `CONTEXT.md`
→ active OpenSpec change。

## 兩個一定會踩到的地方

**批准必須在真正的終端機執行。**

```bash
python3 workflow/bin/workflow_transition.py approve-spec <change>
```

在 Claude Code 對話框裡用 `!` 前綴執行**不會成功** —— 那裡的 stdin 不是 TTY。
請開 Terminal / iTerm / VS Code 終端機。

這道邊界擋的是**一般非互動執行環境**，不是「程式絕對拿不到 TTY」——
能力邊界寫在 `SETUP.md`，請不要把它當成人類身分認證。

**送審之前就要 commit，不是批准之前。**

`PROJECT-PROFILE.md` 一進 `SPEC_REVIEW` 就變成唯讀的 Control Plane。沒有在
`submit-for-review` 之前提交的人會卡住 —— 只能 `revert-to-spec` 退回去改。
CLI 會在送審時先擋下並給你指令（exit 37）。

```bash
git add PROJECT-PROFILE.md openspec/changes/<change>
git commit -m "spec: <change> 送審版本"
python3 workflow/bin/workflow_transition.py submit-for-review <change>
```

## 文件地圖

| 你想知道 | 看 |
|---|---|
| 每個階段該做什麼 | `START-HERE.md` |
| 給 AI 的 normative 規範 | `AGENTS.md`（本 repo 內唯一 normative workflow 權威） |
| Gate 判準、信任邊界、**所有已知限制** | `workflow/GATES.md` |
| 伺服器端執法怎麼設、怎麼實測 | `workflow/MERGE-PROTECTION.md` |
| CI 的涵蓋範圍與形狀要求 | `workflow/CI.md` |
| Web / API 專案的真實驗證 | `workflow/BROWSER-VERIFICATION.md`、`workflow/DEPLOYMENT.md` |
| 多任務並行、pnpm、套件升級 | `workflow/DEV-ENVIRONMENT.md` |
| 打包與上線 | `workflow/DEPLOYMENT.md` |

## 核心檔案

- `workflow/bin/workflow_transition.py` — **唯一**合法的 state transition 入口
- `workflow/STATE.md` / `workflow/state-log.md` — Control Plane 狀態與 append-only 稽核
- `workflow/bin/audit-control-plane.py` — 伺服器端逐 commit 授權稽核（CI required check）
- `workflow/evidence/` — 驗證證據；ARCHIVE 後凍結
- `PROJECT-PROFILE.md` — 專案型別、驗證政策、critical journeys

OpenSpec 管「要做什麼」；Superpowers 管「怎麼可靠地做出來」。

## 給 Starter 維護者

```bash
python3 workflow/bin/run-tests.py     # 平行跑自我測試（~40 秒；序列要 ~250 秒）
python3 workflow/bin/acceptance.py    # 在拋棄式採用者 repo 上跑完整生命週期
```

`acceptance.py` 是 release 前的必要步驟：它做安裝 → TTY 批准 → 產品 commit →
驗證 → 封存 → 第二輪 → 伺服器稽核，**並且正反兩向**（合法歷史要過，
`--no-verify` 的未授權 commit 要被擋）。只有正向的話，那個綠燈證明不了任何事。

> 本 repo 是 Starter **原始碼**，不是採用 Starter 的專案（見 `DEVELOPING.md`）。
> 它刻意不設 `core.hooksPath`，對它自己的歷史跑 runtime audit **預期會失敗**。

## 已知限制

完整清單見 `workflow/GATES.md`。最需要先知道的幾條：

- **`--no-verify` 繞得過本機**。沒有 remote 的單機專案沒有第二道，這是無法消除的邊界。
- **Browser / API evidence 驗證的是「宣稱涵蓋範圍」**，不是那些流程真的被執行過。
- **`Core verification policy: custom`** 的指令從你寫進 profile 那一刻起每個 commit 都會跑，
  而驗證腳本本身是產品程式碼、ENGINEERING 前不能 commit。
  指令要寫成「專案完成時有意義、專案還空著時不擋路」。
- `.claude/**` 的即時 hook 只保證 Claude Code；其他 agent harness 不一定執行它。
- 非 Node/Python stack 需自行擴充 `verify.sh` 的 checks。

# 開發本 Starter

**這個 repo 是 Starter 的原始碼，不是一個「使用 Starter 的專案」。** 兩者的規則不同。

**本檔不隨 Starter 出貨**（`workflow/SHIPPED-MANIFEST.txt` 刻意排除它）。
所以它的存在本身就是判別訊號：**看得到這個檔案，代表你在 Starter 原始碼裡，
不在下游專案裡。**

## 現在的狀態：v1.0，功能凍結

2026-08-30 經 20 輪對抗審查（12 次拒簽）取得 sign-off，tag `v1.0`。

| 接受 | 不接受 |
|---|---|
| release blocker 修正 | 新增 evidence 類型 |
| 回歸測試 | 新增 state transition |
| 診斷訊息與文件一致性修正 | 新增 policy vocabulary |
| | **新增任何 enforcement layer 或 gate** |

### 為什麼特別禁止「再加一個 gate」

**最後三個 blocker 全部來自新增的 API gate，不是舊缺陷。**

在這套架構裡加一種新的 evidence，要同時接進**十一個地方**：schema、
applicability、ownership、AI write policy、local gate、server audit、
verification provenance、archive replay、revert staleness、guard feedback、
acceptance path。第一次實作漏了三個，而**局部測試全綠**。

> **gate 是跨生命週期功能，不是單一 validator。**

使用者若要求新增 gate：先說明凍結狀態、列出上面那十一個 consumer 讓他決定。
真的要做就逐層實作 + 逐層突變測試（見〈修改之後要做什麼〉第 2 點）。

## 有一個姊妹模板，不要把東西搬錯邊

同一個作者維護兩個模板，解決的問題不同：

| | 這個（`ai-project-starter`） | `ai-team-starter` |
|---|---|---|
| 信任錨 | **本機 hook + state machine**：沒有人類批准，產品程式碼 commit 不進去 | **GitHub required check + code owner review**：本機完全不擋，只有雲端擋 |
| 適合 | 一個人 + agent，要在 commit 之前就擋住 | 多人協作，接受「違反會在 PR 上被看到」 |
| 重量 | `workflow/` 一整套 state machine、evidence、archive replay | 一支 bash 閘門腳本 + 一份 ruleset 快照 |
| 狀態 | **v1.0 凍結** | 持續演進 |

**2026-09-04 起，分支類別閘門、ruleset 快照、lockfile 來源檢查這些新東西
都在 `ai-team-starter` 那邊發展。** 它們是「規範不是機制」的同一個命題在
GitHub 那一層的解法，跟本 repo 的本機 hook 那一層是兩套獨立的答案 ——
**不要把那邊的東西搬進來**。搬進來就是新增 enforcement layer，直接違反凍結，
而且會踩到上面那十一個 consumer。

## 不要在這個 repo 執行 bootstrap

`bash workflow/bin/bootstrap.sh` 會設定 `core.hooksPath=.githooks`，把 Starter 的
runtime gate 套用到**它自己的模板檔案**上。後果是 `workflow/STATE.md`、`.githooks/**`、
`.claude/settings.json` 全部變成受保護的 Control Plane —— 而編輯這些檔案**正是**
開發 Starter 的工作內容，於是你會被自己的 gate 擋住。

這個 repo 刻意**不設** `core.hooksPath`。`git config --get core.hooksPath` 應該是空的。

本 repo 裡的 `workflow/STATE.md` 是**出貨模板**（`Phase: DISCOVERY`），
不是本專案的實際工作狀態。不要用 `workflow_transition.py` 去推進它。

## 要測 Starter 的行為，複製到別處測

```bash
W=$(mktemp -d)
tar cf - $(find . -type f -not -path './.git/*' -not -name '*.pyc' -not -path '*__pycache__*') | (cd "$W" && tar xf -)
cd "$W" && git init -q -b main && bash workflow/bin/bootstrap.sh
```

回歸測試已經是這個形狀（每條測試各自建立臨時 repo），所以正常情況下直接跑測試即可。

## 測試

```bash
python3 -m unittest discover -s workflow/tests -t .
```

沒有 TTY 的環境（CI、sandbox、agent harness）會有兩條必然失敗，那是設計值：

- `test_actor_prompt_is_distinguishable_from_change_prompt`
- `test_wrong_input_names_both_values_in_error`

兩條都以真實 pty 驗證 Human Approval 的提示，需要 controlling terminal。

## 修改之後要做什麼

1. **每個修正都要有回歸測試，而且要證明它會紅。** 還原修正 → 測試變紅 → 復原修正 → 變綠。
   沒紅過的測試不能證明它守住了什麼。
2. **突變測試要跑完整套件**，不要只跑相關的那幾條。深度防禦會讓各層互相遮蔽 ——
   只看最終結果的斷言，可能在某一層被移除時仍然全綠。每一層都需要一條「只有該層適用」
   的隔離測試。
3. 新增 skill 時遵守 `docs/skill-authoring.md`。
4. 新增檔案若要隨 Starter 出貨，必須在 `workflow/SHIPPED-MANIFEST.txt` 的根目錄涵蓋範圍內。
   本檔（`DEVELOPING.md`）刻意不在其中。

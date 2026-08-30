# 取得與安裝模板

這個 Starter 是散發用模板，不假設模板目錄本身就是 Git repo。

**出貨檔案要從 `v1.0` tag 取，依 `workflow/SHIPPED-MANIFEST.txt` 複製** ——
可直接執行的指令在 `README.md` 的〈快速開始〉。不要 `cp -R` 整個工作目錄：
那會帶走 `.git` 與開發產物，讓新專案的第一個 commit 就髒掉。

- **Greenfield**：把 Starter shipped files 複製到空專案目錄後，執行 `bash workflow/bin/bootstrap.sh`。
- **Brownfield**：把 Starter files 放入既有 repo 後，**先**執行 `python3 workflow/bin/workflow_transition.py check-install-conflicts`。若列出 tracked overwrite / Control Plane conflict，依輸出先 merge / adopt，不要直接重跑 bootstrap。
- 不要在未檢查前用覆蓋式複製破壞既有 `.claude/`、`.githooks/`、`CLAUDE.md` 等檔案；Git 只能還原已追蹤內容。

詳細外部工具安裝見 `SETUP.md`。

# START HERE

```bash
bash ./workflow/bin/bootstrap.sh
python3 workflow/bin/workflow_transition.py doctor
python3 workflow/bin/workflow_transition.py status
```

## 每個階段該做什麼

先執行 `python3 workflow/bin/workflow_transition.py status` 看目前 Phase，
再對照下表。**Human Approval 欄標 ✋ 的兩步必須由真人在互動終端機執行。**

| Phase | 讀這份 prompt | 完成後執行 |
|---|---|---|
| `DISCOVERY` | `prompts/01-discovery.md` | `set-mode GREENFIELD` 或 `set-mode BROWNFIELD` |
| `DISCOVERY`（模式已設定） | `prompts/02-to-openspec.md` | 建立 `openspec/changes/<change>/` 並寫入內容後 `start-change <change>` |
| `SPECIFICATION` | `prompts/03-spec-review.md` | `submit-for-review <change>` |
| `SPEC_REVIEW` | 人類審閱 `openspec/changes/<change>/` | ✋ `approve-spec <change>` |
| `TEST_DESIGN` | `prompts/04-test-design.md` | ✋ `approve-tests <change>`，再 `start-engineering <change>` |
| `ENGINEERING` | `prompts/05-implement.md` | 實作完成後 `bash workflow/bin/verify.sh --full` |
| `ENGINEERING`（Web 專案） | `prompts/06-browser-verify.md` | 寫 `workflow/evidence/<change>/browser.md` |
| `ENGINEERING`（驗證齊備） | `prompts/07-verify-and-archive.md` | `verification-pass <change>` |
| `VERIFICATION` | 同上 | `archive <change>` |

`openspec/changes/<change>/` 至少要有這三樣，`submit-for-review` 才會通過：

| 需要 | 認定方式 |
|---|---|
| proposal | 檔名含 `proposal` |
| specs | 有 `specs/` 目錄，或檔名含 `spec` |
| tasks | 檔名含 `task` |

`design` 是選用的（`prompts/02` 建議寫，但不是 gate 的必要條件）。
`start-change` 只要求目錄非空 —— 完整清單是在 `submit-for-review` 檢查。

指令一律加前綴 `python3 workflow/bin/workflow_transition.py`。
每次 transition 之後，**先單獨提交 `workflow/STATE.md` 與 `workflow/state-log.md`**，再繼續下一階段的工作。

**送審之前，被批准的內容必須先 commit** —— 注意是 `submit-for-review` **之前**，
不是 `approve-spec` 之前。`PROJECT-PROFILE.md` 一進 SPEC_REVIEW 就變成唯讀的
Control Plane，那時再想用一般 commit 修它就來不及了。`submit-for-review` 會替你
檢查這件事（exit 37）。

**批准之前，被批准的內容必須先 commit。** `approve-spec` 會檢查
`PROJECT-PROFILE.md` 與 `openspec/changes/<change>/**`、`approve-tests` 會檢查
`workflow/test-cases/<change>.md` —— 三者都必須存在於 HEAD，且 worktree / index /
HEAD 是同一份。理由：批准綁定的是**會被 commit 出去的那一份**，不是本機當下看到的
那一份。少了這條，STATE 可以宣稱「已批准」而 fresh clone 拿不到任何被批准的東西。

```bash
git add PROJECT-PROFILE.md openspec/changes/<change>
git commit -m "spec: <change> 送審版本"
python3 workflow/bin/workflow_transition.py approve-spec <change>
```

進入 ENGINEERING 之後打勾（`- [ ]` → `- [x]`）不會使批准失效，改動任務或規格**文字**會。

第一次導入：
- `GREENFIELD`：新專案，從需求探索開始。
- `BROWNFIELD`：既有專案，先掃描 Repository、補 Context/Profile，再只對新 change 建 OpenSpec。

Human Approval 只存在於：
- `approve-spec`
- `approve-tests`

這兩個 transition 需要人類在互動終端機確認 change 名稱。

其餘 transition 由 CLI 自己驗證 artifact，不接受 AI 的「已經完成」宣稱。

# Workflow Gates

`AGENTS.md` 是唯一 normative 規範；本檔集中操作判準。

## Control Plane
單一政策來源：`workflow/bin/workflow_state.py`。Starter 執行檔位於 `workflow/bin/**`，Starter regression 位於 `workflow/tests/**`；兩者皆屬 Control Plane，不佔用真實專案的 `scripts/**`。PROJECT-PROFILE 僅在 DISCOVERY/SPECIFICATION 可寫。

## Evidence Ownership
- `workflow/evidence/<change>/core/<timestamp>.md`：machine-owned；AI Write/Edit deny。
- `workflow/evidence/<change>/browser.md`：Browser Verification writer。
- core 檔名只接受 `YYYYMMDDTHHMMSS[ffffff]Z.md`。
- Web browser.md 必須引用一份存在且成功的 core evidence、一個實際存在的 Playwright report artifact，並包含 Chrome DevTools MCP 結論。

## State Audit
每次 transition append state-log + STATE SHA256；pre-commit 驗證 hash 且 log append-only。

## Brownfield Installation
Gate 必須在 Starter Control Plane 進入 Git history 後才啟動。bootstrap 在既有 repo 首次安裝時，只 staging Starter-owned paths 並建立 `chore: install AI project starter control plane` baseline，不應攜帶既有產品變更。

## Control Plane Maintenance
一般 commit 一律拒絕 Control Plane 修改。人類需先 stage 純 Control Plane 變更，再在互動終端機執行：
`python3 workflow/bin/workflow_transition.py control-plane-commit`。
此命令以 TTY 授權、檢查 staged files 全為 Control Plane，再建立單獨 commit。團隊環境仍應優先 PR+CODEOWNERS。

## Data Safety
資料庫專案依 `templates/test-db-safety.md` 建立 test-only destructive-operation 規則。

## Starter Self Tests
Starter 自我測試只驗證 Starter 自身，不屬於採用者產品的 pre-commit gate。
預設不執行；僅在維護 Starter 或 CI 時使用：

```bash
STARTER_SELF_TESTS=1 bash workflow/bin/verify.sh --full
```

Self tests 使用 isolated pristine fixture，不依賴宿主專案目前的 STATE。

## `--no-verify` 邊界
Agent / 人類 / 一般 script 不得直接使用 `git commit --no-verify` 或 `git commit -n`。
唯一合法例外是 `workflow_transition.py control-plane-commit` 與首次 Brownfield 的 `adopt-control-plane`；兩者都必須經 TTY Human Authorization、限制 staged scope，並同步寫入 audit log。

## Team Authorization
團隊專案建議依 `templates/CODEOWNERS.example` 建立真正的 `.github/CODEOWNERS`，並搭配 branch protection / required review。不要保留範例中的 `@YOUR_TEAM`。

## Git mutation model
Gate 以 `status + old_path + new_path` 判定 staged mutation，不只檢查檔案寫入。Control Plane 的 create / modify / delete / rename-away / rename-into 都受保護；`workflow/STATE.md` 與 `workflow/state-log.md` 不得刪除或改名。

## Control Plane audit 能力邊界
`audit-control-plane.py` 驗證的是 Control Plane mutation 與 audit record 的一致性，不證明 audit record 一定由人類產生。真正的團隊授權依賴 CODEOWNERS、branch protection、required human review。`Parent SHA` 僅作人類閱讀 metadata，不作 validity 條件；digest 以 binary-safe mutation content 計算，rebase 不應使合法記錄失效。


## Regression Test Validity
Starter security / workflow regression tests 必須證明「功能壞掉時會失敗」，不能只追求測試為綠。

新增或修正 regression test 時：
- Git fixture 明確指定 branch（例如 `git init -b main`），不得依賴 host `init.defaultBranch`。
- setup / checkout / merge / rebase 等必要 Git command 必須檢查 return code。
- 預期 rebase 時，必須斷言 commit SHA / ancestry 確實改變。
- 預期 merge 時，必須斷言 merge commit 確實有多個 parent。
- Audit test 不得意外使用 empty revision range。
- 新的安全 regression 在提交前應暫時還原對應修正，確認測試 RED；再恢復修正確認 GREEN，並保留該次失敗輸出於 review/回報。
- 新增或修改 `workflow/bin/**` 的 Control Plane 行為時，完成條件包含：對應 regression + 至少一次 broken→RED 輸出；沒有 RED evidence 不得宣稱該修正完成。

## Unicode / Git path parsing
所有 Git mutation discovery 必須使用 NUL-separated (`-z`) name-status 輸出解析。不得依賴 `core.quotePath`、tab-separated path parsing 或 host locale。繁體中文、空白與 tab 等合法 Git 路徑必須保持原始語意。

## Installation baseline
Greenfield / Brownfield 首次安裝的 sanctioned baseline 判準由 `workflow_state.py` 單一 helper 定義，Gate 與 CI audit 共用。Pristine STATE 只是必要條件之一；必要 Control Plane artifacts 必須為 initial additions，不能用初始 STATE 掩護既有 Control Plane mutation。

## Control Plane audit additional limits
- Control Plane digest 綁定 mutation 內容，不綁定 commit identity；相同 mutation digest 可能被歷史記錄重放。這不提升或改變 Human Authorization 能力。
- Historical commit 無法讀取有效 STATE 時，audit fail-closed 使用 `ENGINEERING` policy，因為這是 Control Plane 覆蓋較大的保守選擇。
- Merge commit 只對「merge result 相對所有 parent 都是新內容」的 mutation 負責；單純帶入已存在於任一 parent 的合法 mutation 不應重複要求授權記錄。



## Release artifact hygiene

Starter release roots must not contain `__pycache__/`, `*.pyc`, or `.DS_Store`. The regression suite is the release gate: if these artifacts exist under any path in `workflow/SHIPPED-MANIFEST.txt`, the suite must fail. `workflow/bin/clean-release-artifacts.sh` is only a remediation tool and must refuse to run outside a verified Starter root. Starter self-tests run with `PYTHONDONTWRITEBYTECODE=1` so the test process does not create the artifact it is checking for.
 Shell scripts must use `${var}` whenever a variable is immediately followed by Chinese or other non-ASCII punctuation/text; unbraced `$var` before non-ASCII is forbidden for macOS bash 3.2 compatibility.

## Installation trust anchor
Installation baseline 證明的是「mutation 結構符合乾淨的 Starter 初始安裝」，不證明被安裝的 Control Plane 原始內容可信；首次安裝 PR 仍需人類 review。既有 Control Plane 不得由 baseline 豁免覆蓋，必須人工合併並走 `adopt-control-plane`。
Audit 無法讀取歷史 STATE 時使用 `AUDIT_FAIL_CLOSED_PHASE=ENGINEERING`，這是刻意的最大保護 fallback。

## Brownfield Adoption Scope
`adopt-control-plane` 的 TTY 確認清單必須等於實際 staged commit 內容；任何非 Starter installation allowlist 的 mutation 都必須在 TTY 前拒絕。adopt 使用當下 pristine STATE phase（DISCOVERY）計算 Control Plane，不得以永久 ENGINEERING override 補償 digest。

`check-install-conflicts` 只保證偵測 Git 已追蹤的既有 Control Plane mutation；若使用者在執行 bootstrap 前已用檔案複製覆蓋未追蹤／被 ignore 的同名檔案，Git 無法還原原內容。Brownfield 不應先直接覆蓋既有 Control Plane。


## Brownfield tracked overwrite scope
`check-install-conflicts` 同時區分兩類：
- **Control Plane conflicts**：需人工 merge 後走 `adopt-control-plane`。
- **Tracked Starter-file overwrites**（例如既有 `CLAUDE.md` / `README.md` / `PROJECT-PROFILE.md`）：bootstrap 不會靜默 commit。每個檔案可選擇採用 Starter 版本、保留 HEAD 原版或人工合併；處理後必須先以一般 commit 保存，再重跑 bootstrap。只 stage 而未 commit 仍會被 overwrite preflight 擋下。

安裝期 Control Plane 判準固定使用 pristine `DISCOVERY` phase；不得用 audit fail-closed 的 `ENGINEERING` phase 來決定 adopt 衝突。


## Additional v1.0 known limitations
- `playwright-report/` 是 gitignored 的本機 runtime artifact。`verification-pass` 對 report 存在性的檢查只保證產生 evidence 的那台機器；其他 clone / CI 不會自動取得 report 本體。
- `.claude/**` 的 PreToolUse / settings 是 Claude Code 的即時回饋層；Codex 與其他 agent harness 不一定執行它們，仍須依 pre-commit、CI audit 與 PR review。
- `verify.sh` 自動偵測主要涵蓋 Node（npm/pnpm/yarn/bun）與 Python（ruff/pytest/mypy）專案；其他 stack 需自行擴充 project checks。

- `SETUP.md` 的外部工具安裝指令屬人工核對資訊，不由 Starter CI 持續連網驗證；重大 Starter 版本釋出前需重新確認官方來源與版本。


## Repository enforcement（rc.5）

`workflow_bin` 的 `repository_enforcement()` 是唯一判準，`doctor`、`setup-git-hooks.sh`
與 regression tests 共用。有效 hook 由 git 自己回答
（`git rev-parse --path-format=absolute --git-path hooks`），檔名由本模組自行追加，
不自行推測 `.git/hooks`、`core.hooksPath` 或 worktree 規則。

**只向 git 要目錄，不要向它要最終檔名。** 實測 Apple Git 2.50.1：
`--path-format=absolute` 必然 realpath 最終元件，`--path-format=relative` 在相對
`core.hooksPath` 時也會；不加 `--path-format` 的預設格式在測試矩陣中保留字面名稱，
但 git 文件只說預設格式是 option-specific，沒有契約保證。先取目錄再自行 join：
目錄與其 ancestor 被 canonicalize（看穿 `/tmp` vs `/private/tmp`、ancestor symlink、
大小寫別名），最終元件保持字面，兩邊都拿到。

### fresh-clone 不變式

Repository enforcement 的定義是「**clone 之後 gate 仍然生效**」。因此有效 hook 必須：

1. 位於 worktree 內（`.git/` 內的 hook 永遠不算）
2. **在 HEAD 裡**，且 HEAD 的 mode 是 `100755`
3. index 裡也必須是 `100755`（HEAD 管「現在 clone 拿到什麼」，index 管「下一個 commit 之後 clone 拿到什麼」）
4. **HEAD 快照本身通過一次行為驗證**

這四條對 managed 與 chained 一律適用。只擋 managed 是不夠的：
`core.hooksPath=.myhooks` 加上未追蹤的 `.myhooks/pre-commit`（symlink 或普通檔案）
會產生同一個「本機 ACTIVE、fresh clone INACTIVE」的繞過。

**權威是 HEAD，不是 index，也不是 worktree。** 這一條是踩過才確立的：先前的不變式綁在
`git ls-files -s`（index）與 worktree 內容上，兩者都是本機狀態，對一個有 shell 的對手
完全可控。四種可實際重現的分歧，舊判定全部回報 ACTIVE，而 fresh clone 全部不生效：

| 分歧 | 舊判定為何通過 |
|---|---|
| hook 只 `git add` 未 commit | `ls-files -s` 把 staged addition 也算成 tracked |
| HEAD 是 `100644`、本機 `update-index --chmod=+x` | 檢查的是 index mode |
| HEAD 存空轉 hook、worktree 才是真 bridge | 路徑與 mode 全合格，probe 跑的是 worktree |
| HEAD 的 `check-implementation-gate.py` 是空轉、worktree 是真 checker | hook 檔案本身完全一致，`gate_impl_sha256` 也一致（它讀 worktree） |

最後一種說明了為什麼**必須對 HEAD 實際執行一次**，而不是比對某個檔案集合：chained hook
可以透過任意 wrapper 間接呼叫 gate，要比對的檔案無法事先枚舉。`probe_head_enforcement()`
把 HEAD 實體化成獨立 repository，在其中跑同一套行為驗證，驗的是整條實際依賴鏈。

**快照必須真的等價於 clone，這比「有跑 probe」更難。** 實體化用
`git bundle create <tmp> HEAD` → `git clone <tmp> dest`，最後斷言 `HEAD^{commit}` 與
`HEAD^{tree}` 都與來源相同。四種踩過的錯：

| 錯誤做法 | 後果 |
|---|---|
| 在**來源 repo** 跑 `checkout-index` | 套用來源 `.git/config` 的轉換。`.gitattributes` 進得了 clone，`filter.X.smudge` 與 `core.autocrlf` 這些**本機 config** 進不了 —— 實測可用 smudge filter 把空轉 checker 洗成真 checker，快照通過而 clone 失敗 |
| checkout 之後重新 `init/add/commit` | `git add` 加不進 `checkout-index` 為 gitlink 造的空目錄，mode `160000` 被靜默丟掉；快照走 fallback 而通過，clone（submodule 未初始化）空轉 |
| `objects/info/alternates` 引用來源 ODB | 快照看得見來源的**全部** object，包含 unreachable 的；clone 只拿得到 HEAD 可達物件。實測 hook 寫成「某個 dangling object 存在才執行 gate」，本機與快照都通過而 clone 空轉 |
| 直接 `git clone` 本機路徑 | detached HEAD 指向的 commit 若不在任何 ref 上就取不到，而要驗的正是那棵 tree |

bundle 同時滿足四件事：只含 HEAD 可達物件、dest 用自己的 config checkout、gitlink 原封保留、
`HEAD` 是 rev 而不是 ref（detached 且完全沒有 branch 也可以）。代價是它會打包完整歷史，
大 repo 上不便宜 —— 因此只在明確 `--probe` 時執行。

### HEAD 快照的能力邊界

**本模組不宣稱快照與任意 fresh clone 的完整行為等價，而且做不到。** chained hook 可以
讀任意 Git metadata 與執行環境 —— remote URL、ref layout、branch 或 detached 狀態、
路徑、環境變數、主機名稱、時間 —— 而「使用者未來會用哪個 URL、哪些 clone option
取得這個 repository」不存在於 HEAD 裡。實測反例：hook 判斷 `remote.origin.url` 為空或
以 `.bundle` 結尾就執行 gate、否則空轉，本機與快照都通過而真正的 transport clone 不生效。

因此 HEAD 快照 probe 的**安全宣稱只到這裡**：

> 在一個隔離的 Git repository 中，對 HEAD 這棵 committed tree 執行有效 hook，
> 確認它會拒絕 Control Plane mutation。

**明確排除**：行為取決於 `.git/config`、remote、refs、路徑或執行環境的 conditional hook。
這一類由 CI 直接跑 Control Plane audit 與 gate、以及 PR review 承擔 —— 見〈能力邊界〉。

快照會把兩個最明顯的 tell 正規化（`remote.origin.url` 設成來源的 origin，來源沒有時用
來源絕對路徑；來源在具名 branch 上時快照也在同名 branch 上而非 detached）。
**這是保真度，不是防禦層**：它擋下意外的環境指紋，也讓因別的理由而讀 origin 的誠實 hook
不會在快照裡假性失敗，但擋不住有心偵測。不要把它算進防禦層數。

**submodule 界線**：快照等價於**普通、未遞迴**的 clone，gitlink 保留為未初始化的空目錄。
依賴 submodule 內容才生效的 gate 會在快照 probe 失敗而判為 INACTIVE —— fail-closed，
因為 `git clone` 預設也拿不到那些內容。

probe 直接執行 hook 檔案，**不用 `bash <hook>` 代跑** —— git 是直接 exec，因此 shebang
與 executable bit 都算數。用 bash 代跑會讓 mode `644` 的 hook 通過 probe（實測如此）。

**chained 專案必須先把 bridge commit 進 HEAD，才驗得起來。** 這是 fresh-clone 不變式的
直接後果，不是額外要求：還沒 commit 的 bridge，clone 之後不存在。

managed 身分以 **`os.path.samefile` 的實體目錄同一性**判斷，不用字串相等 ——
`.GITHOOKS`（case-insensitive 檔案系統）或指向本 repository 的絕對 ancestor symlink
都會讓字串比對失手，把合法安裝誤判成 chained，或讓別名路徑繞過 managed 專屬檢查。

| 狀態 | 意義 |
|---|---|
| `ACTIVE_MANAGED` | 有效 hook 是 Starter 管理的 `.githooks/pre-commit`，且 HEAD 與 index 的 mode 均為 `100755`，並通過 worktree 與 HEAD 快照兩次行為驗證 |
| `ACTIVE_CHAINED` | **行為驗證通過**（probe receipt 有效）。不要求靜態字串命中 —— 透過 wrapper 或 dispatcher 間接呼叫也算 |
| `CHAINED_STATIC` | 靜態找到 bridge 但尚未行為驗證。**不算 active** |
| `UNKNOWN` | 有自訂 hook，但既無靜態 bridge 也無有效 receipt —— 不得樂觀顯示為 ACTIVE |
| `INACTIVE` | 沒有 hook、不可執行、位於 `.git/` 內、未被追蹤、只 staged 未 commit、已 staged 移除、HEAD 或 index 的 mode 不是 `100755`、最終元件是 symlink，或 HEAD 快照未通過行為驗證 |

**不要對任何一層宣稱「不可達」。** symlink 拒絕分支曾被判定為死碼並標註「不是安全邊界」，
那是錯的：當時的程式移除它就會得到 `ACTIVE_MANAGED`（HEAD／index 存 mode `100755` 的
空轉 hook，worktree 換成指向真 gate 的 symlink；tracked 與 mode 檢查都查 index，兩關都過，
重新 probe 又會產生一張綁定當前 symlink 目標的新 receipt）。誤判的原因是突變用的 fixture
指向 noop 而且沒跑 `--probe`。**深度防禦會讓各層互相遮蔽，只看最終結果的斷言證明不了
任何一層還在** —— 每一層都必須有一條「只有該層適用」的隔離測試，並以突變確認它會變紅。

Starter **不覆蓋**既有 hook framework（政策不變），但未串接時 `setup-git-hooks.sh`
回傳非零、`bootstrap` 不以 ready 結束。

### 能力邊界

`ACTIVE` 不代表不可繞過。`git commit --no-verify`、`HUSKY=0`、直接改 hook 都是本機 hook
的固有限制，須由政策禁止並由 CI audit 與 PR protection 補強。

串接判定分兩級：

- **靜態命中**（bridge 指令出現在非註解行）只得到 `CHAINED_STATIC`，**不算 active**。
  這比純字串比對強，但仍無法證明可達性 —— `if false; then bash .githooks/pre-commit; fi`
  與 `echo bash .githooks/pre-commit` 都會靜態命中。
- **行為驗證**（`enforcement-status --probe` 或 `setup-git-hooks.sh --probe`）以暫時
  `GIT_INDEX_FILE` 製造一個 Control Plane mutation、實際執行有效 hook，並要求觀察到
  gate 的拒絕訊號（不接受「只是回傳非零」）。通過後才是 `ACTIVE_CHAINED`。

probe receipt 存於 `.git/starter-enforcement-probe.json`（不進 repo），綁定有效 hook 的
路徑、內容 digest、mode、gate 實作 digest，以及 **HEAD 的 tree sha**；chained 另外綁
**整片已追蹤路徑在 worktree 的原始位元組**摘要（含 mode 與 symlink 目標）。
任一改變即降回 `CHAINED_STATIC`。

這個摘要**不能**用 `add -u` + `write-tree` 算：`add` 會套用來源本機的 `filter.X.clean`，
不同的實際內容可以被 clean 成同一個 blob、同一棵 tree。實測把 clean 設成「永遠輸出好的
那份 wrapper」，wrapper 換成 `exit 0` 之後 tree sha 完全不變，receipt 續報有效。
hook 執行的是磁碟上的位元組，摘要就只讀磁碟上的位元組。

chained 的範圍必須這麼寬，是因為它的依賴鏈是開放的：實測繞過是 `.myhooks/pre-commit`
呼叫 `scripts/hook-wrapper.sh`，probe 通過後把 wrapper 改成 `exit 0` —— hook 檔案、HEAD、
以及只涵蓋 `workflow/bin` 與 `.githooks` 的 digest 全都沒變，receipt 仍然有效。
managed 不需要這麼寬。精確的說法是**針對 probe 的 DENY 路徑**：`.githooks/pre-commit`
先呼叫 `workflow/bin/check-implementation-gate.py`，checker 拒絕後即因 `set -e` 結束
（hook 後面還會呼叫 `verify.sh`，但那在 DENY 路徑上到不了）。該路徑上的 repository
executable code 全部落在 gate digest 範圍內，而改動 hook 本身會讓 `hook_sha256` 變 ——
依賴鏈在**版本控管檔案**這個層次是封閉的。因此 managed 專案不會因為無關的程式碼編輯
就讓 receipt 失效。

封閉的只到這裡：PATH、Python runtime、shell 啟動環境等外部依賴仍不封閉，
那屬於下面〈receipt 的性質〉寫明的非對抗邊界。

綁 `HEAD^{tree}` 的代價是**任何 commit 都讓 receipt 失效**。這是刻意的（新的 HEAD 就是
還沒被驗證過的 HEAD），但操作上很吵，須在 release notes 說明。

**receipt 的性質**：它是非對抗模型下的 probe 快取與 freshness token，**不是認證，也不是
不可偽造的安全證明**。`ACTIVE` 只表示「指定 fingerprint 所涵蓋的輸入自上次 probe 後未變」。
不要把它說成「系統不會謊稱 enforcement 生效」—— 那句話太強：fingerprint 涵蓋不到的東西
改變時（這正是上面那個 stale wrapper 的情境），系統依然會回報 ACTIVE 而沒有任何偽造行為。

CI 若要驗 hook wiring，應**一律執行 `--probe`，不採信既有 receipt**（fresh checkout 通常
沒有 receipt，但 cache restore 或自管 runner 未必）。更重要的是 CI 的真正安全邊界是直接跑
Control Plane audit 與 gate；hook probe 只能是補充的 required check。

普通 `doctor` 不會自動執行第三方 hook —— probe 必須由人類明確觸發。

## 測試案例文件的勾選狀態

`workflow/test-cases/<change>.md` 的 `[ ]` / `[x]` 是**給人類閱讀與追蹤用的**，
**不是 gate 憑證**。Gate 只採信 `workflow/evidence/<change>/` 裡由 `verify.sh`
產生的機器 evidence（具名 check、command、exit code）。

理由與 evidence ownership 一致：AI 可以寫出那個勾，所以那個勾不能證明任何事。
勾選只能在案例實際通過之後更新。

## Core verification policy（rc.5）

`PROJECT-PROFILE.md` 的 `Core verification policy` 決定 full verification 的判準：

| 值 | 語意 |
|---|---|
| `auto` | 執行 Starter 能辨識的 checks；**零 runnable checks 時失敗** |
| `custom` | 使用 `Custom verification command`，必須真的執行並記錄結果 |
| `not-applicable` | 純文件或刻意沒有 automated verification 的 repo；**必須填非空 `Verification exception reason`**，且結果為 `NOT_APPLICABLE` 而非 PASS |

**規則**：預設情況下至少要實際執行一個具名、有 command 與 exit code 的 automated check，
否則不得產生 PASS。不要求一定有 test —— lint、typecheck、build、專案自訂 verifier 都算。

工具偵測區分三件事：專案存在 / check 已配置 / runner 可執行。
**已配置但 runner 不可用時必須失敗**（`configured but unavailable`），
不得當作「沒有適用的檢查」而略過。

Python runner 依序尋找 PATH 與 `./.venv/bin`。刻意**不**自動採用 `uv run` / `poetry run`：
兩者存在不代表工具已安裝在該環境，實測會誤判為 runnable、執行時才失敗，
並在採用者專案產生非預期的 `.venv`。這類情境請改用 `Core verification policy: custom`。

## Core evidence schema 2（rc.5）

```text
Core evidence schema: 2
Verification policy: auto
Checks selected: 2
Checks executed: 2
Outcome: PASS
Overall exit code: 0
```

`core_evidence_status()` 是語意化 validator：

- `PASS` 必須 `Checks executed >= 1` 且 `Overall exit code: 0`
- `NOT_APPLICABLE` 必須與 Profile 政策一致且 `Exception reason` 非空
- 零檢查配 `Outcome: PASS` 一律拒絕
- **舊 schema（無 `Core evidence schema` 欄位）一律拒絕並要求重跑**

`verification-pass` 採用 `verify.sh` **明確回報**的 evidence 路徑，不用「前後檔名集合差」，
也不用 `latest_core()` —— 後者依檔名排序，植入未來時間戳的檔案會成為被驗證的對象。
被接受的路徑另外驗證必須位於 `workflow/evidence/<change>/core/` 且檔名符合 core evidence 格式。

### 已知邊界：browser.md 與 core evidence 未綁定

Web 專案的 `browser.md` 由 AI 撰寫並引用一份**已存在且通過**的 core evidence，
而 `verification-pass` 之後會產生並接受**另一份**新的 core evidence。兩者目前沒有綁定，
因此 browser evidence 可能對應到較舊的程式狀態。

這是流程順序造成的（browser evidence 必須先於最終驗證存在）。rc.5 選擇明文記載而非改動順序；
若要收緊，應在 `browser.md` 記錄它所依據的 Git SHA，並由 `verification-pass` 核對。

### Core verification policy 的可逆性（已知邊界）

`PROJECT-PROFILE.md` 只在 DISCOVERY／SPECIFICATION 可寫，之後即為 Control Plane。
因此「補上測試後想把 `not-applicable` 改回 `auto`」這個**收緊**動作，在後期需要人類以
`control-plane-commit` 執行；而在早期階段「從 `auto` 放寬成 `not-applicable`」不需要授權。

**這與 `revert-to-spec` 的 ratchet 方向相反，是刻意接受的取捨。** 理由是 policy 沒有完整偏序：
`not-applicable → auto` 明確是收緊，但 `auto ↔ custom` 無法只靠 enum 判斷誰比較嚴
（`custom` 甚至可能比 `auto` 更弱）。為此新增 machine-verified transition 需要同步修改
Profile、gate、state-log 與 audit，超出 rc.5 的合理表面積。

後續版本可考慮一個範圍極窄的 `drop-verification-exception`，只允許
`not-applicable → auto` 並清除理由，不泛化成任意 policy transition。

## Core evidence 的完整性鏈（rc.5）

`verification-pass` **只驗證自己這次執行所產生的那一份 evidence**，不採用 `latest_core()`。
理由：`latest_core` 依檔名排序，植入未來時間戳的檔案會成為被驗證的對象；
**檔名時間戳與系統時鐘都不是 integrity anchor。**

接受後，該 evidence 的相對路徑與 SHA-256 會寫進 state-log 的 verification-pass 條目：

```text
- Core evidence: workflow/evidence/<change>/core/<timestamp>.md
- Core evidence sha256: <64 hex>
```

`archive` 核對同一路徑與 digest，不符即拒絕。

`PASS` 的 evidence 另外要求自洽：`Checks executed` 必須與實際的 `Exit code:` 紀錄筆數相符，
且每筆都是 0；`Change` 欄位必須與當前 change 相符。

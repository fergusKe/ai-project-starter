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

**上面這一段是規範，不是機制。** `--no-verify` 是 git 自己提供的旗標，Starter
攔不到它 —— pre-commit 沒被執行，就沒有任何本機程式碼有機會表示意見。一個有
shell 權限的 agent 只要打這個旗標，本機所有 gate 同時失效。

而「對有 shell 權限的對手，規範不構成約束」正是這整套 Control Plane 存在的前提。
把它套用在自己身上：**本機層永遠只能做到「盡量」，真正的 gate 必須在伺服器端。**

因此 `--no-verify` 的完整答案是兩段：本機寫成規範（讓誠實的參與者知道界線），
伺服器端寫成機制（讓不誠實的參與者過不去）。後者的設定與驗證步驟見
`workflow/MERGE-PROTECTION.md`，**包含一個必做的失敗實測** —— 沒有實際看過
「合併按鈕變灰」，就不能宣稱這一層存在。

沒有 remote 的單機專案不適用第二段。那種情境下 `--no-verify` 是已知的、無法
消除的邊界，應在 `CONTEXT.md` 明白記錄，不要假裝本機 gate 是完整的。

## Team Authorization
團隊專案必須依 `templates/CODEOWNERS.example` 建立真正的 `.github/CODEOWNERS`，並搭配 branch protection / required review。不要保留範例中的 `@YOUR_TEAM`。

CODEOWNERS 的涵蓋範圍不只 Control Plane 本體，還必須包含：

- `.github/`（**執法層自己**。CI workflow 與 CODEOWNERS 若可被自由修改，
  required check 與 required review 都能被安靜地拆掉。守衛的設定檔必須跟守衛
  一樣受保護。）
- `PROJECT-PROFILE.md`、`openspec/`、`workflow/test-cases/`（**被批准的內容**。
  它們的 digest 被寫進 STATE 並由 gate 複驗，改它們等於改已批准的範圍。）
- `workflow/evidence/`（**封存證據**。review 是本機 freeze 之外的第二道。）

完整設定流程見 `workflow/MERGE-PROTECTION.md`。

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

**agent 的執行環境不在 Starter 的控制範圍內。** 使用者層級的 `~/.claude/settings.json`、
skills 與 hooks 會在每一個專案生效，包含裝了 Starter 的專案；它們不在版控裡、
`git clone` 拿不到、換一台機器可能完全不同。Starter **不宣稱**下列任何一件事：

- fresh clone 能重現完整的 agent 指令環境
- 專案版控內容是 agent 實際收到的全部指令來源
- Claude Code 的 hook 是不可繞過的安全邊界

已確認的合成規則（非推測）：多來源的 PreToolUse hook 是**合併**執行、決策優先序為
`deny > defer > ask > allow`，所以使用者層級的 `allow` **不能**覆蓋專案的 `deny`。
但 hook 是可執行程式不是純投票 —— 使用者 hook 可以在最終判定為 deny **之前**就產生
副作用（改檔、改 git config、啟動外部程序），而且 hooks 平行執行，不能依賴順序。
同名 skill 的優先序是 `managed > user > project`，因此使用者層級的同名 skill
**會遮蔽**專案版本；`doctor` 對這一項給 WARN。

`doctor` 的 `Agent environment provenance` 是**獨立的可觀測性訊號，不參與
Repository enforcement 的 ACTIVE/INACTIVE 判定**。兩者問的問題不同：enforcement 問
「clone 之後 gate 還在不在」，provenance 問「這台機器上還有誰在對 agent 說話」。
把後者混進前者，等於讓 Starter 對它無法驗證的東西下判斷。

provenance 只做 **filesystem inventory**，不是完整的 effective runtime inventory。
看不到 managed policy、CLI `--settings`、session hooks、plugin 與 frontmatter 帶的 hooks、
MCP 與 subagent 碰撞、以及 shell environment。要看實際生效的完整清單，
用 Claude Code 的 `/hooks` 與 `/status`。輸出刻意不含 hook command 本文、
環境變數值與 skill 內容 —— doctor 的輸出常被貼進 issue 與聊天室。

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

### receipt 只能替 probe **之前**捕獲的狀態背書

fingerprint 必須在**任何 probe 執行之前**取得（`F0`），probe 全部通過之後再量一次
（`F1`），`F0 == F1` 才寫 receipt，而且寫進去的是 `F0`。

為什麼不能在 probe 之後採樣（這是原本的作法）：**hook 是被實際執行的程式**，它可以在
被驗證的過程中改變自己。實測重現 —— 一個 chained hook 先呼叫真 gate（於是本機 probe
與 HEAD 快照 probe 都通過），再用 `mv` 把自己換成 `#!/bin/sh` + `exit 0`。舊流程在那
之後才量 worktree，receipt 記下的是空轉版的 `hook_sha256`，`probe_receipt_valid` 回
True，之後每次 `enforcement-status` 都繼續宣稱「行為驗證通過於 …」，而 gate 已經不在。

同一條規則也關掉另一個競態視窗：`讀 C0 → bundle 捕獲 C0 → 來源切到 C1 → 快照驗 C0
→ receipt 綁 C1`。只比較快照與最初讀到的 `C0` 抓不到它，因為快照本來就等於 `C0`。

`F0 != F1` 時必須**刪除** receipt 並回非零，不能只是不寫 —— 留著上一次的舊 receipt
會讓下一次不加 `--probe` 的 `enforcement-status` 繼續宣稱驗證通過。

能力邊界：狀態在 probe 期間變成 B 又變回 A 時 `F0 == F1` 成立，而 probe 實際跑的是 B。
關掉這個視窗需要 lock 或 kernel 級的變更通知，兩者都超出 Starter 的範圍。receipt 的
宣稱因此是「**這個 fingerprint 被 probe 過，且前後未變**」，不是「probe 期間不存在
其他狀態」。

> 註：用 `printf > "$0"` 寫的自我改寫 hook **不會**重現這個問題 —— 那會截斷 shell
> 正在讀的檔案，`exit` 那行讀不到，hook 回 0 而被 probe 判失敗。那是自我改寫腳本的
> artifact，不是防禦。寫這類 regression 時必須用 `mv` 換 inode，否則測到的是別的東西。

## Change identifier 的 canonical validation

change 名字有**兩個**下游消費者，失敗模式完全不同，所以驗證必須集中在一個
validator（`validate_change_id`）並在**寫入之前**執行：

1. **路徑**：`openspec/changes/<id>`、`workflow/evidence/<id>/core`。實測
   `start-change ..` 會讓路徑指向 `openspec/`，它非空，所以「目錄不得為空」的檢查
   通過；`verify.sh` 則會把 machine evidence 寫到 `workflow/core/`，越出宣告的
   ownership 位置。
2. **檔案格式**：STATE.md 是 `Key: value` 的逐行格式。實測
   `evil\nPhase: ENGINEERING` 會讓 STATE.md 出現第二個 `Phase:`。

第 2 點的結果值得記下來：`parse_state_text` 的重複欄位檢查**擋住了升級**（fail-closed，
方向正確），但擋下的方式是拋出未被接住的 `ValueError` —— 此後每一個 transition 都噴
traceback，Control Plane 等於被砸爛，而那筆污染永久留在 append-only 的 state-log 裡。
**fail-closed 不等於處理得當**：讀取端必須把「Control Plane 檔案損壞」報成可讀的錯誤
（exit 42），不是 stack trace。

驗證同時發生在寫入端（CLI，涵蓋所有接受 change 參數的子指令）與讀取端
（`parse_state_text`，涵蓋已經在檔案裡的污染）。`verify.sh` 因為直接 grep STATE.md
繞過了 `parse_state`，所以呼叫同一個 validator，不另寫一份會漂移的 shell 規則。

不採「純小寫」的 allowlist：大小寫是命名風格不是安全性質，強制它會擋掉合法的既有
專案。危險的是 `/`、`.`／`..`、控制字元與換行。

## PROJECT-PROFILE 的三條不變式

**一、打錯字不是未決，是已決定。** 只排除 placeholder、其餘一律視為已解析的設計會
fail-open。實測 `Type: WEB_AP`（少一個字母）通過 profile resolution，而
`project_web_status` 因為它不等於 `WEB_APP` 判為 `NON_WEB` —— **一個 typo 靜默關掉
Browser Gate**。有正式 vocabulary 的欄位必須做列舉檢查，而且決定 Gate 開關的那一層
（`project_web_status`）也要對無法辨識的值 fail-closed，不能靠「不等於 WEB_APP」推論
它是非 Web。`invalid` 必須與 `unresolved` 分開回報，否則使用者會以為自己沒存檔。

沒有可窮舉正確答案的欄位（`Primary stack`、`Package manager`、`CI provider`）維持自由
文字。`Test database strategy` 保留 `other: <描述>` 逃生口，但描述不得為空 —— 單獨的
`other:` 是 UNKNOWN 換皮。

**二、被批准的內容必須包含驗證契約本身。** `Core verification policy`、
`Custom verification command`、`Verification exception reason` 有預設值因此永遠「已
解析」，但它們決定驗證契約。不納入 digest 與 TTY 顯示的話，
`Core verification policy: not-applicable` 可以在 SPECIFICATION 階段寫進去，七個必填
欄位全部通過，人類看到的畫面完全不提 verification 已被豁免，之後 zero-check 的
`NOT_APPLICABLE` 就依這個從未被明示批准的政策通過。

**三、批准綁的是內容，不是旗標。** 人類批准當下的 digest 寫進 STATE 的
`Approved profile digest`；`approve-spec` 在 TTY 返回後重新比對（TTY 是人類速度的等待，
視窗以分鐘計），`start-engineering` 再比對一次（approve-spec 與 start-engineering 之間
可以隔任意長的時間與任意多的 agent 動作）。只檢查 approval flag 的設計看不到這段期間
的放寬。舊 STATE 沒有這個欄位時視為未綁定並 fail-closed，要求重新 approve-spec。

**四、綁定是持續不變式，不是一次性關卡。** 上面第三條原本只在 `start-engineering`
比對一次，那還不夠 —— 實測兩個繞過：

- **已在 ENGINEERING 的舊 STATE**（沒有 `Approved profile digest` 欄位）解析後
  `profile_digest == 'none'`，但 `implementation_allowed` 仍為 True，產品 commit 照樣
  放行。它已經越過 `start-engineering`，永遠不會再碰到那次拒絕。
- **worktree-only 掉包**：批准 `Core verification policy: auto` 並進入 ENGINEERING 後，
  只在 worktree 改成 `not-applicable`（**不 stage**），`verification-pass` 會產生並接受
  一份 `Checks executed: 0` / `Outcome: NOT_APPLICABLE` 的 evidence；事後把檔案 restore
  回去，git 看不到任何 profile mutation。fresh clone 拿到的是批准過的 `auto`，
  而 archived evidence 是依從未被批准的 `not-applicable` 產生的。

所以判準必須集中成一個 `approved_profile_status(root, state)`，由**每一項批准後能力**
使用：pre-commit gate（透過 `implementation_authorized`，不能只看
`implementation_allowed` —— 那是 STATE 內部的推導，看不到 profile 被換掉）、
`approve-tests`、`start-engineering`、`verification-pass`、`archive`。

`none` 的語意是「**可解析，但不具備任何批准後權限**」，不是「下次 start-engineering
會擋」。讀取端保持可選是對的（升級不該讓 Control Plane 變成損壞），錯的是後續消費。

**五、evidence 必須自證來歷。**

### validator 的分段順序不是美感問題

`core_evidence_status` 拆成 `_core_evidence_semantics` → `_core_evidence_provenance`
兩段依序執行。語意先跑（「這份 evidence 宣稱了什麼」），來歷後跑（「該不該相信它」）。

原因是實測出來的：把來歷檢查插在語意檢查**中間**，它會**遮蔽**五條既有的語意
regression —— 那些測試在到達自己的斷言之前就因為「缺少 digest 欄位」而短路，
於是它們宣稱在測的東西全部沒被測到。防禦層互相遮蔽在這個專案是反覆出現的失敗模式。

刻意**不**拆成兩個公開函式讓呼叫端自己組合：那會多出一條「有人只呼叫其中一段」的
未鎖住路徑。兩個呼叫端（`verification-pass`、`archive`）都只呼叫 `core_evidence_status`。

### 來歷這一層需要**隔離型**測試

「竄改 evidence 的 digest 後 archive 會拒絕」**沒有**測到來歷層 —— archive 會先比對
state-log 記錄的 SHA-256，竄改檔案在那裡就被擋下。突變測試證實：把
`_core_evidence_provenance` 整個拿掉，或把 digest 比對改成永遠通過，那條測試照樣是綠的。

所以必須有一條直接呼叫 validator、不經過任何會更早開火的層的測試，四種情境都要涵蓋：
缺欄位、值為 `none`、格式正確但對不上、正確。 core evidence 記錄 `Approved profile digest`，
validator 比對它與 STATE 的值。理由與第四條的第二個繞過同一件事：產生 evidence 的
profile 可以在事後被 restore，git 因此看不到任何痕跡 —— evidence 自己不帶來歷的話，
沒有任何一層能事後判斷它是依哪一份被批准的政策產生的。

**`none` 作為保留哨兵。** `Active OpenSpec change: none` 表示「沒有 active change」，
所以 `none`（含 `None`／`NONE`）不得作為 change id。允許它會產生自相矛盾的狀態：
transition 成功、append-only log 追加一筆，但讀取語意認為沒有 change，而 `verify.sh`
之後又因 `change == none` 拒絕。那筆矛盾永久留在稽核紀錄裡。

> 註：`approved_profile_status` 裡「digest 為 `none`」那個分支，**在安全性上是冗餘的**
> —— 真 digest 永遠不等於字串 `none`，後面的比對也會擋。突變測試證實拿掉它整組測試
> 照樣全綠。保留它是為了**診斷**：舊 schema 的使用者需要「請重新執行 approve-spec」
> 這個可操作的指示，而不是一則寫著「批准時 digest: none」的比對失敗訊息。
> 因此該鎖的是**訊息內容**，不是擋不擋。這也是一個提醒：冗餘不等於可刪，
> 但它的測試必須鎖住它真正提供的東西。

## 生命週期必須有第二輪

`start-change` 接受 `DISCOVERY` / `SPECIFICATION` / **`ARCHIVE`**。

原本只接受前兩者，於是做完第一個 change 之後**整個 Starter 沒有合法的第二輪入口**：
`start-change` 拒絕（exit 34）、`revert-to-spec` 拒絕 ARCHIVE 並叫使用者「請建立新的
OpenSpec change」（一個做不到的建議）、`set-mode` 只允許 DISCOVERY。而 `AGENTS.md`
的規範明寫「ARCHIVE 後必須開新 change」。

**這不是安全漏洞，是工具不能用。** 十三輪對抗審查都沒發現，因為所有情境（包含 G4
冷啟動）都停在 SPEC_REVIEW 之前。安全審查會盯著對手做得到什麼，不會盯著使用者做不到
什麼 —— 兩種缺陷都要找。

從 ARCHIVE 起新的一輪時：
- **所有** approval flag 與被批准內容的 digest 都要清掉（少清一個就等於讓新 change
  繼承上一輪人類的批准）。
- `Project mode` 保留 —— 那是 repository 屬性，不是 change 屬性。
- 拒絕沿用剛封存的 change 名，否則新一輪的 evidence 會寫進已封存那一輪的目錄，
  而 state-log 的兩筆 verification-pass 會指向同一條路徑。

## 批准綁內容：spec 與 test design

第十三輪只對 profile 做了「綁內容不綁旗標」。但 `Spec approved: yes` 與
`Test design approved: yes` 仍是**裸旗標**，而 `openspec/**` 與 `workflow/test-cases/**`
都永久列在 AI-writable allowlist 裡。

實測繞過：批准 Spec A（「只做 X，絕不碰付款」）進入 ENGINEERING 後，把 proposal 換成
Spec B（「直接對外開放付款 API，不做驗證」）、test design 一併換掉，產品 commit 照樣
放行，STATE 仍顯示兩者已批准。fresh clone 看到「已批准」，而實際內容從未被任何人批准。

`Approved spec digest` 綁 `openspec/changes/<change>/**` 的完整內容，
`Approved test design digest` 綁 `workflow/test-cases/<change>.md`。

**勾選狀態不計入 digest。** `[x]` 是進度，在 ENGINEERING 期間本來就會更新；算進去會讓
每打一個勾就撤銷一次人類批准 —— 那不是收緊，是把 gate 變成噪音來源，使用者會學會繞過
它。任務與案例的**文字**則是被批准內容的一部分，不得改動。這與「勾選不是 gate 憑證」
是同一條規則的兩面。

digest 必須能區分「缺檔」與「空檔」，否則刪掉檔案就等於通過。

## Critical user journeys 是被批准的**範圍**

journeys 決定 Browser Verification 涵蓋什麼，因此屬於被批准內容，納入 profile digest。
不納入的話：批准含「結帳、付款」的 profile 之後只在 worktree 改成「首頁」，digest 完全
不變，於是可以產生一份內容完整性無誤、但驗證範圍從未被批准的 browser evidence。

**browser evidence 的 SHA-256 只證明「這份文字沒被換掉」，不證明它覆蓋了被批准的範圍。**
因此 WEB 專案的 `browser.md` 必須對每個已批准的 journey 給出 `J<n>: PASS`；缺項或非 PASS
一律拒絕。

journeys 使用穩定 ID（`- [J1] 描述`）。沒有 ID 就只能比對整段文字，任何排版改動都會變成
gate 失敗。ID 一旦指派不得重用或重編號。

**能力邊界**：這驗證的是**宣稱**覆蓋了哪些 journey，不驗證它們真的被執行過。誠實執行
仍是既有的能力邊界。

> 註：PROJECT-PROFILE 在該區段用 HTML 註解放範例。解析前必須先剝掉註解 —— 否則一份
> 全新的 profile 會憑空「已定義」兩個沒人寫過的 journey，WEB 專案的必填檢查也會被範例
> 矇混過去。這個 bug 是在寫完功能、讀自己輸出時發現的。

## ARCHIVE 之後 evidence 凍結

core/browser evidence 在 gate 的 product 判定裡被豁免（它們由 machine 產生，不算產品
程式碼），但那個豁免原本沒有分階段。結果是 archive 完成後仍可用 shell 或一般編輯器改
evidence 再單獨 commit，而 STATE 繼續顯示 ARCHIVE、`archive` 也不能重跑。state-log 裡
有 digest 可供人工比對，但沒有任何一般 commit、`status` 或 CI audit 會去比。

ARCHIVE 階段拒絕已封存 evidence 的任何 mutation。新的一輪先 `start-change`，
新 change 有自己的 evidence 目錄。

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

## 批准綁定的是「會被 commit 出去的那一份」（rc.5）

`spec_digest` / `test_design_digest` / profile digest 原本只讀磁碟。那證明的是
**本機現在看到什麼**，不是 **clone 之後會拿到什麼** —— 也就是 fresh-clone 不變式
只套用在 hook 上，沒有套用在**內容**上。兩個實測繞過：

1. **未追蹤的 artifact**：openspec / test-design / profile 建立但從未 commit，
   approve 成功綁定 worktree digest，之後只依指示提交 STATE + state-log。
   本機一路通過，fresh clone 拿到一份宣稱「已批准」而被批准的東西根本不存在的 STATE。
2. **index / worktree 分裂**：批准 Spec A 之後把內容改成 B 並 `git add`，再把
   worktree 檔案還原成 A（保留 index 的 B），連同產品程式碼一起 commit。
   Gate 對 spec 路徑走 AI-writable 豁免，digest 比對讀的是 worktree 的 A 因此放行 ——
   但 commit 與 fresh clone 拿到的是從未被批准的 B。

判準因此是 `content_sources_agree`：**worktree / index / HEAD 三者必須是同一份，
且必須存在於 HEAD**。三者比的是正規化後的內容，所以勾選進度仍可只存在於 worktree。

`approve-spec` / `approve-tests` 在 TTY **前後**都檢查 —— 只檢查前面的話，
等待期間把改動 stage 進 index 不會讓 worktree digest 失效，但 commit 出去的是 index 那一份。

### 兩層都要有測試

「批准後內容被換掉」有兩種形狀，由不同的一層擋下：

| 形狀 | 擋下的層 |
|---|---|
| 只改 worktree（不 stage） | 三來源綁定 |
| 改完並 commit | digest 比對 |

只測前者的話，digest 那層可以被整個刪掉而測試全綠。這是 N3 與 Q7c 之後第三次
遇到同一個坑，所以寫成規則：**每加一層，就要有一個只有那一層擋得住的測試。**

## 勾選正規化的套用範圍（rc.5）

`- [x]` 是進度還是決策，取決於它在哪個檔案裡。

- `tasks.md`（檔名以 `task` 開頭）與 test-case 檔：**進度**，正規化掉。
- proposal / specs / design：**決策**，逐字綁定。

原本對整個 change 目錄一律正規化，於是最常見的規格寫法 ——

```markdown
## 已批准範圍
- [ ] 啟用未驗證的公開付款 API
```

—— 被勾成 `[x]` 之後 digest 完全不變，而那是相反的決定。

同一段程式的 `errors='replace'` 也要改掉：replace 會把不同的非法 byte sequence
摘要成同一段文字（全部變成 U+FFFD），等於在 digest 上製造碰撞。非 UTF-8 一律
fail-closed 回 `None`。

## Evidence 凍結的判準是所有權，不是階段（rc.5）

第一版用 `s.phase=='ARCHIVE'` 當凍結條件。那是全域旗標，而 evidence 是分 change 的 ——
執行 `start-change B` 之後 phase 離開 ARCHIVE，change A 的已封存 evidence 立刻又可寫，
而 A 已封存、archive 不會再跑，沒有任何一條路徑會再去比對它。

正確判準（`evidence_write_allowed`）：**只有目前 active change、且正處於
ENGINEERING / VERIFICATION，才能寫自己的 evidence。** 其餘一律凍結 ——
包含歷史 change 的，以及本輪尚未進入工程階段的。

`start-change` 從 ARCHIVE 出發前另外要求 **ARCHIVE transition 已進入 HEAD**：
清掉 STATE 上一輪的三個 digest 之前，那份 STATE 必須先被保存下來，
否則 `archive A → start-change B` 中間不 commit，唯一記載 A 完整 digest 的
STATE 會被直接覆寫，從未進入任何 commit。

## Journey 的 schema 必須完整驗證（rc.5）

`- [J 2] 結帳`（ID 裡多一個空格）原本會被 `findall` 直接忽略。於是 J1 讓 profile
看起來「已定義」，人類以為自己批准了兩條 journey，而 browser evidence 只寫
`J1: PASS` 就通過。**靜默忽略不合法的輸入，等於把打錯字變成關閉檢查** ——
跟 `Type: WEB_AP` 那個 typo 靜默關掉 Browser Gate 是同一個病。

因此 `journeys_status` 回傳 `(journeys, errors)`，三條規則：

1. journey 區段內每個列表項目都必須符合 `- [J<n>] 描述`，不合格式即為 profile 的 invalid 值。
2. ID 必須唯一 —— 重複時單一行 `J1: PASS` 會同時滿足多條，一次驗證兌換多條覆蓋宣稱。
3. browser evidence 中每個 required ID 必須**恰好一筆**結果。`J1: PASS` 與 `J1: FAIL`
   並存時 `re.search` 只取第一筆而放行；矛盾的結果不是「其中一筆有效」，
   是這份 evidence 不可信。

能力邊界不變：這驗證的是**宣稱**，不是那些 journey 真的被執行過。要擋「寫了
PASS 但沒跑」，需要 Playwright test id 與 journey id 對應、從 report 反查 ——
那是下一層工程，rc.5 明確不做。

## 測試 fixture 必須是真的 git repository（rc.5）

被批准的內容要綁到 worktree / index / HEAD，而 Starter 本來就要求 git
（bootstrap 會安裝 hook）。一個沒有 git 的 fixture 模擬的是真實安裝不會存在的狀態，
它讓所有依賴 Git 歷史的判準退化成「取不到就跳過」—— **那是最糟的一種綠燈**。

同理，`git commit` 不加 pathspec 會提交**整個 index**。測試若要「掉包被批准內容、
但把產品變更留在 staged」，必須寫成 `git commit -m msg -- <paths>`；
少了 pathspec，待驗的產品檔案會被一起 commit 掉，gate 沒東西可看，測試假綠。

## Release acceptance：在採用者形狀上跑完整條生命週期（rc.5）

`DEVELOPING.md` 說明本 repo 是 Starter **原始碼**，不是採用 Starter 的專案 ——
它刻意不設 `core.hooksPath`，`STATE.md` 是出貨模板。所以**對 Starter 自己的歷史跑
runtime audit 預期會失敗**，那不是缺陷；採用者只應從 sanctioned installation
baseline 或 PR merge-base 起算。

但這留下一個缺口：這條工作流從未在真實採用者形狀中被整體走完過。e2e 測試模擬過
片段，那是模擬 —— bootstrap、真實的 git hook、TTY 批准、對整段合法歷史跑伺服器端
稽核，這四件事只有在 `workflow/bin/acceptance.py` 裡才會同時發生。

它涵蓋安裝 → TTY 批准 ×2 → 產品 commit → 驗證 → 封存 → 第二輪 → 伺服器稽核，
並且**正反兩向**：合法歷史必須通過，`--no-verify` 繞過本機的未授權 commit 必須被擋。
只有正向的話，那個綠燈證明不了任何事。

### 它第一次跑就抓到的兩件事

兩件都是「本機測試涵蓋不到、只有真的走一遍才會撞到」的類型。

**1. submit-for-review 是內容必須進 HEAD 的最後時機。**
`PROJECT-PROFILE.md` 在 DISCOVERY/SPECIFICATION 是 AI-writable，一進 SPEC_REVIEW
就變成唯讀的 Control Plane。而 `approve-spec` 要求被批准的內容已在 HEAD。
兩者相加：沒有在送審前 commit 的人會在 SPEC_REVIEW **卡死** —— approve-spec 說
「內容不在 HEAD」，一般 commit 說「Control Plane 變更不可透過一般 commit」，
兩則訊息都不指向真正的原因（順序錯了）。

因此 `submit-for-review` 現在自己檢查這件事並給出可操作的指示（exit 37）。
**失敗要發生在能修的地方**，不是在已經來不及的地方。

**2. `Core verification policy: custom` 對 greenfield 是雞生蛋。**
`verify.sh` 的 custom 分支**完全忽略 `plan_mode`** —— `auto` 有 pre-commit 與 full
兩套計畫，custom 只有一條指令，在兩種模式下都跑。於是從 profile 宣告它那一刻起，
每一個 commit（含 Control Plane transition）都要先讓它通過；而驗證腳本本身是產品
程式碼，ENGINEERING 之前根本不能 commit。

已知邊界，rc.5 不改行為，但採用者必須知道：**custom 指令要能在「還沒有任何產品
程式碼」的 repo 上通過**，或者等到 ENGINEERING 之後再把 policy 改成 custom
（那要走 SPECIFICATION 重新 review）。Brownfield 不受影響 —— 它的驗證入口本來就
已經在 repo 裡。

## API 專案的端點驗證（rc.5）

`AGENTS.md` 與 `BROWSER-VERIFICATION.md` 都寫著「非 Web 專案標記 NOT APPLICABLE
只代表不需要瀏覽器，不代表不需要真的跑一次」—— 在此之前那是一句**沒有機制的
規範**：一個 API 專案只要任一 automated check 通過（lint 也算）就能 archive，
沒有任何東西證明端點被實際打過。

這與 MERGE-PROTECTION 那次是同一個錯誤：在文件裡寫下 normative 宣稱，卻沒有
對應的 gate。**規範與機制必須成對出現，否則規範只是願望。**

因此 `Type: API` 現在：

1. 與 WEB 一樣**必須列出 critical user journeys**（納入被批准的 profile digest）
2. 必須提供 `workflow/evidence/<change>/api.md`，每條 journey 恰好一行：

   ```
   J1: success=PASS validation=PASS authorization=PASS
   ```

3. 三類情境缺一不可。`not-applicable` 是合法值 —— 確實沒有權限層的端點不該被
   逼著造假，但**必須明示**，不能省略。

**權限那一類最容易被跳過，也最容易出事。** 前端把選單做成下拉式，不代表後端擋得住
手動送出的非法值；前端把按鈕藏起來，不代表後端擋得住直接打 API。

CLI / LIBRARY 等沒有對外流程的類型不適用 —— 強制它們填 journeys 等於製造假資料。

### 能力邊界

與 Browser Gate 完全相同：驗證的是**宣稱涵蓋範圍**，不是那些 request 真的被送出過。
要擋「寫了 PASS 但沒跑」，需要從測試報告反查，那是下一層工程，rc.5 明確不做。


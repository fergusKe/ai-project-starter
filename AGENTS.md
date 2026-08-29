# AGENTS.md

本檔是此 Repository 對 AI Coding Agent 的唯一 normative workflow 規範。其他文件衝突時以本檔為準。

## Source of Truth
1. 已批准 OpenSpec specs
2. ADR
3. CONTEXT.md
4. OpenSpec config/design/tasks
5. Superpowers implementation plan
6. chat/notes

OpenSpec 管「要做什麼」；Superpowers 管「怎麼可靠地做出來」。

新增或修改 `.claude/skills/**` 時，遵守 `docs/skill-authoring.md`。

## 與其他 Agent 框架的邊界

適用於 Superpowers 或任何自帶需求塑形流程的框架。**依能力分類，不依框架名稱** ——
名稱與版本會變，能力不會。核心原則：**可以借用另一套框架的方法，不能把產品真相的
所有權借出去。**

1. **需求所有權（所有階段皆適用）**
   OpenSpec 獨占產品意圖、可觀察行為、acceptance criteria、範圍與產品限制。
   任何技能或框架產出的設計文件都不得成為平行或替代的產品 Spec。

2. **階段能力**
   ENGINEERING 之前可以使用 read-only investigation、systematic debugging、
   hypothesis testing 等調查方法 —— 這些在 brownfield 的 DISCOVERY 特別有價值
   （重現既有 bug、查清資料流、判斷目前行為算不算需求）。但產出只能是事實、
   evidence 或 OpenSpec 的輸入；**不得**建立獨立的產品設計、寫產品程式碼，
   或以另一套 brainstorming workflow 取代 `prompts/01`–`03` 與 OpenSpec。
   若某個 skill 堅持產生它自己的 normative design document，該階段就不得使用它。

3. **衍生計畫**
   implementation plan 只能在需求已批准、implementation 已允許之後產生，
   且必須由 OpenSpec `tasks.md` 衍生。它只能增加檔案定位、工程拆分、順序、
   測試步驟與除錯策略，**不得**新增產品行為、acceptance criteria 或範圍。
   衍生計畫不進 Control Plane，但必須標頭自證：

   ```
   Non-normative: true
   Derived from: openspec/changes/<change>/tasks.md
   Source digest: <sha256>
   ```

   OpenSpec 一旦變動，舊 plan 即視為 stale。

4. **發現缺漏時的判準**
   若新決策會改變可觀察行為、acceptance criteria、安全／資料處理、相容性或
   批准範圍 → **停止受影響的實作**，回 OpenSpec 修訂並重新 review。
   純工程實作選擇若仍完全落在已批准限制內，記入衍生 plan 後可以繼續。
   （是「受影響的實作」，不是「全部工程」；彼此獨立的 task 不必一起停。）

## Session 啟動
讀 AGENTS.md → workflow/STATE.md → PROJECT-PROFILE.md → CONTEXT.md → active OpenSpec change。執行 `python3 workflow/bin/workflow_transition.py status`。除非使用者指定其他語言，對人類使用繁體中文。

## Project Mode
GREENFIELD：從需求探索開始。
BROWNFIELD：先掃描既有 stack、architecture、scripts、tests、CI 與 conventions，補 Context/Profile；既有程式碼不必反向補完整 OpenSpec，只對新的 change 建規格。

## Workflow
DISCOVERY → SPECIFICATION → SPEC_REVIEW → TEST_DESIGN → ENGINEERING → VERIFICATION → ARCHIVE。STATE 只能由 Transition CLI 更新。
Human Approval：approve-spec / approve-tests。Machine Verified：set-mode / start-change / submit-for-review / start-engineering / verification-pass / archive。revert-to-spec 是無摩擦收緊，但 ARCHIVE 後必須開新 change。

## Authorization
任何 AI 能讀到或自己產出的 token、環境變數、repo 內秘密都不能當 Human Approval 憑證。本機 Human Approval 使用經 doctor 實測的 TTY execution boundary；它不是 cryptographic identity。

## Control Plane
Control Plane 定義只在 `workflow/bin/workflow_state.py`。PreToolUse 是快速回饋層、Bash 可繞過；tracked `.githooks/pre-commit` 是 Repository enforcement；團隊情境以 PR review/branch protection/CODEOWNERS 作外部 authorization。Control Plane 維護只能使用 TTY-only `control-plane-commit`，不得 `--no-verify`。

`PROJECT-PROFILE.md` 只在 DISCOVERY/SPECIFICATION 可調整，之後唯讀。`workflow/evidence/<change>/core/**` 是 machine-owned；AI 只能寫 `browser.md`。

## Testing / Data Safety
TEST_DESIGN 可寫 `workflow/test-cases/**`。先建立 requirement→test traceability；優先 unit/integration，Playwright 只覆蓋 critical journeys。Tests 不得碰 production data；destructive DB setup 前必須證明 test-only，參考 `templates/test-db-safety.md`。

## Web Verification
Web policy 必須明確；UNKNOWN/auto 未決 fail-closed。WEB_APP 無法用 `no` 關閉 Browser Gate。06 可反覆驗證並寫 browser.md；07 只消費 evidence。操作細節見 `workflow/BROWSER-VERIFICATION.md`。

## Git / CI
Transition CLI 不自動 commit；每次 transition 後先獨立提交 STATE+state-log。不得靜默覆蓋既有 Husky/Lefthook/pre-commit/core.hooksPath；依 `workflow/CI.md` 建立實際 CI。

## 完成
只有 approved spec/test design、implementation、lint/typecheck/tests/build、Web Gate（適用時）、machine core evidence、browser evidence 與 OpenSpec compliance 全部通過才能 archive。散文式「已完成」不算 evidence。

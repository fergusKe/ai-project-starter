# Project Profile

此檔案是 Gate 與 Verification 的專案級輸入。

## 值的三種狀態

**未知、候選、已批准是三件不同的事**，不要混為一談：

| 狀態 | 寫法 | 什麼時候 |
|---|---|---|
| 未知／尚未決定 | `UNKNOWN`（`Web verification required` 用 `auto`） | DISCOVERY、SPECIFICATION 都可以停在這裡 |
| 候選 | 仍寫 `UNKNOWN`，候選值與理由寫進 ADR（`Status: Proposed`） | AI 可以提，但**不得在本檔宣稱為定案** |
| 已批准 | 具體值 | 由 `approve-spec` 一併定案 |

所以「未知資訊不要猜測」與「不急著選技術」並不衝突：**DISCOVERY 不必定案，
SPECIFICATION 可以提出方案，SPEC_REVIEW 才向人類收取決策。**
沒有依據時就留 `UNKNOWN`，把問題寫進 ADR 與 OpenSpec 的 open questions，
不要為了讓 Gate 過而編一個值。

## 什麼時候必須解析完成

`approve-spec` 會在人類確認**之前**檢查下列欄位是否仍為未決，未決就拒絕（exit 44）：

`Type`、`Web verification required`、`Primary stack`、`Package manager`、
`Monorepo`、`CI provider`、`Test database strategy`

判準是「會影響 Gate、驗證契約、安全政策或工程行為」。這些值會列在 TTY 確認畫面上，
人類批准 spec 時同時批准它們，audit log 記錄 profile digest。

**定案之後要改，必須回 SPECIFICATION 修訂 ADR/OpenSpec 並重新 review**，
不是原地改這個檔案。原因：`UNKNOWN → 具體值` 不是單調收緊 ——
`Test database strategy: UNKNOWN → NOT_APPLICABLE` 其實是放寬，
machine 只能證明格式與來源，不能授權「選擇」。

Mode: UNSET
# GREENFIELD | BROWNFIELD

Type: UNKNOWN
# WEB_APP | API | CLI | LIBRARY | MOBILE | OTHER

Web verification required: auto
# auto | yes | no
# Type=WEB_APP 時，即使填 no，Web Gate 仍會啟用。
# 明確非 Web（API/CLI/LIBRARY 等）請填 no；auto 表示未決並 fail-closed。

Core verification policy: auto
# auto | custom | not-applicable
# auto           ：執行 Starter 能辨識的 checks；零 runnable checks 時失敗。
# custom         ：改用專案自己的驗證入口，必須真的執行並記錄結果。
# not-applicable ：純文件或刻意沒有 automated verification 的 repo；
#                  必須填寫非空的 Verification exception reason，且不會標記為 PASS。

Custom verification command: none
Verification exception reason: none

## Critical user journeys
- 尚未定義

## Repository
Primary stack: UNKNOWN
Package manager: UNKNOWN
Monorepo: UNKNOWN
CI provider: UNKNOWN

## Testing
Test database strategy: UNKNOWN

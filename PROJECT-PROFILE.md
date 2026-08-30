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

另外三個欄位有預設值、因此永遠「已解析」，但它們**決定驗證契約**，所以一樣會
列在 TTY 畫面上並納入 digest：

`Core verification policy`、`Custom verification command`、`Verification exception reason`

沒有這一條的話，`Core verification policy: not-applicable` 可以在 SPECIFICATION
階段悄悄寫進來，七個必填欄位全部通過，人類看到的畫面完全不提 verification 已被
豁免，之後 zero-check 的 `NOT_APPLICABLE` 就依這個從未被明示批准的政策通過。

判準是「會影響 Gate、驗證契約、安全政策或工程行為」。這些值會列在 TTY 確認畫面上，
人類批准 spec 時同時批准它們，audit log 記錄 profile digest。

## 打錯字不是未決，是已決定

有正式 vocabulary 的欄位（`Type`、`Web verification required`、`Monorepo`、
`Test database strategy`、`Core verification policy`）會做列舉檢查，不合法時
`approve-spec` 以 exit 44 拒絕，並且與「尚未填寫」分開報。

原因是實測出來的：`Type: WEB_AP`（少一個字母）原本會被當成已解析，而 Browser Gate
因為它不等於 `WEB_APP` 判定為非 Web —— **一個 typo 就把 Gate 靜默關掉**。
沒有 vocabulary 的欄位（`Primary stack`、`Package manager`、`CI provider`）維持
自由文字，因為它們沒有可窮舉的正確答案。

## 批准綁的是內容，不是旗標

人類批准當下的 profile digest 會寫進 `workflow/STATE.md` 的
`Approved profile digest`。`start-engineering` 會重新計算並比對，不一致就拒絕。

兩個視窗因此被關掉：`approve-spec` 的 TTY 等待期間（人類速度，以分鐘計）有人換掉
檔案；以及 approve-spec 與 start-engineering 之間的任意長時間。

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
<!-- WEB 專案必須改成具穩定 ID 的形式，例如：
- [J1] 訪客可以瀏覽商品並加入購物車
- [J2] 已登入使用者可以完成結帳與付款
ID 一旦指派就不要重用或重編號 —— evidence 以 ID 對應結果。
journeys 屬於被批准內容：它決定驗證的範圍，改動會使批准失效。

WEB 專案以 browser evidence 對應（`J1: PASS`）。
**API 專案同樣必須列出**，以 api evidence 對應，每條要有三類情境：
`J1: success=PASS validation=PASS authorization=PASS`。
CLI / LIBRARY 等沒有對外流程的專案維持「尚未定義」即可。 -->

## Repository
Primary stack: UNKNOWN
Package manager: UNKNOWN
Monorepo: UNKNOWN
CI provider: UNKNOWN

## Testing
Test database strategy: UNKNOWN
# UNKNOWN | not-applicable | separate-database | transaction-rollback
#         | ephemeral-container | schema-per-worker | other: <描述>
# not-applicable 表示這個 repo 沒有資料庫。清單以外的隔離手法請用
# `other: <描述>`，描述不得為空。可執行形狀的最低要求見 templates/test-db-safety.md。

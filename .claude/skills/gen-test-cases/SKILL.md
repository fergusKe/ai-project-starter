---
name: gen-test-cases
description: 當使用者提到「寫測試案例」、「test design」、「這個 change 要測什麼」、「產生測試計畫」時觸發，或進入 TEST_DESIGN 階段時使用；將已批准的 OpenSpec requirements 轉為可追溯的測試案例。本 skill 只產生文件，不寫測試程式碼。
---

# Generate Test Cases from OpenSpec

## 前置檢查

| 前提 | 怎麼確認 | 不成立時說什麼 |
|---|---|---|
| Phase 是 TEST_DESIGN | `workflow_transition.py status` | 「目前在 `<phase>`。測試案例要在 spec 批准之後設計，否則會對著會變的規格寫。」 |
| Spec 已批准 | 同上的 `Spec approved: yes` | 「spec 尚未批准，先完成 `approve-spec`。」 |
| requirements 可讀 | `openspec/changes/<change>/specs/` 有內容 | 「找不到 specs，無從轉換。」 |

本 skill **只產生 `workflow/test-cases/<change>.md`，不寫測試程式碼、不執行測試**。

## 流程

1. 讀 `references/test-case-template.md`。**它是唯一事實來源**。
2. **掃描既有測試**：讀出所有 `describe` / `it` / `test`（或 `def test_`）的描述，
   逐一標記「已涵蓋 / 需整併 / 不相關」，填入「既有測試盤點」。
3. 逐條 requirement 產生案例，依測試類型分組。
4. 產生追溯表與涵蓋檢查。
5. 發現規格缺口或矛盾 → **停止並回到 OpenSpec**，不要自行補假設。
6. 產出不保留註解。

## 規則

| 規則 | 理由 |
|---|---|
| 既有測試不符規則時**一併整併，不另開新檔** | 同一行為兩套測試，改規格時必然漏改一邊 |
| 第二層分組必須是測試類型，與程式的 `describe` 結構鏡射 | 文件與程式對不上就沒人維護文件 |
| `it()` 描述直接沿用本檔原文，不翻譯、不改名 | 名稱漂移就斷了追溯 |
| 勾選狀態只能在實際通過後更新 | 未通過就打勾等於偽造 |
| 勾選**不是 gate 憑證** | Gate 只採信 `workflow/evidence/` 的機器 evidence |
| 修 bug 的迴歸案例必須能證明「還原修正會變紅」 | 沒紅過的測試不能證明它守住了什麼 |

## 範例

| requirement 片段 | 產生的案例 | 判斷依據 |
|---|---|---|
| 「成員可以邀請其他人加入」 | `[ ] TC-001【integration】成員邀請新成員後，被邀請者出現在待接受清單` | 跨 API 與 DB → integration，不是 unit |
| 「只有管理者可以移除成員」 | `[ ] TC-002【integration】一般成員呼叫移除 API 得到 403` | 權限規則必須有**負向**案例，不能只測 happy path |
| 「邀請連結 7 天後失效」 | `[ ] TC-003【unit】第 7 天整點的邀請視為失效` | 邊界值，用 unit 直接測時間判斷函式 |
| spec 沒說「重複邀請同一人會怎樣」 | 不產生案例，停下來回 OpenSpec | 規格缺口不得由測試設計自行決定 |

## 邊界情況處理

- **既有測試與新 requirement 衝突**（舊測試斷言的行為已被新 spec 推翻）→ 在盤點表標為「需整併」
  並明確指出衝突點，**不要**同時保留兩份互相矛盾的斷言。
- **requirement 太抽象無法轉成可觀察結果**（例如「效能要好」）→ 停下來回 OpenSpec 要求量化，
  不要自己定一個門檻。
- **同一行為已有測試但描述不同** → 沿用既有描述並在盤點表註明，
  **不要**為了符合本檔格式而改寫既有測試的名稱造成 diff 噪音。
- **change 只改文件或設定** → 「案例」節可以只有 manual 類型，
  但涵蓋檢查每一項仍要填「不適用」與理由，不要整節刪除。
- **使用者要求「先把測試都標成通過」** → 拒絕。勾選只能在實際通過後更新，
  而且勾選本身不構成 gate 憑證。

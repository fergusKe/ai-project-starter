<!--
本檔是 workflow/test-cases/<change>.md 的唯一事實來源。
填寫規則寫在 HTML 註解裡；產出時**移除所有註解**。

勾選狀態的規則（重要）：
- `[ ]` → `[x]` **只能在該案例實際通過之後更新**。
- 這個勾**不是 gate 憑證**。Gate 只採信 workflow/evidence/<change>/ 裡由
  verify.sh 產生的機器 evidence。AI 勾選的框僅供人類閱讀與追蹤，
  不得用來主張 VERIFICATION 通過。
-->

# 測試案例：<change>

OpenSpec change：`openspec/changes/<change>/`

## 既有測試盤點

<!--
BROWNFIELD 必填；GREENFIELD 若專案已有測試也必填。
掃描既有測試檔，列出所有 describe / it / test 的描述，逐一標記：

| 既有描述 | 檔案 | 處置 |
|---|---|---|
| ... | ... | 已涵蓋 / 需整併 / 不相關 |

**規則：既有測試結構不符本檔規則時，一併整併重構，不另開新檔。**
另開新檔會造成同一行為有兩套測試，日後改規格時必然漏改一邊。
-->

## 案例

<!--
每個 material requirement 至少一案。第二層分組必須是**測試類型**
（unit / integration / contract / E2E / manual），與程式裡的 describe 結構鏡射。

每個 it() 的描述**直接使用本檔原文，不翻譯、不重新命名** ——
名稱一旦漂移，追溯就斷了。
-->

### [ ] TC-001 【unit】<一句話說明這個案例驗什麼>

- **OpenSpec**：<requirement / scenario 引用>
- **Given**：<前置狀態>
- **When**：<觸發動作>
- **Then**：<可觀察的預期結果>
- **Notes**：<setup、fixture、需要的權限>

## 追溯表

<!--
requirement → test case(s)。每個 material requirement 都必須出現在左欄；
沒有對應案例的 requirement 要標記為未涵蓋並說明原因。
-->

| Requirement | 案例 |
|---|---|
| ... | TC-001, TC-002 |

## 涵蓋檢查

<!-- 逐項確認，沒有適用就寫「不適用」與理由，不要留空。 -->

- 權限與授權：
- 負向與錯誤路徑：
- 邊界值：
- 並行與順序：
- 資料遷移：
- 迴歸（修 bug 時必填，且必須證明還原修正會變紅）：

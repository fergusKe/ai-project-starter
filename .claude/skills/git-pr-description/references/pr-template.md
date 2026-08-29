<!--
本檔是 PR 說明的唯一事實來源。填寫規則寫在 HTML 註解裡：渲染時看不到，但 AI 讀得到，
規則與版型放在同一個檔案才不會走鐘。

產出時**移除所有註解**，只留填好的內容。
用不到的區塊整段刪除，不要留下「無」或空標題。

全域禁止：
- 禁止 Markdown 連結格式 `[文字](路徑)`
- 禁止任何 URI scheme（file://、cci:、vscode://）
  兩者都會產生在他人機器上無效的本機路徑。要指路就寫純文字相對路徑。
-->

## 為什麼

<!--
這個 PR 解決什麼問題。寫給「三個月後來查為什麼要這樣做」的人看。
必須引用 active OpenSpec change：openspec/changes/<change>/
不要重述 diff 做了什麼 —— 那是下一節的事。
-->

## 修改內容

<!--
依模組分組，一行一項。說明「改了什麼」與「影響到誰」。
不要逐檔列出；review 者看得到檔案清單，看不到的是分組與意圖。
-->

## 📦 切換 branch 後需執行的指令

<!--
**產生條件**：下列任一命中就必須有本區塊，否則整段刪除。

- lockfile 或 package.json / pyproject.toml 的相依變動
- codegen 產物不進版控（prisma generate、protobuf、GraphQL codegen）
- 新增 DB migration
- 新增或改名環境變數
- docker / infra 設定變更
- 本 Starter 專屬：新增或修改 workflow/bin/** 的安裝腳本
  （bootstrap.sh、setup-git-hooks.sh、setup-web-verification.sh）

**格式要求**：
- 所有指令放在**同一個 bash code block**，依執行順序排列
- 每一條都用 # 註明原因
- 區塊下方補三件事：漏跑會看到的**具體錯誤訊息**、明確「不需要跑」的指令、
  切回舊 branch 是否需要額外動作
- 環境變數只列 key 與範例值的位置，**絕不寫出真實 secret**
-->

```bash
# <原因>
<指令>
```

**漏跑的症狀**：<!-- 具體錯誤訊息，不是「可能會壞」 -->

**不需要跑**：<!-- 明講哪些常見指令這次不用跑，省下 review 者的猶豫 -->

**切回舊 branch**：<!-- 需不需要額外動作 -->

## 測試與驗證

<!--
引用既有 artifact，**不要在 PR 裡重寫一份測試規格**：
- 測試案例：workflow/test-cases/<change>.md
- 執行 evidence：workflow/evidence/<change>/
- Web 專案另附 workflow/evidence/<change>/browser.md

只陳述 evidence 檔案裡真的有的結果。沒有檔案就寫「尚未執行」，
**不得**宣稱通過。
-->

## 授權與安全影響

<!--
權限模型、資料存取範圍、Control Plane 檔案是否變動。
沒有影響就寫「無」，不要刪除本節 —— review 者需要看到你確實想過。
-->

## 風險與回滾

<!--
已知風險、回滾方式、需要人工介入的步驟。
有 DB migration 時必須說明能不能回滾。
-->

## 已知限制與後續

<!-- 這個 PR 刻意不做的事，以及它們追蹤在哪裡。 -->

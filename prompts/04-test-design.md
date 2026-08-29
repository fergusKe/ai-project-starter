# Test Design Prompt

根據已批准的 OpenSpec specs 建立 requirement → verification traceability。

將案例分類為 Unit、Integration、E2E/Playwright、Browser Inspection。Critical user journey 必須有 E2E；純 business logic 優先 Unit/Integration。

不要為了追求 E2E 覆蓋率把所有邏輯都塞進 Playwright。


Test Design 經人類確認後，請由**人類**執行：
```bash
python3 workflow/bin/workflow_transition.py approve-tests <change>
```
完成後再由 AI 執行 `start-engineering`。

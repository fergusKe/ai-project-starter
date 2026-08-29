# OpenSpec Review Prompt

請審查目前 OpenSpec change，對照完整 Discovery context。

特別檢查：遺漏需求、隱藏假設、negative requirements、權限、edge cases、錯誤行為、數值限制與預設值、ordering、concurrency、data ownership、security、migration、compatibility、observability、testability。

列出 blocking issues 與建議修正。不要實作。


Review 通過後，請由**人類**在互動終端機執行：
```bash
python3 workflow/bin/workflow_transition.py approve-spec <change>
```

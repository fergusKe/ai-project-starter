# 06 — Browser Verification

先執行 `python3 workflow/bin/workflow_transition.py status`。

- WEB：執行本檔。
- NON_WEB：由 `verify.sh --full` 機器產生 NOT APPLICABLE。
- UNRESOLVED：停止並先完成 PROJECT-PROFILE。

Web 專案：
1. 先執行一次 `bash workflow/bin/verify.sh --full`，取得成功的 `workflow/evidence/<change>/core/<timestamp>.md`。
2. 執行 Playwright critical journeys，保留實際 report artifact。
3. 使用 Chrome DevTools MCP 檢查 console/network/runtime/session 等。
4. 寫 `workflow/evidence/<change>/browser.md`，必須包含：

```text
# Browser Verification Evidence
Core evidence: 20260828T120000123456Z.md
Playwright report: playwright-report/index.html
Chrome DevTools MCP: console/network checked; no blocking errors
```

`core/**` 是 machine-owned，AI 不得直接寫；`browser.md` 是 Browser Verification writer。

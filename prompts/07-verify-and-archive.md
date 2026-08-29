# 07 — Final Verification & Archive

不要相信先前任何「已完成」聲明。先執行：

```bash
python3 workflow/bin/workflow_transition.py verification-pass <change>
```

此指令自己跑 `verify.sh --full`，檢查最新 core evidence 與 browser evidence；Web 專案拒絕 NOT APPLICABLE，UNKNOWN/auto fail-closed。成功後再執行 `archive`。不接受 skip/force/already-verified 類參數。

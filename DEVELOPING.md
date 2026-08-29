# 開發本 Starter

**這個 repo 是 Starter 的原始碼，不是一個「使用 Starter 的專案」。** 兩者的規則不同。

## 不要在這個 repo 執行 bootstrap

`bash workflow/bin/bootstrap.sh` 會設定 `core.hooksPath=.githooks`，把 Starter 的
runtime gate 套用到**它自己的模板檔案**上。後果是 `workflow/STATE.md`、`.githooks/**`、
`.claude/settings.json` 全部變成受保護的 Control Plane —— 而編輯這些檔案**正是**
開發 Starter 的工作內容，於是你會被自己的 gate 擋住。

這個 repo 刻意**不設** `core.hooksPath`。`git config --get core.hooksPath` 應該是空的。

本 repo 裡的 `workflow/STATE.md` 是**出貨模板**（`Phase: DISCOVERY`），
不是本專案的實際工作狀態。不要用 `workflow_transition.py` 去推進它。

## 要測 Starter 的行為，複製到別處測

```bash
W=$(mktemp -d)
tar cf - $(find . -type f -not -path './.git/*' -not -name '*.pyc' -not -path '*__pycache__*') | (cd "$W" && tar xf -)
cd "$W" && git init -q -b main && bash workflow/bin/bootstrap.sh
```

回歸測試已經是這個形狀（每條測試各自建立臨時 repo），所以正常情況下直接跑測試即可。

## 測試

```bash
python3 -m unittest discover -s workflow/tests -t .
```

沒有 TTY 的環境（CI、sandbox、agent harness）會有兩條必然失敗，那是設計值：

- `test_actor_prompt_is_distinguishable_from_change_prompt`
- `test_wrong_input_names_both_values_in_error`

兩條都以真實 pty 驗證 Human Approval 的提示，需要 controlling terminal。

## 修改之後要做什麼

1. **每個修正都要有回歸測試，而且要證明它會紅。** 還原修正 → 測試變紅 → 復原修正 → 變綠。
   沒紅過的測試不能證明它守住了什麼。
2. **突變測試要跑完整套件**，不要只跑相關的那幾條。深度防禦會讓各層互相遮蔽 ——
   只看最終結果的斷言，可能在某一層被移除時仍然全綠。每一層都需要一條「只有該層適用」
   的隔離測試。
3. 新增 skill 時遵守 `docs/skill-authoring.md`。
4. 新增檔案若要隨 Starter 出貨，必須在 `workflow/SHIPPED-MANIFEST.txt` 的根目錄涵蓋範圍內。
   本檔（`DEVELOPING.md`）刻意不在其中。

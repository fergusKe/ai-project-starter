#!/usr/bin/env python3
"""Claude Code PreToolUse guard for destructive shell/git commands.

This is a defense-in-depth layer. Project permissions block common direct forms;
this hook also catches wrapped/absolute-path variants. It denies agent execution
and leaves any intentional destructive action to explicit human execution.
"""
import json
import re
import sys

PRE = r"(?:^|[\s;&|()`{])"
PATH = r"(?:[/\w.-]+/)?"
RULES = [
    ("recursive/forced rm", rf"{PRE}{PATH}rm\b[^\n;&|]*?(?:-{{1,2}}[\w-]*[rRf]|--recursive|--force|--no-preserve-root)"),
    ("sudo elevation", rf"{PRE}sudo\b"),
    ("dd disk write", rf"{PRE}{PATH}dd\b"),
    ("filesystem formatting", rf"{PRE}{PATH}mkfs(?:\.\w+)?\b"),
    ("disk erase", rf"{PRE}{PATH}diskutil\s+erase\w*"),
    ("chmod 777", rf"{PRE}{PATH}chmod\s+(?:-R\s+)?0?777\b"),
    ("git reset --hard", r"\bgit\s+reset\s+--hard\b"),
    ("git force push", r"\bgit\s+push\b[^\n;&|]*?(?:--force(?:-with-lease)?\b|\s-f\b)"),
    ("git clean -f", r"\bgit\s+clean\b[^\n;&|]*?-\w*f"),
    ("git branch -D", r"\bgit\s+branch\b[^\n;&|]*?-\w*D"),
    ("shutdown/reboot", rf"{PRE}{PATH}(?:shutdown|reboot|halt|poweroff)\b"),
    ("truncate file", rf"{PRE}{PATH}truncate\b"),
    ("shell file truncation", r":\s*>\s*\S"),
    ("find -delete", r"\bfind\b[^\n]*\s-delete\b"),
]
COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in RULES]


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    if data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command", "")
    if not command:
        return
    normalized = re.sub(r"[\t\n\r]+", " ", command)

    for name, regex in COMPILED:
        if regex.search(normalized):
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked by repository safety policy: {name}. "
                        "Destructive operations must be explicitly performed/authorized by the human."
                    ),
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "=== Web verification setup ==="

if [[ ! -f package.json ]]; then
  echo "! package.json not found. Playwright setup is currently provided for Node-based web projects."
  echo "  For non-Node web stacks, keep the browser policy and configure a project-specific runner."
  exit 0
fi

PM=npm
[[ -f pnpm-lock.yaml ]] && command -v pnpm >/dev/null 2>&1 && PM=pnpm
[[ -f yarn.lock ]] && command -v yarn >/dev/null 2>&1 && PM=yarn
[[ -f bun.lockb || -f bun.lock ]] && command -v bun >/dev/null 2>&1 && PM=bun

if node -e 'const p=require("./package.json"); const d={...(p.dependencies||{}),...(p.devDependencies||{})}; process.exit(d["@playwright/test"]?0:1)' >/dev/null 2>&1; then
  echo "✓ @playwright/test already installed"
else
  echo "! Playwright is not installed."
  echo "  Recommended official scaffold: npm init playwright@latest"
  echo "  Or install into the existing project with your package manager."
fi

if command -v claude >/dev/null 2>&1; then
  if claude mcp list 2>/dev/null | grep -qi 'chrome-devtools'; then
    echo "✓ Chrome DevTools MCP appears configured for Claude Code"
  else
    echo "! Chrome DevTools MCP not detected."
    echo "  Recommended: claude mcp add chrome-devtools --scope user npx chrome-devtools-mcp@latest"
  fi
else
  echo "! Claude Code not detected; configure Chrome DevTools MCP in the coding agent you use."
fi

echo
cat <<'MSG'
For web projects, browser verification is a completion gate:
  Playwright critical-flow E2E + Chrome DevTools live inspection.
See workflow/BROWSER-VERIFICATION.md.
MSG

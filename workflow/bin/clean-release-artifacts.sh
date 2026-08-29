#!/usr/bin/env bash
set -euo pipefail

# Release packaging must not ship host-generated caches/metadata.
required=(
  workflow/SHIPPED-MANIFEST.txt
  workflow/bin/workflow_state.py
)
for path in "${required[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "✗ 不在 Starter root（缺少 ${path}）；拒絕清理" >&2
    exit 2
  fi
done

find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '.DS_Store' \) -delete

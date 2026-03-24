#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

/usr/bin/env python3 "$SCRIPT_DIR/job_digest.py" --send-email

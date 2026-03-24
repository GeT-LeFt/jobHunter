#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NGINX_HTML_DIR="${JOBHUNTER_NGINX_HTML_DIR:-}"
cd "$SCRIPT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

if [[ -n "${JOBDIGEST_SMTP_HOST:-}" && -n "${JOBDIGEST_SMTP_USER:-}" && -n "${JOBDIGEST_SMTP_PASSWORD:-}" && -n "${JOBDIGEST_MAIL_TO:-}" ]]; then
  /usr/bin/env python3 "$SCRIPT_DIR/job_digest.py" --send-email
else
  /usr/bin/env python3 "$SCRIPT_DIR/job_digest.py"
fi

if [[ -n "$NGINX_HTML_DIR" && -d "$NGINX_HTML_DIR" ]]; then
  /usr/bin/rsync -a --delete "$SCRIPT_DIR/web/" "$NGINX_HTML_DIR/"
fi

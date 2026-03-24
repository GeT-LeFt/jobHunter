#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "web" / "data"
LATEST_JSON = DATA_DIR / "latest.json"
META_JSON = DATA_DIR / "meta.json"
RUN_SCRIPT = BASE_DIR / "run_job_digest.sh"


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def filter_jobs(jobs: list[dict[str, Any]], params: dict[str, list[str]]) -> list[dict[str, Any]]:
    region = params.get("region", ["all"])[0]
    category = params.get("category", ["all"])[0]
    query = params.get("q", [""])[0].strip().lower()
    limit_raw = params.get("limit", ["0"])[0]

    try:
        limit = max(0, int(limit_raw))
    except ValueError:
        limit = 0

    filtered: list[dict[str, Any]] = []
    for job in jobs:
        if region != "all" and job.get("region") != region:
            continue
        if category != "all" and job.get("category") != category:
            continue
        if query:
            haystack = " ".join(
                [
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("summary", ""),
                    job.get("category", ""),
                    job.get("region", ""),
                    " ".join(job.get("tags", [])),
                ]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(job)

    if limit:
        return filtered[:limit]
    return filtered


class JobHunterHandler(BaseHTTPRequestHandler):
    server_version = "JobHunterAPI/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/jobhunter-api/health":
            self.respond_json({"ok": True})
            return

        if parsed.path == "/jobhunter-api/meta":
            meta = load_json(META_JSON)
            if meta is None:
                self.respond_json({"error": "meta not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.respond_json(meta)
            return

        if parsed.path == "/jobhunter-api/latest":
            jobs = load_json(LATEST_JSON)
            if jobs is None:
                self.respond_json({"error": "jobs not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.respond_json({"items": jobs, "count": len(jobs)})
            return

        if parsed.path == "/jobhunter-api/jobs":
            jobs = load_json(LATEST_JSON)
            meta = load_json(META_JSON) or {}
            if jobs is None:
                self.respond_json({"error": "jobs not found"}, status=HTTPStatus.NOT_FOUND)
                return
            filtered = filter_jobs(jobs, params)
            self.respond_json(
                {
                    "items": filtered,
                    "count": len(filtered),
                    "generated_at": meta.get("generated_at"),
                    "generated_at_display": meta.get("generated_at_display"),
                    "timezone": meta.get("timezone"),
                }
            )
            return

        self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/jobhunter-api/refresh":
            try:
                result = subprocess.run(
                    ["/bin/zsh", str(RUN_SCRIPT)],
                    cwd=str(BASE_DIR),
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=True,
                )
                self.respond_json(
                    {
                        "ok": True,
                        "stdout": result.stdout[-1200:],
                    }
                )
            except subprocess.CalledProcessError as exc:
                self.respond_json(
                    {
                        "ok": False,
                        "stdout": exc.stdout[-1200:] if exc.stdout else "",
                        "stderr": exc.stderr[-1200:] if exc.stderr else "",
                    },
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            except subprocess.TimeoutExpired:
                self.respond_json({"ok": False, "error": "refresh timeout"}, status=HTTPStatus.GATEWAY_TIMEOUT)
            return

        self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def respond_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8090), JobHunterHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()

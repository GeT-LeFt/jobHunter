#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from resume_utils import (
    apply_resume_scores,
    build_resume_profile,
    decode_base64_payload,
    extract_text_from_upload,
    load_resume_profile,
    save_resume_profile,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "web" / "data"
LATEST_JSON = DATA_DIR / "latest.json"
META_JSON = DATA_DIR / "meta.json"
RUN_SCRIPT = BASE_DIR / "run_job_digest.sh"
RESUME_PROFILE_PATH = BASE_DIR / "resume_storage" / "resume_profile.json"


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_jobs_with_resume() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    jobs = load_json(LATEST_JSON) or []
    meta = load_json(META_JSON) or {}
    resume_profile = load_resume_profile(RESUME_PROFILE_PATH)
    if isinstance(jobs, list):
        jobs = apply_resume_scores(jobs, resume_profile)
    return jobs, meta, resume_profile


def salary_threshold(value: str) -> int | None:
    mapping = {
        "10k_plus": 10000,
        "15k_plus": 15000,
        "20k_plus": 20000,
    }
    return mapping.get(value)


def company_size_matches(job: dict[str, Any], size_filter: str) -> bool:
    bucket = str(job.get("company_size_bucket", "unknown"))
    if size_filter in {"", "all"}:
        return True
    if size_filter == "preferred_large":
        if job.get("region") != "深圳":
            return True
        return bucket in {"10000_plus", "unknown"}
    if size_filter == "10000_plus":
        return bucket == "10000_plus"
    if size_filter == "unknown":
        return bucket == "unknown"
    return bucket == size_filter


def filter_jobs(jobs: list[dict[str, Any]], params: dict[str, list[str]]) -> list[dict[str, Any]]:
    region = params.get("region", ["all"])[0]
    query = params.get("q", [""])[0].strip().lower()
    salary_filter = params.get("salary", ["all"])[0]
    company_size = params.get("company_size", ["all"])[0]
    recommended_only = params.get("recommended_only", ["0"])[0] in {"1", "true", "yes"}
    limit_raw = params.get("limit", ["0"])[0]
    strict_large = params.get("strict_large", ["0"])[0] in {"1", "true", "yes"}

    try:
        limit = max(0, int(limit_raw))
    except ValueError:
        limit = 0

    min_salary = salary_threshold(salary_filter)
    effective_company_size = "10000_plus" if strict_large else company_size

    filtered: list[dict[str, Any]] = []
    for job in jobs:
        if region != "all" and job.get("region") != region:
            continue
        if recommended_only and not job.get("recommended"):
            continue
        if not company_size_matches(job, effective_company_size):
            continue
        if min_salary is not None:
            salary_min = job.get("salary_min_monthly") or 0
            salary_max = job.get("salary_max_monthly") or 0
            if not salary_min and not salary_max:
                continue
            if max(int(salary_min or 0), int(salary_max or 0)) < min_salary:
                continue
        if query:
            haystack = " ".join(
                [
                    str(job.get("title", "")),
                    str(job.get("company", "")),
                    str(job.get("location", "")),
                    str(job.get("summary", "")),
                    str(job.get("region", "")),
                    " ".join(job.get("tags", []) or []),
                    " ".join(job.get("match_reasons", []) or []),
                ]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(job)

    if limit:
        return filtered[:limit]
    return filtered


def resume_meta_payload(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not profile:
        return {"has_resume": False}
    return {
        "has_resume": True,
        "filename": profile.get("filename", ""),
        "updated_at": profile.get("updated_at", ""),
        "target_roles": profile.get("target_roles", []),
        "preferred_cities": profile.get("preferred_cities", []),
        "text_preview": profile.get("text_preview", ""),
    }


class JobHunterHandler(BaseHTTPRequestHandler):
    server_version = "JobHunterAPI/0.2"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        jobs, meta, profile = load_jobs_with_resume()

        if parsed.path == "/jobhunter-api/health":
            self.respond_json({"ok": True})
            return

        if parsed.path == "/jobhunter-api/meta":
            if not meta:
                self.respond_json({"error": "meta not found"}, status=HTTPStatus.NOT_FOUND)
                return
            payload = dict(meta)
            payload["resume"] = resume_meta_payload(profile)
            self.respond_json(payload)
            return

        if parsed.path == "/jobhunter-api/resume/meta":
            self.respond_json(resume_meta_payload(profile))
            return

        if parsed.path == "/jobhunter-api/latest":
            if not jobs:
                self.respond_json({"error": "jobs not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.respond_json({"items": jobs, "count": len(jobs), "resume": resume_meta_payload(profile)})
            return

        if parsed.path == "/jobhunter-api/jobs":
            if not jobs:
                self.respond_json({"error": "jobs not found"}, status=HTTPStatus.NOT_FOUND)
                return
            filtered = filter_jobs(jobs, params)
            self.respond_json(
                {
                    "items": filtered,
                    "count": len(filtered),
                    "generated_at": meta.get("generated_at"),
                    "generated_at_display": meta.get("generated_at_display"),
                    "regions": meta.get("regions"),
                    "resume": resume_meta_payload(profile),
                }
            )
            return

        self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/jobhunter-api/refresh":
            self.handle_refresh()
            return
        if parsed.path == "/jobhunter-api/resume":
            self.handle_resume_upload()
            return
        self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def handle_refresh(self) -> None:
        try:
            result = subprocess.run(
                ["/bin/zsh", str(RUN_SCRIPT)],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
            self.respond_json({"ok": True, "stdout": result.stdout[-1200:]})
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

    def handle_resume_upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.respond_json({"ok": False, "error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
            return

        filename = str(payload.get("filename", "resume.txt")).strip() or "resume.txt"
        text = str(payload.get("text", "")).strip()
        content_base64 = str(payload.get("content_base64", "")).strip()

        if not text and not content_base64:
            self.respond_json({"ok": False, "error": "missing resume content"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            if not text:
                raw = decode_base64_payload(content_base64)
                text = extract_text_from_upload(filename, raw)
        except Exception as exc:
            self.respond_json({"ok": False, "error": f"resume parse failed: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            return

        if len(text) < 40:
            self.respond_json({"ok": False, "error": "resume text too short"}, status=HTTPStatus.BAD_REQUEST)
            return

        profile = build_resume_profile(text, filename=filename)
        save_resume_profile(RESUME_PROFILE_PATH, profile)
        self.respond_json({"ok": True, "resume": resume_meta_payload(profile)})

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

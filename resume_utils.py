#!/usr/bin/env python3
from __future__ import annotations

import base64
import datetime as dt
import html
import json
import re
import zipfile
from pathlib import Path
from typing import Any


JAPAN_KEYWORDS = [
    "日语",
    "日文",
    "日本",
    "对日",
    "日企",
    "日资",
    "jlpt",
    "n1",
    "n2",
    "japanese",
    "japan",
]

ROLE_GROUPS = {
    "市场": ["市场", "营销", "品牌", "推广", "marketing", "brand", "content", "social", "digital", "公关"],
    "销售": ["销售", "营业", "商务", "客户", "business development", "sales", "account", "bd"],
    "运营": ["运营", "电商", "项目", "协调", "coordinator", "operation", "运营支持"],
    "翻译": ["翻译", "口译", "笔译", "秘书", "助理", "translation", "translator", "interpret"],
    "分析": ["分析", "研究", "咨询", "strategy", "analyst", "research", "consult"],
    "职能": ["人事", "总务", "行政", "back office", "admin", "hr"],
}

CITY_KEYWORDS = {
    "深圳": ["深圳"],
    "香港": ["香港", "hong kong", "hk"],
}

EARLY_CAREER_KEYWORDS = [
    "应届",
    "校招",
    "实习",
    "毕业",
    "graduate",
    "fresh graduate",
    "entry level",
    "trainee",
    "无经验",
]


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_tags(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_spaces(html.unescape(text))


def keyword_matches(lowered_text: str, keyword: str) -> bool:
    lowered_keyword = keyword.lower()
    if re.search(r"[a-z]", lowered_keyword):
        escaped = re.escape(lowered_keyword).replace(r"\ ", r"\s+")
        pattern = rf"(?<![a-z]){escaped}(?![a-z])"
        return re.search(pattern, lowered_text) is not None
    return lowered_keyword in lowered_text


def contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword_matches(lowered, keyword) for keyword in keywords)


def extract_pdf_text(raw: bytes) -> str:
    # Basic fallback for text-based PDFs. Scanned PDFs will still fail.
    chunks = []
    for match in re.finditer(rb"\(([^()]|\\.){3,}\)", raw):
        token = match.group(0)[1:-1]
        token = token.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\n", b"\n")
        try:
            text = token.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = token.decode("gb18030")
            except UnicodeDecodeError:
                text = token.decode("latin-1", errors="ignore")
        if re.search(r"[\u4e00-\u9fffA-Za-z]", text):
            chunks.append(text)
    return normalize_spaces(" ".join(chunks))


def extract_docx_text(raw: bytes) -> str:
    with zipfile.ZipFile(io_from_bytes(raw)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    return strip_tags(xml)


def io_from_bytes(raw: bytes):
    from io import BytesIO

    return BytesIO(raw)


def extract_text_from_upload(filename: str, raw: bytes) -> str:
    suffix = Path(filename or "resume.txt").suffix.lower()
    if suffix in {".txt", ".md", ".csv"}:
        try:
            return normalize_spaces(raw.decode("utf-8"))
        except UnicodeDecodeError:
            return normalize_spaces(raw.decode("gb18030", errors="ignore"))
    if suffix == ".docx":
        return extract_docx_text(raw)
    if suffix == ".pdf":
        return extract_pdf_text(raw)
    try:
        return normalize_spaces(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return normalize_spaces(raw.decode("latin-1", errors="ignore"))


def build_resume_profile(text: str, filename: str = "") -> dict[str, Any]:
    normalized = normalize_spaces(text)
    lowered = normalized.lower()

    target_roles = [
        name
        for name, keywords in ROLE_GROUPS.items()
        if any(keyword_matches(lowered, keyword) for keyword in keywords)
    ]
    preferred_cities = [
        city
        for city, keywords in CITY_KEYWORDS.items()
        if any(keyword_matches(lowered, keyword) for keyword in keywords)
    ]
    if not preferred_cities:
        preferred_cities = ["深圳", "香港"]

    profile = {
        "filename": filename,
        "text": normalized,
        "text_preview": normalized[:240],
        "has_japan_focus": contains_any(normalized, JAPAN_KEYWORDS),
        "target_roles": target_roles or ["市场", "销售", "运营", "翻译", "分析", "职能"],
        "preferred_cities": preferred_cities,
        "early_career": contains_any(normalized, EARLY_CAREER_KEYWORDS),
        "updated_at": dt.datetime.now().isoformat(),
    }
    return profile


def score_job_for_resume(job: dict[str, Any], profile: dict[str, Any] | None) -> tuple[int, list[str]]:
    if not profile:
        return 0, []

    job_text = " ".join(
        [
            str(job.get("title", "")),
            str(job.get("company", "")),
            str(job.get("location", "")),
            str(job.get("summary", "")),
            str(job.get("detail_text", "")),
            " ".join(job.get("tags", []) or []),
            " ".join(job.get("reasons", []) or []),
        ]
    )
    lowered = job_text.lower()

    score = 0
    reasons: list[str] = []

    if profile.get("has_japan_focus") and contains_any(job_text, JAPAN_KEYWORDS):
        score += 3
        reasons.append("简历与岗位都强调日语/日本相关")

    matched_roles: list[str] = []
    for role in profile.get("target_roles", []):
        keywords = ROLE_GROUPS.get(role, [])
        if any(keyword_matches(lowered, keyword) for keyword in keywords):
            matched_roles.append(role)
    if matched_roles:
        score += min(6, len(matched_roles) * 2)
        reasons.append(f"岗位方向命中：{' / '.join(matched_roles[:3])}")

    if job.get("region") in (profile.get("preferred_cities") or []):
        score += 2
        reasons.append(f"地区偏好一致：{job.get('region')}")

    salary_min = job.get("salary_min_monthly") or 0
    if isinstance(salary_min, (int, float)) and salary_min >= 15000:
        score += 1
        reasons.append("薪资区间较优")

    if profile.get("early_career") and (
        "应届" in lowered or "毕业" in lowered or "graduate" in lowered or "无经验" in lowered
    ):
        score += 1
        reasons.append("简历阶段与岗位年限更贴近")

    return score, reasons


def apply_resume_scores(jobs: list[dict[str, Any]], profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for job in jobs:
        cloned = dict(job)
        match_score, match_reasons = score_job_for_resume(cloned, profile)
        cloned["match_score"] = match_score
        cloned["match_reasons"] = match_reasons
        cloned["recommended"] = match_score >= 5
        scored.append(cloned)
    return scored


def load_resume_profile(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_resume_profile(path: Path, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def decode_base64_payload(raw_text: str) -> bytes:
    if "," in raw_text and raw_text.strip().startswith("data:"):
        raw_text = raw_text.split(",", 1)[1]
    return base64.b64decode(raw_text)

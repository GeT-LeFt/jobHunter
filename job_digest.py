#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from resume_utils import apply_resume_scores, contains_any, load_resume_profile, strip_tags

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


WORKDIR = Path(__file__).resolve().parent
OUTPUT_DIR = WORKDIR / "job_digest_output"
STATE_PATH = OUTPUT_DIR / "seen_jobs.json"
DEFAULT_ENV_PATH = WORKDIR / ".env"
WEB_DATA_DIR = WORKDIR / "web" / "data"
TIMEZONE_NAME = "Asia/Shanghai"
RESUME_PROFILE_PATH = WORKDIR / "resume_storage" / "resume_profile.json"
COMPANY_SIZE_OVERRIDES_PATH = WORKDIR / "company_size_overrides.json"

JAPANESE_JOBS_SOURCES = [
    {
        "name": "Japanese-Jobs 深圳",
        "platform": "Japanese-Jobs",
        "base_url": "https://cn.japanese-jobs.com/city-shenzhen",
        "region": "深圳",
        "parser": "japanese_jobs",
        "max_pages": 8,
        "detail_enrichment": True,
    },
]

CTGOODJOBS_SOURCES = [
    {
        "name": "CTgoodjobs 香港 Japanese Fresh Graduate",
        "platform": "CTgoodjobs",
        "base_url": "https://jobs.ctgoodjobs.hk/jobs/japanese-fresh-graduate-jobs",
        "region": "香港",
        "parser": "ctgoodjobs",
        "max_pages": 5,
    },
    {
        "name": "CTgoodjobs 香港 Japanese Marketing",
        "platform": "CTgoodjobs",
        "base_url": "https://jobs.ctgoodjobs.hk/jobs/japanese-marketing-jobs",
        "region": "香港",
        "parser": "ctgoodjobs",
        "max_pages": 5,
    },
    {
        "name": "CTgoodjobs 香港 Japanese Sales",
        "platform": "CTgoodjobs",
        "base_url": "https://jobs.ctgoodjobs.hk/jobs/japanese-sales-jobs",
        "region": "香港",
        "parser": "ctgoodjobs",
        "max_pages": 4,
    },
    {
        "name": "CTgoodjobs 香港 Japanese Translator",
        "platform": "CTgoodjobs",
        "base_url": "https://jobs.ctgoodjobs.hk/jobs/japanese-translator-jobs",
        "region": "香港",
        "parser": "ctgoodjobs",
        "max_pages": 4,
    },
]

BOSS_SOURCES = [
    {
        "name": "BOSS 深圳 日语",
        "platform": "BOSS直聘",
        "region": "深圳",
        "parser": "boss_api",
        "query": "日语",
        "max_pages": 2,
        "enabled_env": "JOBHUNTER_ENABLE_BOSS",
    },
    {
        "name": "BOSS 深圳 日本市场",
        "platform": "BOSS直聘",
        "region": "深圳",
        "parser": "boss_api",
        "query": "日本市场",
        "max_pages": 2,
        "enabled_env": "JOBHUNTER_ENABLE_BOSS",
    },
]

ALL_SOURCES = JAPANESE_JOBS_SOURCES + CTGOODJOBS_SOURCES + BOSS_SOURCES

JAPAN_RELATED_KEYWORDS = [
    "日语",
    "日文",
    "日本",
    "日企",
    "日资",
    "日本市场",
    "对日",
    "japanese",
    "japan",
    "jlpt",
    "n1",
    "n2",
]

LANGUAGE_REQUIREMENT_KEYWORDS = [
    "日语：",
    "日语能力",
    "商务日语",
    "jlpt",
    "n1",
    "n2",
    "japanese speaking",
    "fluent japanese",
]

ROLE_KEYWORDS = [
    "市场",
    "营销",
    "品牌",
    "运营",
    "商务",
    "销售",
    "营业",
    "客户",
    "翻译",
    "口译",
    "笔译",
    "总务",
    "行政",
    "助理",
    "企画",
    "宣传",
    "公关",
    "内容",
    "社媒",
    "分析",
    "研究",
    "咨询",
    "strategy",
    "consult",
    "analyst",
    "research",
    "marketing",
    "brand",
    "operation",
    "sales",
    "business",
    "content",
    "social",
    "coordinator",
    "assistant",
    "translator",
]

EARLY_CAREER_KEYWORDS = [
    "春招",
    "校招",
    "应届",
    "应届生",
    "新卒",
    "graduate",
    "fresh graduate",
    "entry level",
    "trainee",
    "intern",
    "internship",
    "实习",
    "无经验",
    "0 - 2 yr",
    "0-2 yr",
    "1 - 2 yr",
    "1-2 yr",
]

BLACKLIST_KEYWORDS = [
    "工程师",
    "结构",
    "机械",
    "工艺",
    "研发",
    "制造",
    "护士",
    "医生",
    "律师",
    "法务",
    "风控",
    "合规",
    "审计",
]

NOT_FIT_KEYWORDS = [
    "risk",
    "kyc",
    "cdd",
    "compliance",
    "audit",
    "internal control",
    "procurement",
    "purchasing",
    "finance manager",
    "accountant",
    "财务经理",
]

SENIOR_TITLE_KEYWORDS = [
    "senior",
    "manager",
    "director",
    "head",
    "lead",
    "总监",
    "经理",
    "课长",
    "部长",
]

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
    "Accept-Encoding": "identity",
}


@dataclass
class Job:
    source_name: str
    source_platform: str
    source_page: str
    region: str
    title: str
    company: str
    location: str
    url: str
    summary: str = ""
    salary: str = ""
    experience: str = ""
    employment_type: str = ""
    published_text: str = ""
    published_date: str = ""
    tags: list[str] = field(default_factory=list)
    detail_text: str = ""
    role_hint: str = ""
    company_size_raw: str = ""
    company_size_bucket: str = "unknown"
    company_size_value: int | None = None
    salary_min_monthly: int | None = None
    salary_max_monthly: int | None = None
    salary_currency: str = ""
    base_score: int = 0
    reasons: list[str] = field(default_factory=list)
    match_score: int = 0
    match_reasons: list[str] = field(default_factory=list)
    recommended: bool = False
    is_new: bool = False
    is_qualified: bool = True


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def now_in_tz() -> dt.datetime:
    if ZoneInfo is None:
        return dt.datetime.now()
    return dt.datetime.now(ZoneInfo(TIMEZONE_NAME))


def build_paged_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    parts = urlsplit(base_url)
    query_pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_pairs["page"] = str(page)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_pairs), parts.fragment))


def fetch_text(url: str, timeout: int = 20, method: str = "GET", data: bytes | None = None) -> str:
    request = Request(url, headers=HTTP_HEADERS, method=method, data=data)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
        return body.decode("utf-8", errors="ignore")
    except Exception:
        curl_cmd = [
            "curl",
            "-L",
            "--max-time",
            str(timeout),
            "-A",
            HTTP_HEADERS["User-Agent"],
            "-H",
            f"Accept-Language: {HTTP_HEADERS['Accept-Language']}",
            "-H",
            "Accept-Encoding: identity",
        ]
        if method != "GET":
            curl_cmd.extend(["-X", method])
        if data:
            curl_cmd.extend(["--data-binary", data.decode("utf-8", errors="ignore")])
        curl_cmd.append(url)
        result = subprocess.run(curl_cmd, capture_output=True, check=True)
        return result.stdout.decode("utf-8", errors="ignore")


def fetch_json(url: str, timeout: int = 20, method: str = "GET", data: bytes | None = None) -> dict[str, object]:
    return json.loads(fetch_text(url, timeout=timeout, method=method, data=data))


def first_match(pattern: str, text: str, flags: int = re.S | re.I) -> str:
    match = re.search(pattern, text, flags)
    return strip_tags(match.group(1)) if match else ""


def parse_japanese_jobs_page(page_html: str, source_name: str, source_page: str, region: str, platform: str) -> list[Job]:
    chunks = page_html.split('<li class="jj-jobs__item">')[1:]
    jobs: list[Job] = []
    for chunk in chunks:
        url = first_match(r'href="(https://cn\.japanese-jobs\.com/jobs/details/\d+)"', chunk)
        title = first_match(r'data-cassette-anchor="target">([^<]+)</a>', chunk)
        company = first_match(r'<li class="jj-cassette__company">.*?</span>\s*(.*?)\s*</li>', chunk)
        location = first_match(r'<li class="jj-cassette__place">.*?</span>\s*(.*?)\s*</li>', chunk)
        if not url or not title or not company:
            continue
        salary = first_match(r'<li class="jj-cassette__price">.*?</span>\s*(.*?)\s*</li>', chunk)
        summary = first_match(r'<p class="jj-cassette__comment">(.*?)</p>', chunk)
        published_text = first_match(r'<span class="jj-cassette__date">发布时间：([^<]+)</span>', chunk)
        tags = [strip_tags(tag) for tag in re.findall(r'<span class="jj-tag[^"]*">(.*?)</span>', chunk, re.S)]
        tags = [tag for tag in tags if tag]
        employment_type = tags[0] if tags else ""
        experience = next((tag for tag in tags if ("经验" in tag or "年" in tag or tag == "无经验")), "")
        published_date = published_text.split("～", 1)[0] if "～" in published_text else ""
        jobs.append(
            Job(
                source_name=source_name,
                source_platform=platform,
                source_page=source_page,
                region=region,
                title=title,
                company=company,
                location=location,
                url=url,
                summary=summary,
                salary=salary,
                experience=experience,
                employment_type=employment_type,
                published_text=published_text,
                published_date=published_date,
                tags=tags,
            )
        )
    return jobs


def parse_ctgoodjobs_page(page_html: str, source_name: str, source_page: str, region: str, platform: str) -> list[Job]:
    chunks = re.split(r'<div class="job-card\b', page_html)[1:]
    jobs: list[Job] = []
    for chunk in chunks:
        url = first_match(r'<a href="([^"]+)" class="jc-position', chunk)
        title = first_match(r'<a href="[^"]+" class="jc-position[^"]*">\s*<h2>(.*?)</h2>', chunk)
        company = first_match(r'class="jc-company">(.*?)</a>', chunk)
        if not url or not title or not company:
            continue
        if url.startswith("/"):
            url = f"https://jobs.ctgoodjobs.hk{url}"
        location = first_match(r'<div class="row jc-info"><div class="col-12">.*?</svg>(.*?)</div></div>', chunk)
        experience = first_match(r'<div class="row jc-info"><div class="col-6"><i class="cus-icon cus-exp"></i>(.*?)</div></div>', chunk)
        highlights_block = first_match(r'<div class="jc-highlight"><ul>(.*?)</ul></div>', chunk)
        highlights = [strip_tags(item) for item in re.findall(r"<li>(.*?)</li>", highlights_block, re.S)]
        summary = " | ".join(highlights)
        published_text = first_match(r'<div class="jc-other"><div>.*?</svg>(.*?)</div></div>', chunk)
        jobs.append(
            Job(
                source_name=source_name,
                source_platform=platform,
                source_page=source_page,
                region=region,
                title=title,
                company=company,
                location=location,
                url=url,
                summary=summary,
                experience=experience,
                published_text=published_text,
                published_date=parse_relative_date(published_text),
                tags=highlights,
            )
        )
    return jobs


def crawl_boss_source(source: dict[str, object]) -> list[Job]:
    payload_template = "scene=1&query={query}&city=101280600&page={page}&pageSize=15"
    jobs: list[Job] = []
    for page in range(1, int(source["max_pages"]) + 1):
        payload = payload_template.format(query=urlencode({"q": str(source["query"])}).split("=", 1)[1], page=page)
        try:
            data = fetch_json(
                "https://www.zhipin.com/wapi/zpgeek/search/joblist.json",
                timeout=20,
                method="POST",
                data=payload.encode("utf-8"),
            )
        except Exception:
            break
        if int(data.get("code", -1)) != 0:
            break
        zp_data = data.get("zpData", {}) if isinstance(data, dict) else {}
        job_list = zp_data.get("jobList", []) if isinstance(zp_data, dict) else []
        if not isinstance(job_list, list) or not job_list:
            break
        for item in job_list:
            if not isinstance(item, dict):
                continue
            security_id = str(item.get("securityId", "")).strip()
            encrypt_job_id = str(item.get("encryptJobId", "")).strip()
            lid = str(item.get("lid", "")).strip()
            url = ""
            if security_id:
                url = f"https://www.zhipin.com/job_detail/{security_id}.html"
                if lid:
                    url = f"{url}?lid={lid}"
            title = str(item.get("jobName", "")).strip()
            company = str(item.get("brandName", "")).strip()
            salary = str(item.get("salaryDesc", "")).strip()
            experience = str(item.get("jobExperience", "")).strip()
            location = " / ".join(part for part in [item.get("cityName"), item.get("areaDistrict")] if part)
            company_size_raw = str(item.get("brandScaleName", "")).strip()
            summary = " | ".join(
                part for part in [str(item.get("skills", "")), str(item.get("welfareList", ""))] if part and part != "[]"
            )
            tags = [
                str(item.get("brandIndustry", "")).strip(),
                str(item.get("brandStageName", "")).strip(),
                company_size_raw,
            ]
            jobs.append(
                Job(
                    source_name=str(source["name"]),
                    source_platform=str(source["platform"]),
                    source_page="https://www.zhipin.com/web/geek/jobs",
                    region=str(source["region"]),
                    title=title,
                    company=company,
                    location=location,
                    url=url or f"https://www.zhipin.com/web/geek/jobs?query={source['query']}",
                    summary=summary,
                    salary=salary,
                    experience=experience,
                    published_text=str(item.get("daysDesc", "")).strip(),
                    published_date=parse_relative_date(str(item.get("daysDesc", "")).strip()),
                    tags=[tag for tag in tags if tag],
                    company_size_raw=company_size_raw,
                )
            )
    return dedupe_jobs(jobs)


def parse_relative_date(relative_text: str) -> str:
    text = relative_text.lower().strip()
    today = now_in_tz().date()
    if not text:
        return ""
    if text in {"today", "just now", "刚刚"}:
        return today.isoformat()
    if text in {"yesterday", "昨天"}:
        return (today - dt.timedelta(days=1)).isoformat()
    match = re.match(r"(\d+)\s*d\s*ago", text)
    if match:
        return (today - dt.timedelta(days=int(match.group(1)))).isoformat()
    match = re.match(r"(\d+)\s*h\s*ago", text)
    if match:
        return today.isoformat()
    match = re.match(r"(\d+)\s*天前", text)
    if match:
        return (today - dt.timedelta(days=int(match.group(1)))).isoformat()
    return ""


def crawl_source(source: dict[str, object]) -> list[Job]:
    enabled_env = str(source.get("enabled_env", "")).strip()
    if enabled_env and not os.getenv(enabled_env):
        return []

    parser_name = str(source["parser"])
    if parser_name == "boss_api":
        return crawl_boss_source(source)

    base_url = str(source["base_url"])
    source_name = str(source["name"])
    region = str(source["region"])
    platform = str(source["platform"])
    max_pages = int(source["max_pages"])
    parser = parse_japanese_jobs_page if parser_name == "japanese_jobs" else parse_ctgoodjobs_page
    seen_signatures: set[tuple[str, ...]] = set()
    all_jobs: list[Job] = []

    for page in range(1, max_pages + 1):
        page_url = build_paged_url(base_url, page)
        page_html = fetch_text(page_url)
        page_jobs = parser(page_html, source_name, page_url, region, platform)
        if not page_jobs:
            break
        signature = tuple(job.url for job in page_jobs[:5])
        if signature in seen_signatures:
            break
        seen_signatures.add(signature)
        all_jobs.extend(page_jobs)

    if source.get("detail_enrichment"):
        for job in all_jobs[:18]:
            enrich_japanese_jobs_detail(job)

    return dedupe_jobs(all_jobs)


def dedupe_jobs(jobs: Sequence[Job]) -> list[Job]:
    deduped: dict[str, Job] = {}
    for job in jobs:
        deduped.setdefault(job.url, job)
    return list(deduped.values())


def enrich_japanese_jobs_detail(job: Job) -> None:
    try:
        page_html = fetch_text(job.url, timeout=8)
    except Exception:
        return
    responsibilities = first_match(r">岗位职责\s*</div>\s*<div class=\"jj-detail__responsibility__inner\">(.*?)</div>", page_html)
    requirement_block = first_match(r">任职要求\s*</div>\s*<div class=\"jj-detail__requirement__inner\">(.*?)</div>", page_html)
    other_info = first_match(r">其他信息\s*</div>\s*<div class=\"jj-detail__requirement__inner\">(.*?)</div>", page_html)
    role_hint = first_match(r"职位种类：(.*?)</div>", other_info)
    company_size_raw = first_match(r"(?:公司规模|従業員数|员工数)[:：]\s*(.*?)</div>", page_html)
    detail_text = " ".join(part for part in [responsibilities, requirement_block, other_info, role_hint] if part)
    job.detail_text = detail_text
    job.role_hint = role_hint
    if company_size_raw:
        job.company_size_raw = company_size_raw
    if detail_text and job.summary:
        job.summary = f"{job.summary} | {detail_text[:220]}"
    elif detail_text:
        job.summary = detail_text[:220]


def keyword_matches(lowered_text: str, keyword: str) -> bool:
    lowered_keyword = keyword.lower()
    if re.search(r"[a-z]", lowered_keyword):
        escaped = re.escape(lowered_keyword).replace(r"\ ", r"\s+")
        pattern = rf"(?<![a-z]){escaped}(?![a-z])"
        return re.search(pattern, lowered_text) is not None
    return lowered_keyword in lowered_text


def contains_any_local(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(keyword_matches(lowered, keyword) for keyword in keywords)


def looks_too_senior(job: Job, combined_text: str) -> bool:
    if contains_any_local(combined_text, EARLY_CAREER_KEYWORDS):
        return False
    experience = job.experience.lower()
    senior_patterns = [
        r"\b[3-9]\s*-\s*\d+\s*yr",
        r"\b([3-9]|[1-9]\d)\+?\s*yr",
        r"\b([3-9]|[1-9]\d)\+?\s*year",
        r"[3-9]-\d+年",
        r"[4-9]年以上",
        r"5-10年",
        r"10年以上",
    ]
    return any(re.search(pattern, experience) for pattern in senior_patterns)


def extract_max_years(experience_text: str) -> int | None:
    text = experience_text.lower().strip()
    if not text:
        return None
    if "无经验" in text:
        return 0
    matches = [int(item) for item in re.findall(r"\d+", text)]
    return max(matches) if matches else None


def parse_salary_range(salary_text: str) -> tuple[int | None, int | None, str]:
    lowered = salary_text.lower().replace(",", "")
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", lowered)]
    currency = ""
    if any(token in lowered for token in ["hkd", "港币", "hk$"]):
        currency = "HKD"
    elif any(token in lowered for token in ["rmb", "cny", "人民币"]):
        currency = "RMB"

    if not numbers:
        return None, None, currency

    multiplier = 1
    if "k" in lowered:
        multiplier = 1000
    if "万" in lowered:
        multiplier = 10000

    numbers = [int(value * multiplier) for value in numbers[:2]]
    if len(numbers) == 1:
        min_value = max_value = numbers[0]
    else:
        min_value, max_value = min(numbers), max(numbers)

    if "年" in lowered and "月" not in lowered:
        min_value //= 12
        max_value //= 12

    return min_value, max_value, currency


def parse_company_size(company_size_raw: str) -> tuple[int | None, str]:
    lowered = company_size_raw.lower().replace(",", "")
    if not lowered:
        return None, "unknown"
    if len(lowered) > 40:
        return None, "unknown"
    if not any(marker in lowered for marker in ["人", "employee", "规模", "員", "従業"]):
        return None, "unknown"
    numbers = [int(item) for item in re.findall(r"\d+", lowered)]
    if not numbers:
        return None, "unknown"
    value = max(numbers)
    if value >= 10000:
        return value, "10000_plus"
    if value >= 1000:
        return value, "1000_9999"
    if value >= 100:
        return value, "100_999"
    return value, "1_99"


def load_company_size_overrides(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key.strip().lower()] = value
    return normalized


def apply_company_size_metadata(job: Job, overrides: dict[str, dict[str, object]]) -> None:
    override = overrides.get(job.company.lower())
    if override:
        if isinstance(override.get("company_size_raw"), str):
            job.company_size_raw = str(override["company_size_raw"])
        if isinstance(override.get("company_size_bucket"), str):
            job.company_size_bucket = str(override["company_size_bucket"])
        if isinstance(override.get("company_size_value"), int):
            job.company_size_value = int(override["company_size_value"])

    if job.company_size_bucket != "unknown" or job.company_size_value is not None:
        return

    parsed_value, parsed_bucket = parse_company_size(job.company_size_raw)
    job.company_size_value = parsed_value
    job.company_size_bucket = parsed_bucket


def score_and_filter_jobs(jobs: list[Job]) -> list[Job]:
    overrides = load_company_size_overrides(COMPANY_SIZE_OVERRIDES_PATH)
    filtered: list[Job] = []

    for job in jobs:
        job.salary_min_monthly, job.salary_max_monthly, job.salary_currency = parse_salary_range(job.salary)
        apply_company_size_metadata(job, overrides)

        content_text = " ".join(
            [
                job.title,
                job.location,
                job.summary,
                job.detail_text,
                job.role_hint,
                job.experience,
                job.salary,
                " ".join(job.tags),
            ]
        ).strip()
        lowered = content_text.lower()
        title_lower = job.title.lower()
        max_years = extract_max_years(job.experience)
        has_senior_title = contains_any_local(title_lower, SENIOR_TITLE_KEYWORDS)

        if contains_any_local(lowered, NOT_FIT_KEYWORDS):
            continue
        if contains_any_local(title_lower, BLACKLIST_KEYWORDS) and not contains_any_local(title_lower, ROLE_KEYWORDS):
            continue

        has_role_signal = contains_any_local(" ".join([job.title, job.role_hint, content_text]), ROLE_KEYWORDS)
        has_japan_signal = contains_any_local(" ".join([job.title, job.summary, job.detail_text, job.company]), JAPAN_RELATED_KEYWORDS)
        has_language_requirement = contains_any_local(job.detail_text or job.summary, LANGUAGE_REQUIREMENT_KEYWORDS)
        has_early_signal = contains_any_local(content_text, EARLY_CAREER_KEYWORDS)

        if job.source_platform == "Japanese-Jobs" and not (has_language_requirement or contains_any_local(job.title, JAPAN_RELATED_KEYWORDS)):
            continue
        if not has_role_signal:
            continue
        if not has_japan_signal:
            continue
        if looks_too_senior(job, lowered):
            continue
        if max_years is not None and max_years > 4:
            continue
        if max_years is not None and max_years > 2 and not has_early_signal:
            continue
        if has_senior_title and not has_early_signal:
            continue

        reasons: list[str] = []
        score = 0
        score += 3
        reasons.append("明确命中日语/日本相关")
        score += 2
        reasons.append("岗位方向属于目标轨道")
        if has_language_requirement:
            score += 2
            reasons.append("职位描述出现明确语言要求")
        if has_early_signal:
            score += 2
            reasons.append("偏应届 / 初级 / 实习")
        elif max_years is not None and max_years <= 2:
            score += 1
            reasons.append("经验要求较初级")
        if is_recent(job.published_date, days=14):
            score += 1
            reasons.append("最近14天内更新")
        if job.region == "深圳" and job.company_size_bucket == "10000_plus":
            score += 1
            reasons.append("公司规模达到万人以上")

        job.base_score = score
        job.reasons = reasons
        filtered.append(job)

    filtered.sort(
        key=lambda job: (
            job.region != "深圳",
            0 if job.region == "深圳" and job.company_size_bucket == "10000_plus" else 1,
            0 if job.is_new else 1,
            -job.base_score,
            -(job.salary_max_monthly or 0),
            job.company,
            job.title,
        )
    )
    return filtered


def parse_date(date_text: str) -> dt.date | None:
    text = date_text.strip()
    patterns = ("%Y/%m/%d", "%Y-%m-%d")
    for pattern in patterns:
        try:
            return dt.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def is_recent(date_text: str, days: int) -> bool:
    parsed = parse_date(date_text)
    if not parsed:
        return False
    return (now_in_tz().date() - parsed).days <= days


def load_seen_jobs(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def mark_and_persist_seen_jobs(jobs: list[Job], path: Path) -> None:
    seen = load_seen_jobs(path)
    today = now_in_tz().date().isoformat()
    for job in jobs:
        job.is_new = job.url not in seen
        seen[job.url] = {
            "title": job.title,
            "company": job.company,
            "region": job.region,
            "first_seen": seen.get(job.url, {}).get("first_seen", today),
            "last_seen": today,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_counts(jobs: list[dict[str, object]]) -> dict[str, object]:
    regions = {}
    for region in ["深圳", "香港"]:
        region_jobs = [job for job in jobs if job.get("region") == region]
        regions[region] = {
            "total": len(region_jobs),
            "recommended": sum(bool(job.get("recommended")) for job in region_jobs),
            "new": sum(bool(job.get("is_new")) for job in region_jobs),
        }
    return {
        "total": len(jobs),
        "new": sum(bool(job.get("is_new")) for job in jobs),
        "recommended": sum(bool(job.get("recommended")) for job in jobs),
        "regions": regions,
    }


def render_html(jobs: list[dict[str, object]]) -> str:
    summary = summarize_counts(jobs)
    generated_at = now_in_tz().strftime("%Y-%m-%d %H:%M")
    sections: list[str] = []
    for region in ["深圳", "香港"]:
        region_jobs = [job for job in jobs if job.get("region") == region]
        recommended = [job for job in region_jobs if job.get("recommended")] or region_jobs[:6]
        cards = []
        for job in region_jobs[:18]:
            badge = '<span class="badge badge-new">新</span>' if job.get("is_new") else ""
            match_text = "、".join(job.get("match_reasons", []) or []) or "基础筛选结果"
            cards.append(
                f"""
                <div class="card">
                  <div class="title-row">
                    <a class="title" href="{html.escape(str(job.get('url', '')))}">{html.escape(str(job.get('title', '')))}</a>
                    {badge}
                  </div>
                  <div class="company">{html.escape(str(job.get('company', '')))}</div>
                  <div class="meta">{html.escape(format_meta_dict(job))}</div>
                  <div class="reason">推荐理由：{html.escape(match_text)}</div>
                </div>
                """
            )
        recommended_html = "".join(
            f"<li>{html.escape(str(job.get('title', '')))} - {html.escape(str(job.get('company', '')))}</li>"
            for job in recommended[:6]
        )
        sections.append(
            f"""
            <section>
              <h2>{region}（{len(region_jobs)}）</h2>
              <p>优先推荐：{len(recommended)}</p>
              <ul>{recommended_html or '<li>暂无优先推荐</li>'}</ul>
              {''.join(cards) or '<p>暂无岗位</p>'}
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>JobHunter 深港日语岗位面板</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif; background: #f4f1ea; color: #1e1c18; }}
    .wrap {{ max-width: 960px; margin: 0 auto; }}
    .hero {{ background: linear-gradient(135deg, #173d3f, #8c4e30); color: #fff7ea; border-radius: 20px; padding: 28px 30px; margin-bottom: 20px; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0 26px; }}
    .stat, .card {{ background: #fffdf8; border-radius: 16px; padding: 16px; box-shadow: 0 8px 24px rgba(31, 28, 24, 0.06); }}
    section {{ margin-bottom: 28px; }}
    .title {{ font-size: 18px; font-weight: 700; color: #173d3f; text-decoration: none; }}
    .meta, .reason, .company {{ margin-top: 8px; font-size: 14px; line-height: 1.6; color: #5d564f; }}
    .badge-new {{ display: inline-block; margin-left: 8px; border-radius: 999px; padding: 4px 10px; background: #d44a1c; color: white; font-size: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>JobHunter 深港日语岗位面板</h1>
      <p>生成时间：{html.escape(generated_at)}</p>
    </div>
    <div class="stats">
      <div class="stat"><div>总岗位</div><strong>{summary['total']}</strong></div>
      <div class="stat"><div>新发现</div><strong>{summary['new']}</strong></div>
      <div class="stat"><div>深圳</div><strong>{summary['regions']['深圳']['total']}</strong></div>
      <div class="stat"><div>香港</div><strong>{summary['regions']['香港']['total']}</strong></div>
    </div>
    {''.join(sections)}
  </div>
</body>
</html>
"""


def format_meta_dict(job: dict[str, object]) -> str:
    parts = [
        str(job.get("location", "")),
        str(job.get("experience", "")),
        str(job.get("salary", "")),
        str(job.get("published_text", "")),
        human_company_size(str(job.get("company_size_bucket", "unknown"))),
        str(job.get("source_platform", "")),
    ]
    return " | ".join(part for part in parts if part and part != "未知规模")


def render_text(jobs: list[dict[str, object]]) -> str:
    summary = summarize_counts(jobs)
    lines = [
        f"JobHunter 深港日语岗位面板 - {now_in_tz().strftime('%Y-%m-%d %H:%M')}",
        f"总数：{summary['total']} | 新发现：{summary['new']} | 优先推荐：{summary['recommended']}",
        f"深圳：{summary['regions']['深圳']['total']} | 香港：{summary['regions']['香港']['total']}",
        "",
    ]
    for region in ["深圳", "香港"]:
        items = [job for job in jobs if job.get("region") == region]
        lines.append(f"{region}（{len(items)}）")
        for job in items[:15]:
            prefix = "[推]" if job.get("recommended") else "[岗]"
            lines.append(f"{prefix} {job.get('title')} - {job.get('company')}")
            meta = format_meta_dict(job)
            if meta:
                lines.append(f"  {meta}")
            reasons = "、".join(job.get("match_reasons", []) or job.get("reasons", []) or [])
            if reasons:
                lines.append(f"  判断：{reasons}")
            lines.append(f"  {job.get('url')}")
        lines.append("")
    return "\n".join(lines).strip()


def human_company_size(bucket: str) -> str:
    return {
        "10000_plus": "10000+人",
        "1000_9999": "1000-9999人",
        "100_999": "100-999人",
        "1_99": "1-99人",
        "unknown": "未知规模",
    }.get(bucket, bucket)


def save_outputs(jobs: list[dict[str, object]], html_body: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_prefix = now_in_tz().strftime("%Y%m%d")
    generated_at = now_in_tz()
    html_path = OUTPUT_DIR / f"{date_prefix}-digest.html"
    json_path = OUTPUT_DIR / f"{date_prefix}-digest.json"
    latest_html = OUTPUT_DIR / "latest.html"
    latest_json = OUTPUT_DIR / "latest.json"
    web_latest_json = WEB_DATA_DIR / "latest.json"
    web_meta_json = WEB_DATA_DIR / "meta.json"

    summary = summarize_counts(jobs)
    meta_payload = {
        "generated_at": generated_at.isoformat(),
        "generated_at_display": generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": TIMEZONE_NAME,
        "total_jobs": summary["total"],
        "new_jobs": summary["new"],
        "recommended_jobs": summary["recommended"],
        "regions": summary["regions"],
        "resume_enabled": bool(load_resume_profile(RESUME_PROFILE_PATH)),
    }
    payload_text = json.dumps(jobs, ensure_ascii=False, indent=2)
    html_path.write_text(html_body, encoding="utf-8")
    json_path.write_text(payload_text, encoding="utf-8")
    latest_html.write_text(html_body, encoding="utf-8")
    latest_json.write_text(payload_text, encoding="utf-8")
    web_latest_json.write_text(payload_text, encoding="utf-8")
    web_meta_json.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return html_path, json_path


def send_email(subject: str, text_body: str, html_body: str) -> None:
    smtp_host = os.getenv("JOBDIGEST_SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("JOBDIGEST_SMTP_PORT", "587").strip())
    smtp_user = os.getenv("JOBDIGEST_SMTP_USER", "").strip()
    smtp_password = os.getenv("JOBDIGEST_SMTP_PASSWORD", "").strip()
    mail_from = os.getenv("JOBDIGEST_MAIL_FROM", smtp_user).strip()
    mail_to = [item.strip() for item in os.getenv("JOBDIGEST_MAIL_TO", "").split(",") if item.strip()]
    missing = [
        name
        for name, value in [
            ("JOBDIGEST_SMTP_HOST", smtp_host),
            ("JOBDIGEST_SMTP_USER", smtp_user),
            ("JOBDIGEST_SMTP_PASSWORD", smtp_password),
            ("JOBDIGEST_MAIL_FROM", mail_from),
            ("JOBDIGEST_MAIL_TO", ",".join(mail_to)),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(f"缺少邮件配置：{', '.join(missing)}")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = ", ".join(mail_to)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls(context=context)
        server.login(smtp_user, smtp_password)
        server.send_message(message)


def run(send_email_enabled: bool) -> int:
    collected: list[Job] = []
    for source in ALL_SOURCES:
        collected.extend(crawl_source(source))

    jobs = dedupe_jobs(collected)
    jobs = score_and_filter_jobs(jobs)
    mark_and_persist_seen_jobs(jobs, STATE_PATH)

    payload = [asdict(job) for job in jobs]
    resume_profile = load_resume_profile(RESUME_PROFILE_PATH)
    payload = apply_resume_scores(payload, resume_profile)

    html_body = render_html(payload)
    text_body = render_text(payload)
    html_path, json_path = save_outputs(payload, html_body)
    subject = f"JobHunter 深港日语岗位面板 - {now_in_tz().strftime('%Y-%m-%d')}"
    if send_email_enabled:
        send_email(subject, text_body, html_body)

    print(f"已输出 HTML: {html_path}")
    print(f"已输出 JSON: {json_path}")
    print(f"筛选后岗位数: {len(payload)}")
    print(f"其中新发现: {sum(bool(job.get('is_new')) for job in payload)}")
    print(f"其中优先推荐: {sum(bool(job.get('recommended')) for job in payload)}")
    if send_email_enabled:
        print("邮件已发送")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取深圳/香港的日语或日本市场岗位，并生成日报/发送邮件。")
    parser.add_argument("--send-email", action="store_true", help="按 .env 或环境变量里的 SMTP 配置发送邮件。")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH), help="可选 .env 路径，默认读取当前目录下的 .env。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file).expanduser())
    try:
        return run(send_email_enabled=args.send_email)
    except Exception as exc:  # pragma: no cover
        print(f"运行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

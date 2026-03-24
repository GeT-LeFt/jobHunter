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
import sys
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


WORKDIR = Path(__file__).resolve().parent
OUTPUT_DIR = WORKDIR / "job_digest_output"
STATE_PATH = OUTPUT_DIR / "seen_jobs.json"
DEFAULT_ENV_PATH = WORKDIR / ".env"
TIMEZONE_NAME = "Asia/Shanghai"

JAPANESE_JOBS_SOURCES = [
    {
        "name": "Japanese-Jobs 深圳",
        "base_url": "https://cn.japanese-jobs.com/city-shenzhen",
        "region": "深圳",
        "parser": "japanese_jobs",
        "max_pages": 8,
    },
    {
        "name": "Japanese-Jobs 广州",
        "base_url": "https://cn.japanese-jobs.com/city-guangzhou",
        "region": "广州",
        "parser": "japanese_jobs",
        "max_pages": 8,
    },
]

CTGOODJOBS_SOURCES = [
    {
        "name": "CTgoodjobs 香港 Japanese Fresh Graduate",
        "base_url": "https://jobs.ctgoodjobs.hk/jobs/japanese-fresh-graduate-jobs",
        "region": "香港",
        "parser": "ctgoodjobs",
        "max_pages": 5,
    },
    {
        "name": "CTgoodjobs 香港 Japanese Marketing",
        "base_url": "https://jobs.ctgoodjobs.hk/jobs/japanese-marketing-jobs",
        "region": "香港",
        "parser": "ctgoodjobs",
        "max_pages": 5,
    },
]

ALL_SOURCES = JAPANESE_JOBS_SOURCES + CTGOODJOBS_SOURCES

JAPAN_RELATED_KEYWORDS = [
    "日语",
    "日文",
    "日本",
    "日企",
    "日资",
    "日本市场",
    "对日",
    "日语人才",
    "japanese",
    "japanese-speaking",
    "japanese speaking",
    "japan",
    "japan market",
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
    "客服",
    "翻译",
    "口译",
    "笔译",
    "总务",
    "行政",
    "助理",
    "企画",
    "广报",
    "宣传",
    "公关",
    "内容",
    "社媒",
    "分析",
    "数据",
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
    "licensing",
    "ecommerce",
    "coordinator",
    "assistant",
    "administrator",
    "customer",
    "client",
]

EARLY_CAREER_KEYWORDS = [
    "春招",
    "校招",
    "应届",
    "应届生",
    "新卒",
    "graduate",
    "fresh graduate",
    "fresh graduates",
    "entry level",
    "trainee",
    "management trainee",
    "graduate program",
    "intern",
    "internship",
    "实习",
    "无经验",
    "0 - 2 yr",
    "0-2 yr",
    "0-1 yr",
    "1 - 2 yr",
    "1-2 yr",
]

BLACKLIST_KEYWORDS = [
    "工程师",
    "sqe",
    "制造",
    "医師",
    "医生",
    "护士",
    "结构",
    "机械",
    "工艺",
    "研发",
    "技术员",
    "技術",
    "品质",
    "质量",
    "律师",
    "法务",
]

MARKETING_FOCUS_KEYWORDS = [
    "市场",
    "营销",
    "品牌",
    "运营",
    "销售",
    "营业",
    "商务",
    "marketing",
    "brand",
    "content",
    "social",
    "digital",
    "ecommerce",
    "licensing",
    "business development",
]

NOT_FIT_KEYWORDS = [
    "risk",
    "kyc",
    "cdd",
    "compliance",
    "audit",
    "internal control",
    "real estate",
    "store business",
    "procurement",
    "purchasing",
    "finance manager",
    "accountant",
    "财务经理",
    "审计",
    "风控",
    "合规",
    "地产",
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
    relevance_score: int = 0
    reasons: list[str] = field(default_factory=list)
    spring_like: bool = False
    is_new: bool = False
    category: str = ""


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


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


def fetch_text(url: str, timeout: int = 20) -> str:
    request = Request(url, headers=HTTP_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    return body.decode("utf-8", errors="ignore")


def strip_tags(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def first_match(pattern: str, text: str, flags: int = re.S | re.I) -> str:
    match = re.search(pattern, text, flags)
    return strip_tags(match.group(1)) if match else ""


def parse_japanese_jobs_page(page_html: str, source_name: str, source_page: str, region: str) -> list[Job]:
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
        experience = next(
            (
                tag
                for tag in tags
                if ("经验" in tag or "年" in tag or tag == "无经验")
            ),
            "",
        )

        published_date = ""
        if "～" in published_text:
            published_date = published_text.split("～", 1)[0]

        jobs.append(
            Job(
                source_name=source_name,
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


def parse_ctgoodjobs_page(page_html: str, source_name: str, source_page: str, region: str) -> list[Job]:
    chunks = re.split(r'<div class="job-card\b', page_html)[1:]
    jobs: list[Job] = []

    for chunk in chunks:
        url = first_match(r'<a href="([^"]+)" class="jc-position', chunk)
        title = first_match(r'<a href="[^"]+" class="jc-position[^"]*">\s*<h2>(.*?)</h2>', chunk)
        company = first_match(r'class="jc-company">(.*?)</a>', chunk)

        if not url or not title or not company:
            continue

        location = first_match(r'<div class="row jc-info"><div class="col-12">.*?</svg>(.*?)</div></div>', chunk)
        experience = first_match(
            r'<div class="row jc-info"><div class="col-6"><i class="cus-icon cus-exp"></i>(.*?)</div></div>',
            chunk,
        )
        highlights_block = first_match(r'<div class="jc-highlight"><ul>(.*?)</ul></div>', chunk)
        highlights = [strip_tags(item) for item in re.findall(r"<li>(.*?)</li>", highlights_block, re.S)]
        summary = " | ".join(highlights)
        published_text = first_match(r'<div class="jc-other"><div>.*?</svg>(.*?)</div></div>', chunk)
        published_date = parse_relative_date(published_text)

        jobs.append(
            Job(
                source_name=source_name,
                source_page=source_page,
                region=region,
                title=title,
                company=company,
                location=location,
                url=url,
                summary=summary,
                experience=experience,
                published_text=published_text,
                published_date=published_date,
                tags=highlights,
            )
        )

    return jobs


def parse_relative_date(relative_text: str) -> str:
    text = relative_text.lower().strip()
    now = now_in_tz().date()

    if not text:
        return ""
    if text in {"today", "just now"}:
        return now.isoformat()
    if text == "yesterday":
        return (now - dt.timedelta(days=1)).isoformat()

    match = re.match(r"(\d+)\s*d\s*ago", text)
    if match:
        return (now - dt.timedelta(days=int(match.group(1)))).isoformat()

    match = re.match(r"(\d+)\s*h\s*ago", text)
    if match:
        return now.isoformat()

    return ""


def crawl_source(source: dict[str, object]) -> list[Job]:
    parser_name = str(source["parser"])
    base_url = str(source["base_url"])
    source_name = str(source["name"])
    region = str(source["region"])
    max_pages = int(source["max_pages"])

    parser = parse_japanese_jobs_page if parser_name == "japanese_jobs" else parse_ctgoodjobs_page
    seen_signatures: set[tuple[str, ...]] = set()
    all_jobs: list[Job] = []

    for page in range(1, max_pages + 1):
        page_url = build_paged_url(base_url, page)
        page_html = fetch_text(page_url)
        page_jobs = parser(page_html, source_name, page_url, region)
        if not page_jobs:
            break

        signature = tuple(job.url for job in page_jobs[:5])
        if signature in seen_signatures:
            break
        seen_signatures.add(signature)
        all_jobs.extend(page_jobs)

    deduped: dict[str, Job] = {}
    for job in all_jobs:
        deduped.setdefault(job.url, job)
    return list(deduped.values())


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(keyword_matches(lowered, keyword) for keyword in keywords)


def keyword_matches(lowered_text: str, keyword: str) -> bool:
    lowered_keyword = keyword.lower()
    if re.search(r"[a-z]", lowered_keyword):
        escaped = re.escape(lowered_keyword).replace(r"\ ", r"\s+")
        pattern = rf"(?<![a-z]){escaped}(?![a-z])"
        return re.search(pattern, lowered_text) is not None
    return lowered_keyword in lowered_text


def looks_too_senior(job: Job, combined_text: str) -> bool:
    if contains_any(combined_text, EARLY_CAREER_KEYWORDS):
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
    if not matches:
        return None
    return max(matches)


def score_and_filter_jobs(jobs: list[Job]) -> list[Job]:
    filtered: list[Job] = []

    for job in jobs:
        content_text = " ".join(
            [
                job.title,
                job.location,
                job.summary,
                job.experience,
                job.salary,
                " ".join(job.tags),
            ]
        ).strip()
        lowered = content_text.lower()
        max_years = extract_max_years(job.experience)
        has_senior_title = contains_any(job.title.lower(), SENIOR_TITLE_KEYWORDS)

        if contains_any(lowered, BLACKLIST_KEYWORDS) and not contains_any(lowered, ROLE_KEYWORDS):
            continue
        if contains_any(lowered, NOT_FIT_KEYWORDS):
            continue

        japan_text = " ".join([content_text, job.company]).lower()
        has_japan_signal = contains_any(japan_text, JAPAN_RELATED_KEYWORDS) or "Japanese-Jobs" in job.source_name
        has_role_signal = contains_any(lowered, ROLE_KEYWORDS)
        has_early_signal = contains_any(lowered, EARLY_CAREER_KEYWORDS)
        has_marketing_signal = contains_any(lowered, MARKETING_FOCUS_KEYWORDS)

        if "CTgoodjobs 香港 Japanese Marketing" in job.source_name and not has_marketing_signal:
            continue
        if "CTgoodjobs 香港 Japanese Fresh Graduate" in job.source_name:
            if not has_early_signal and (max_years is None or max_years > 2):
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

        if has_japan_signal:
            score += 2
            reasons.append("日语/日本相关")
        if has_role_signal:
            score += 2
            reasons.append("岗位方向匹配语言/市场/分析")
        if has_early_signal:
            score += 3
            reasons.append("明确偏春招/应届/实习")
        elif max_years is not None and max_years <= 2:
            score += 2
            reasons.append("经验要求偏初级")

        if is_recent(job.published_date, days=14):
            score += 1
            reasons.append("最近14天内更新")

        job.relevance_score = score
        job.reasons = reasons
        job.spring_like = (
            (has_early_signal or (max_years is not None and max_years <= 2))
            and not has_senior_title
            and has_japan_signal
        )
        job.category = "高匹配春招" if job.spring_like else "补充关注"
        filtered.append(job)

    filtered.sort(
        key=lambda job: (
            0 if job.category == "高匹配春招" else 1,
            0 if job.is_new else 1,
            -job.relevance_score,
            job.region,
            job.company,
            job.title,
        )
    )
    return filtered


def is_recent(date_text: str, days: int) -> bool:
    if not date_text:
        return False
    parsed = parse_date(date_text)
    if not parsed:
        return False
    return (now_in_tz().date() - parsed).days <= days


def parse_date(date_text: str) -> dt.date | None:
    text = date_text.strip()
    patterns = ("%Y/%m/%d", "%Y-%m-%d")
    for pattern in patterns:
        try:
            return dt.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


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


def summarize_counts(jobs: list[Job]) -> dict[str, int]:
    summary = {
        "total": len(jobs),
        "new": sum(job.is_new for job in jobs),
        "spring_like": sum(job.category == "高匹配春招" for job in jobs),
        "shenzhen": sum(job.region == "深圳" for job in jobs),
        "guangzhou": sum(job.region == "广州" for job in jobs),
        "hongkong": sum(job.region == "香港" for job in jobs),
    }
    return summary


def render_html(jobs: list[Job]) -> str:
    now_text = now_in_tz().strftime("%Y-%m-%d %H:%M")
    summary = summarize_counts(jobs)
    grouped = {
        "高匹配春招": [job for job in jobs if job.category == "高匹配春招"],
        "补充关注": [job for job in jobs if job.category == "补充关注"],
    }

    sections: list[str] = []
    for name, items in grouped.items():
        if not items:
            continue
        cards = []
        for job in items:
            badge = '<span class="badge badge-new">新</span>' if job.is_new else ""
            meta_parts = [job.region, job.location]
            if job.experience:
                meta_parts.append(job.experience)
            if job.salary:
                meta_parts.append(job.salary)
            if job.published_text:
                meta_parts.append(job.published_text)
            meta = " | ".join(part for part in meta_parts if part)
            reasons = "、".join(job.reasons) if job.reasons else "人工复核"
            tags = "".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in job.tags[:5])
            summary_html = html.escape(job.summary) if job.summary else "无额外摘要"
            cards.append(
                f"""
                <div class="card">
                  <div class="title-row">
                    <a class="title" href="{html.escape(job.url)}">{html.escape(job.title)}</a>
                    {badge}
                  </div>
                  <div class="company">{html.escape(job.company)}</div>
                  <div class="meta">{html.escape(meta)}</div>
                  <div class="reason">判断理由：{html.escape(reasons)}</div>
                  <div class="summary">{summary_html}</div>
                  <div class="tags">{tags}</div>
                </div>
                """
            )
        sections.append(
            f"""
            <section>
              <h2>{html.escape(name)}（{len(items)}）</h2>
              {''.join(cards)}
            </section>
            """
        )

    if not sections:
        sections.append("<p>今天没有筛到符合条件的新岗位。</p>")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>日语 / 日本市场岗位日报</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
      background: #f4f1ea;
      color: #1e1c18;
    }}
    .wrap {{
      max-width: 980px;
      margin: 0 auto;
    }}
    .hero {{
      background: linear-gradient(135deg, #173d3f, #8c4e30);
      color: #fff7ea;
      border-radius: 20px;
      padding: 28px 30px;
      margin-bottom: 20px;
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: 30px;
      line-height: 1.2;
    }}
    .hero p {{
      margin: 0;
      opacity: 0.9;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin: 18px 0 26px;
    }}
    .stat {{
      background: #fffdf8;
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 8px 24px rgba(31, 28, 24, 0.06);
    }}
    .stat .label {{
      font-size: 12px;
      color: #6f675f;
      margin-bottom: 6px;
    }}
    .stat .value {{
      font-size: 28px;
      font-weight: 700;
    }}
    section {{
      margin-bottom: 28px;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 22px;
    }}
    .card {{
      background: #fffdf8;
      border-radius: 18px;
      padding: 18px 18px 16px;
      margin-bottom: 14px;
      box-shadow: 0 8px 24px rgba(31, 28, 24, 0.06);
    }}
    .title-row {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .title {{
      font-size: 20px;
      font-weight: 700;
      color: #173d3f;
      text-decoration: none;
    }}
    .company {{
      margin-top: 8px;
      font-size: 15px;
      color: #3d3a34;
    }}
    .meta, .reason, .summary {{
      margin-top: 8px;
      font-size: 14px;
      line-height: 1.6;
      color: #5d564f;
    }}
    .tags {{
      margin-top: 10px;
    }}
    .tag, .badge {{
      display: inline-block;
      margin: 0 8px 8px 0;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
    }}
    .tag {{
      background: #efe8da;
      color: #6d5129;
    }}
    .badge-new {{
      background: #d44a1c;
      color: white;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>日语 / 日本市场岗位日报</h1>
      <p>生成时间：{html.escape(now_text)}（{TIMEZONE_NAME}）</p>
    </div>

    <div class="stats">
      <div class="stat"><div class="label">总岗位数</div><div class="value">{summary['total']}</div></div>
      <div class="stat"><div class="label">今日新发现</div><div class="value">{summary['new']}</div></div>
      <div class="stat"><div class="label">高匹配春招</div><div class="value">{summary['spring_like']}</div></div>
      <div class="stat"><div class="label">深圳</div><div class="value">{summary['shenzhen']}</div></div>
      <div class="stat"><div class="label">广州</div><div class="value">{summary['guangzhou']}</div></div>
      <div class="stat"><div class="label">香港</div><div class="value">{summary['hongkong']}</div></div>
    </div>

    {''.join(sections)}
  </div>
</body>
</html>
"""


def render_text(jobs: list[Job]) -> str:
    summary = summarize_counts(jobs)
    lines = [
        f"日语 / 日本市场岗位日报 - {now_in_tz().strftime('%Y-%m-%d %H:%M')} ({TIMEZONE_NAME})",
        "",
        f"总数：{summary['total']} | 新发现：{summary['new']} | 高匹配春招：{summary['spring_like']}",
        f"深圳：{summary['shenzhen']} | 广州：{summary['guangzhou']} | 香港：{summary['hongkong']}",
        "",
    ]

    for category in ["高匹配春招", "补充关注"]:
        items = [job for job in jobs if job.category == category]
        if not items:
            continue
        lines.append(f"{category}（{len(items)}）")
        for job in items:
            prefix = "[新]" if job.is_new else "[旧]"
            meta = " | ".join(
                part
                for part in [job.region, job.location, job.experience, job.salary, job.published_text]
                if part
            )
            lines.append(f"{prefix} {job.title} - {job.company}")
            if meta:
                lines.append(f"  {meta}")
            if job.reasons:
                lines.append(f"  判断：{'、'.join(job.reasons)}")
            lines.append(f"  {job.url}")
        lines.append("")

    if len(lines) <= 5:
        lines.append("今天没有筛到符合条件的岗位。")
    return "\n".join(lines).strip()


def save_outputs(jobs: list[Job], html_body: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_prefix = now_in_tz().strftime("%Y%m%d")
    html_path = OUTPUT_DIR / f"{date_prefix}-digest.html"
    json_path = OUTPUT_DIR / f"{date_prefix}-digest.json"
    latest_html = OUTPUT_DIR / "latest.html"
    latest_json = OUTPUT_DIR / "latest.json"

    json_payload = [asdict(job) for job in jobs]
    html_path.write_text(html_body, encoding="utf-8")
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_html.write_text(html_body, encoding="utf-8")
    latest_json.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
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

    deduped_by_url: dict[str, Job] = {}
    for job in collected:
        deduped_by_url.setdefault(job.url, job)

    jobs = list(deduped_by_url.values())
    jobs = score_and_filter_jobs(jobs)
    mark_and_persist_seen_jobs(jobs, STATE_PATH)

    html_body = render_html(jobs)
    text_body = render_text(jobs)
    html_path, json_path = save_outputs(jobs, html_body)

    subject = f"日语 / 日本市场岗位日报 - {now_in_tz().strftime('%Y-%m-%d')}"
    if send_email_enabled:
        send_email(subject, text_body, html_body)

    print(f"已输出 HTML: {html_path}")
    print(f"已输出 JSON: {json_path}")
    print(f"筛选后岗位数: {len(jobs)}")
    print(f"其中新发现: {sum(job.is_new for job in jobs)}")
    if send_email_enabled:
        print("邮件已发送")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取深圳/广州/香港的日语或日本市场岗位，并生成日报/发送邮件。"
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="按 .env 或环境变量里的 SMTP 配置发送邮件。",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_PATH),
        help="可选 .env 路径，默认读取当前目录下的 .env。",
    )
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

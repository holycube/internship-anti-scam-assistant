# -*- coding: utf-8 -*-
"""岗位公共读写、标准化与配置加载。"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

# 保证同目录模块可互相 import（中文文件名）
_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 根目录, 配置目录  # noqa: E402

ENTITY_RE = re.compile(r"&#x([0-9a-fA-F]+);?")

标准字段 = (
    "run_id",
    "platform",
    "source_keyword",
    "job_id",
    "title",
    "company",
    "city",
    "industry",
    "degree",
    "salary_min",
    "salary_max",
    "salary_text",
    "tags",
    "link",
    "remote",
    "publish_time",
    "collected_at",
    "match_score",
    "match_reason",
    "risk_flags",
    "mass_hire_score",
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def clean_text(s: Any) -> str:
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    s = html.unescape(s)
    s = ENTITY_RE.sub("", s)
    s = re.sub(r"[\ue000-\uf8ff]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_config(name: str) -> dict[str, Any]:
    path = 配置目录 / name
    if not path.exists():
        raise FileNotFoundError(f"缺少配置: {path}")
    data = load_json(path, {})
    if not isinstance(data, dict):
        raise ValueError(f"配置不是对象: {path}")
    return data


def load_profile() -> dict[str, Any]:
    return load_config("画像.json")


def load_sources() -> dict[str, Any]:
    return load_config("数据源.json")


def load_filter_rules() -> dict[str, Any]:
    return load_config("过滤规则.json")


def normalize_url(url: str) -> str:
    url = clean_text(url)
    if not url:
        return ""
    try:
        p = urlparse(url)
    except Exception:
        return url.rstrip("/")
    scheme = (p.scheme or "https").lower()
    netloc = (p.netloc or "").lower()
    path = re.sub(r"/+", "/", p.path or "")
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    # 去掉常见跟踪参数
    return urlunparse((scheme, netloc, path, "", "", ""))


def salary_text_from(min_v: Any, max_v: Any, existing: str = "") -> str:
    if existing:
        return clean_text(existing)
    try:
        lo = int(min_v or 0)
        hi = int(max_v or 0)
    except (TypeError, ValueError):
        lo, hi = 0, 0
    if lo == 0 and hi == 0:
        return "薪资面议/未标注"
    if lo and hi:
        return f"{lo}-{hi}元/天"
    return f"{hi or lo}元/天"


def empty_job(**kwargs: Any) -> dict[str, Any]:
    job = {
        "run_id": "",
        "platform": "",
        "source_keyword": "",
        "job_id": "",
        "title": "",
        "company": "",
        "city": "",
        "industry": "",
        "degree": "",
        "salary_min": 0,
        "salary_max": 0,
        "salary_text": "",
        "tags": [],
        "link": "",
        "remote": False,
        "publish_time": "",
        "collected_at": now_iso(),
        "match_score": 0,
        "match_reason": "",
        "risk_flags": [],
        "mass_hire_score": 0,
    }
    job.update(kwargs)
    if not job.get("salary_text"):
        job["salary_text"] = salary_text_from(job.get("salary_min"), job.get("salary_max"))
    if not isinstance(job.get("tags"), list):
        job["tags"] = [clean_text(t) for t in (job.get("tags") or "").split(",") if clean_text(t)]
    if not isinstance(job.get("risk_flags"), list):
        job["risk_flags"] = []
    return job


def get_title(job: dict[str, Any]) -> str:
    return clean_text(job.get("title") or job.get("name") or "")


def get_company(job: dict[str, Any]) -> str:
    return clean_text(job.get("company") or job.get("cname") or "")


def get_link(job: dict[str, Any]) -> str:
    return clean_text(job.get("link") or job.get("url") or "")


def get_tags(job: dict[str, Any]) -> list[str]:
    raw = job.get("tags") or job.get("i_tags") or []
    if isinstance(raw, str):
        return [clean_text(x) for x in re.split(r"[,，/|]", raw) if clean_text(x)]
    return [clean_text(t) for t in raw if clean_text(t)]


def get_score(job: dict[str, Any]) -> int:
    try:
        return int(job.get("match_score") or 0)
    except (TypeError, ValueError):
        return 0


def completeness(job: dict[str, Any]) -> int:
    """字段完整度，用于跨平台去重保留更完整项。"""
    fields = [
        get_title(job),
        get_company(job),
        get_link(job),
        clean_text(job.get("city")),
        clean_text(job.get("industry")),
        clean_text(job.get("degree")),
        clean_text(job.get("salary_text")),
    ]
    score = sum(1 for f in fields if f)
    tags = get_tags(job)
    score += min(3, len(tags))
    if job.get("remote"):
        score += 1
    if job.get("source") or job.get("raw"):
        score += 1
    return score


def dedupe_key(job: dict[str, Any]) -> str:
    link = normalize_url(get_link(job))
    if link:
        return "url:" + link
    company = get_company(job).lower()
    title = get_title(job).lower()
    title = re.sub(r"\s+", "", title)
    return f"ct:{company}|{title}"


def merge_prefer(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """保留更高匹配分；同分保留更完整。"""
    sa, sb = get_score(a), get_score(b)
    if sb > sa:
        return b
    if sa > sb:
        return a
    return b if completeness(b) > completeness(a) else a


def list_raw_jsonl(batch_dir: Path) -> list[Path]:
    return sorted(batch_dir.glob("01_原始_*.jsonl"))


def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


# 根目录导出供脚本引用
ROOT = 根目录

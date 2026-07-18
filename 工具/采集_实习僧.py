# -*- coding: utf-8 -*-
"""实习僧公开 API 采集 → 01_原始_实习僧.jsonl（只采集与标准化，不打分不过滤）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 解析或要求批号  # noqa: E402
from 岗位公共 import (  # noqa: E402
    DEFAULT_HEADERS,
    clean_text,
    empty_job,
    ensure_utf8_stdio,
    load_filter_rules,
    load_sources,
    now_iso,
    write_jsonl,
)


def is_remote_item(item: dict[str, Any], remote_kws: list[str]) -> bool:
    tags = [clean_text(t) for t in (item.get("i_tags") or [])]
    name = clean_text(item.get("name"))
    blob = " ".join(tags + [name])
    return any(k in blob for k in remote_kws)


def fetch_page(
    api: str,
    headers: dict[str, str],
    keyword: str,
    page: int,
    publish_time: str,
    sort_type: str,
    page_size: int,
) -> list[dict]:
    params = {
        "keyword": keyword,
        "page": page,
        "pageSize": page_size,
        "city": "",
        "type": "intern",
        "sortType": sort_type,
        "publishTime": publish_time,
    }
    r = requests.get(api, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    msg = data.get("msg") or {}
    if isinstance(msg, dict):
        return msg.get("data") or []
    return []


def item_to_job(
    item: dict[str, Any],
    *,
    run_id: str,
    keyword: str,
    base: str,
) -> dict[str, Any]:
    uuid = clean_text(item.get("uuid") or "")
    title = clean_text(item.get("name")) or uuid
    tags = [clean_text(t) for t in (item.get("i_tags") or [])]
    try:
        smin = int(item.get("minsalary") or 0)
    except (TypeError, ValueError):
        smin = 0
    try:
        smax = int(item.get("maxsalary") or 0)
    except (TypeError, ValueError):
        smax = 0
    return empty_job(
        run_id=run_id,
        platform="shixiseng",
        source_keyword=keyword,
        job_id=uuid,
        title=title,
        company=clean_text(item.get("cname")),
        city=clean_text(item.get("city")),
        industry=clean_text(item.get("industry")),
        degree=clean_text(item.get("degree")),
        salary_min=smin,
        salary_max=smax,
        tags=tags,
        link=f"{base.rstrip('/')}/intern/{uuid}" if uuid else "",
        remote=True,
        publish_time=clean_text(item.get("refresh_time") or item.get("delivered") or ""),
        collected_at=now_iso(),
        source="shixiseng_api",
        raw={
            "company_tags": [clean_text(t) for t in (item.get("c_tags") or [])],
            "uuid": uuid,
        },
    )


def collect(run_id: str, out_path: Path) -> int:
    sources = load_sources().get("shixiseng") or {}
    rules = load_filter_rules()
    remote_kws = rules.get("remote_keywords") or ["远程", "线上", "在家", "居家"]
    if not sources.get("enabled", True):
        print("实习僧已在配置中禁用，写出空文件")
        write_jsonl(out_path, [])
        return 0

    base = sources.get("base") or "https://www.shixiseng.com"
    api = sources.get("api") or f"{base}/app/interns/search/v2"
    delay = float(sources.get("request_delay_sec") or 0.8)
    page_size = int(sources.get("page_size") or 20)
    remote_only = bool(sources.get("remote_only", True))
    searches = sources.get("searches") or []

    headers = {
        **DEFAULT_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{base}/interns?k={quote('远程')}&p=1",
    }

    seen: set[str] = set()
    jobs: list[dict[str, Any]] = []

    for cfg in searches:
        keyword = cfg.get("keyword") or "远程"
        pages = int(cfg.get("pages") or 1)
        publish_time = cfg.get("publishTime") or "week"
        sort_type = cfg.get("sortType") or "new"
        for page in range(1, pages + 1):
            print(f"[实习僧] {keyword} page={page} publishTime={publish_time}", flush=True)
            try:
                items = fetch_page(
                    api, headers, keyword, page, publish_time, sort_type, page_size
                )
            except Exception as e:
                print(f"  ! error (continue): {e}", flush=True)
                time.sleep(delay)
                continue
            if not items:
                print("  empty, stop paging", flush=True)
                break
            for item in items:
                uuid = clean_text(item.get("uuid") or "")
                if not uuid or uuid in seen:
                    continue
                if remote_only and not is_remote_item(item, remote_kws):
                    continue
                seen.add(uuid)
                jobs.append(item_to_job(item, run_id=run_id, keyword=keyword, base=base))
            time.sleep(delay)

    n = write_jsonl(out_path, jobs)
    print(f"[实习僧] wrote {n} → {out_path}", flush=True)
    return n


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    run_id, batch = 解析或要求批号(argv)
    out = batch / "01_原始_实习僧.jsonl"
    collect(run_id, out)


if __name__ == "__main__":
    main()

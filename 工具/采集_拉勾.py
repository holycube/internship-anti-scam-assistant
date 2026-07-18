# -*- coding: utf-8 -*-
"""拉勾：仅尝试公开搜索页 1–2 页；失败写说明 + 空 jsonl，不伪造、不中断流水线。"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

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
    load_sources,
    now_iso,
    write_jsonl,
)


def keyword_from_url(url: str) -> str:
    qs = parse_qs(urlparse(url).query)
    kd = (qs.get("kd") or qs.get("keyword") or [""])[0]
    return clean_text(unquote(kd)) or "拉勾搜索"


def try_parse_jobs(html_text: str, run_id: str, keyword: str, page_url: str) -> list[dict[str, Any]]:
    """尽力从页面嵌入 JSON / 链接解析；解析不到返回空列表。"""
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 常见 __NEXT_DATA__ / window 变量
    candidates: list[Any] = []
    for pat in (
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});",
        r"window\.gbData\s*=\s*(\{.*?\});",
    ):
        m = re.search(pat, html_text, re.I | re.S)
        if m:
            try:
                candidates.append(json.loads(m.group(1)))
            except json.JSONDecodeError:
                pass

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            # 启发式：含 positionId / positionName
            pid = obj.get("positionId") or obj.get("positionid") or obj.get("jobId")
            pname = obj.get("positionName") or obj.get("positionname") or obj.get("jobName") or obj.get("title")
            company = obj.get("companyShortName") or obj.get("companyFullName") or obj.get("companyName")
            if pid and pname:
                jid = str(pid)
                if jid not in seen:
                    seen.add(jid)
                    link = clean_text(obj.get("positionURL") or obj.get("url") or "")
                    if not link:
                        link = f"https://www.lagou.com/jobs/{jid}.html"
                    city = clean_text(obj.get("city") or obj.get("district") or "")
                    salary = clean_text(obj.get("salary") or "")
                    tags = obj.get("skillLables") or obj.get("skillLabels") or obj.get("positionLables") or []
                    if not isinstance(tags, list):
                        tags = []
                    jobs.append(
                        empty_job(
                            run_id=run_id,
                            platform="lagou",
                            source_keyword=keyword,
                            job_id=jid,
                            title=clean_text(pname),
                            company=clean_text(company),
                            city=city,
                            industry=clean_text(obj.get("industryField") or ""),
                            degree=clean_text(obj.get("education") or ""),
                            salary_text=salary,
                            tags=[clean_text(t) for t in tags],
                            link=link,
                            remote=any(
                                k in (clean_text(pname) + " " + " ".join(map(str, tags)))
                                for k in ("远程", "居家", "线上")
                            ),
                            collected_at=now_iso(),
                            source="lagou_public_search",
                            raw={"from_page": page_url},
                        )
                    )
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    for c in candidates:
        walk(c)

    # 退而求其次：岗位详情链接
    if not jobs:
        for m in re.finditer(
            r'https?://(?:www\.)?lagou\.com/(?:jobs|wn/job)/([0-9]+)[^"\s]*',
            html_text,
            re.I,
        ):
            jid = m.group(1)
            if jid in seen:
                continue
            seen.add(jid)
            link = m.group(0).split('"')[0]
            jobs.append(
                empty_job(
                    run_id=run_id,
                    platform="lagou",
                    source_keyword=keyword,
                    job_id=jid,
                    title=f"拉勾岗位 {jid}",
                    link=link,
                    collected_at=now_iso(),
                    source="lagou_link_only",
                    raw={"from_page": page_url, "note": "仅解析到链接，标题待补"},
                )
            )
            if len(jobs) >= 40:
                break
    return jobs


def collect(run_id: str, batch: Path) -> int:
    sources = load_sources().get("lagou") or {}
    out_path = batch / "01_原始_拉勾.jsonl"
    note_path = batch / "拉勾采集说明.txt"
    delay = float(sources.get("request_delay_sec") or 1.5)
    max_pages = int(sources.get("max_pages") or 2)
    urls = list(sources.get("search_urls") or [])

    if not sources.get("enabled", True):
        write_jsonl(out_path, [])
        note_path.write_text("拉勾已在配置中禁用。\n", encoding="utf-8")
        print("拉勾已禁用")
        return 0

    if not urls:
        write_jsonl(out_path, [])
        note_path.write_text("配置中无 search_urls，跳过。\n", encoding="utf-8")
        return 0

    headers = {
        **DEFAULT_HEADERS,
        "Referer": "https://www.lagou.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    all_jobs: list[dict[str, Any]] = []
    notes: list[str] = [
        f"采集时间: {now_iso()}",
        f"批号: {run_id}",
        f"计划页数上限: {max_pages}",
        "",
    ]
    parse_ok = False
    any_http_ok = False

    for base_url in urls[: max(1, min(len(urls), 4))]:
        keyword = keyword_from_url(base_url)
        for page in range(1, max_pages + 1):
            # 简单拼页参数；失败也不中断
            sep = "&" if "?" in base_url else "?"
            url = f"{base_url}{sep}pn={page}" if page > 1 else base_url
            print(f"[拉勾] {keyword} page={page}", flush=True)
            try:
                r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
                notes.append(f"GET {url} → HTTP {r.status_code}")
                if r.status_code >= 400:
                    notes.append(f"  跳过：HTTP {r.status_code}")
                    time.sleep(delay)
                    continue
                any_http_ok = True
                r.encoding = r.apparent_encoding or "utf-8"
                jobs = try_parse_jobs(r.text, run_id, keyword, url)
                if jobs:
                    parse_ok = True
                    # 去重
                    exist = {j.get("job_id") for j in all_jobs}
                    for j in jobs:
                        if j.get("job_id") not in exist:
                            all_jobs.append(j)
                            exist.add(j.get("job_id"))
                    notes.append(f"  解析到 {len(jobs)} 条（累计 {len(all_jobs)}）")
                else:
                    notes.append("  未能从 HTML 解析出岗位列表（可能需登录/反爬）")
            except Exception as e:
                notes.append(f"GET {url} → 异常: {e}")
                print(f"  ! error (continue): {e}", flush=True)
            time.sleep(delay)

    if not parse_ok:
        write_jsonl(out_path, [])
        notes.extend(
            [
                "",
                "结论：本次未解析到可靠岗位数据，已写出空的 01_原始_拉勾.jsonl。",
                "不会伪造结果；流水线可继续打分/过滤。",
                "若 HTTP 正常但仍无数据，通常是拉勾前端改版或反爬；可改配置或改人工粘贴。",
            ]
        )
        if not any_http_ok:
            notes.append("补充：请求均未成功，请检查网络或稍后再试。")
    else:
        write_jsonl(out_path, all_jobs)
        notes.append("")
        notes.append(f"结论：成功写入 {len(all_jobs)} 条。")

    note_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    print(f"[拉勾] jobs={len(all_jobs)} note={note_path}", flush=True)
    return len(all_jobs)


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    run_id, batch = 解析或要求批号(argv)
    collect(run_id, batch)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Boss：不扫搜索页；读取 Boss待抓链接.txt，低频抓详情并解析。"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 解析或要求批号  # noqa: E402
from 岗位公共 import (  # noqa: E402
    DEFAULT_HEADERS,
    append_jsonl,
    clean_text,
    empty_job,
    ensure_utf8_stdio,
    load_sources,
    now_iso,
    write_jsonl,
)

SALARY_RE = re.compile(
    r"(?P<a>\d+)\s*[-~—–到至]\s*(?P<b>\d+)\s*(?P<unit>K|k|千|万)?|"
    r"(?P<one>\d+)\s*(?P<unit2>K|k|千|万)?\s*(?:元)?(?:/|／)?(?:天|日|月)?"
)


def read_links(path: Path) -> list[str]:
    if not path.exists():
        return []
    links: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("http://") or line.startswith("https://"):
            links.append(line)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_salary(text: str) -> tuple[int, int, str]:
    text = clean_text(text)
    if not text:
        return 0, 0, ""
    m = SALARY_RE.search(text.replace(" ", ""))
    if not m:
        return 0, 0, text
    def scale(n: int, unit: str | None) -> int:
        u = (unit or "").lower()
        if u in ("k",) or u == "千":
            return n * 1000
        if u == "万":
            return n * 10000
        return n

    if m.group("a") and m.group("b"):
        unit = m.group("unit")
        a, b = scale(int(m.group("a")), unit), scale(int(m.group("b")), unit)
        return a, b, text
    if m.group("one"):
        n = scale(int(m.group("one")), m.group("unit2"))
        return n, n, text
    return 0, 0, text


def extract_json_ld(html_text: str) -> list[Any]:
    blocks: list[Any] = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        re.I | re.S,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blocks


def walk_ld(obj: Any) -> list[dict]:
    found: list[dict] = []
    if isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else ([t] if t else [])
        types_l = [str(x).lower() for x in types]
        if any(x in ("jobposting", "job") for x in types_l) or "title" in obj and "hiringOrganization" in obj:
            found.append(obj)
        for v in obj.values():
            found.extend(walk_ld(v))
    elif isinstance(obj, list):
        for x in obj:
            found.extend(walk_ld(x))
    return found


def meta_content(html_text: str, prop: str) -> str:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
        html_text,
        re.I,
    )
    if not m:
        m = re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
            html_text,
            re.I,
        )
    return clean_text(m.group(1)) if m else ""


def job_id_from_url(url: str) -> str:
    path = urlparse(url).path or ""
    m = re.search(r"([a-f0-9]{16,})", path, re.I)
    if m:
        return m.group(1)
    m = re.search(r"job_detail/([^./]+)", path)
    if m:
        return m.group(1)
    return clean_text(path.strip("/").replace("/", "_"))[:64]


def parse_detail(html_text: str, url: str, run_id: str) -> dict[str, Any]:
    title = meta_content(html_text, "og:title") or ""
    desc = meta_content(html_text, "og:description") or meta_content(html_text, "description")
    company = ""
    city = ""
    salary_text = ""
    smin = smax = 0
    industry = ""
    degree = ""
    tags: list[str] = []
    remote = any(k in (title + " " + desc) for k in ("远程", "居家", "线上", "在家"))

    for block in extract_json_ld(html_text):
        for jp in walk_ld(block):
            title = clean_text(jp.get("title") or title)
            org = jp.get("hiringOrganization") or {}
            if isinstance(org, dict):
                company = clean_text(org.get("name") or company)
            loc = jp.get("jobLocation") or {}
            if isinstance(loc, list) and loc:
                loc = loc[0]
            if isinstance(loc, dict):
                addr = loc.get("address") or loc
                if isinstance(addr, dict):
                    city = clean_text(
                        addr.get("addressLocality")
                        or addr.get("addressRegion")
                        or city
                    )
            base = jp.get("baseSalary") or {}
            if isinstance(base, dict):
                val = base.get("value") or base
                if isinstance(val, dict):
                    try:
                        smin = int(float(val.get("minValue") or 0))
                        smax = int(float(val.get("maxValue") or val.get("value") or 0))
                    except (TypeError, ValueError):
                        pass
                    salary_text = clean_text(str(val.get("value") or salary_text))
            desc_ld = clean_text(jp.get("description") or "")
            if desc_ld and not desc:
                desc = desc_ld

    if not title:
        m = re.search(r"<title>(.*?)</title>", html_text, re.I | re.S)
        if m:
            title = clean_text(re.split(r"[-_|]", html_lib.unescape(m.group(1)))[0])

    # HTML 常见字段
    if not company:
        m = re.search(r'class="[^"]*company[^"]*"[^>]*>(.*?)<', html_text, re.I | re.S)
        if m:
            company = clean_text(re.sub(r"<[^>]+>", "", m.group(1)))
    if not salary_text:
        m = re.search(r"(\d+\s*[-~]\s*\d+\s*[Kk千万元/天日月]*)", html_text)
        if m:
            salary_text = clean_text(m.group(1))
    if salary_text and not (smin or smax):
        smin, smax, salary_text = parse_salary(salary_text)

    if not city:
        m = re.search(r"([\u4e00-\u9fff]{2,8})市", title + " " + desc)
        if m:
            city = m.group(1) + "市"

    return empty_job(
        run_id=run_id,
        platform="boss",
        source_keyword="manual_link",
        job_id=job_id_from_url(url),
        title=title or job_id_from_url(url),
        company=company,
        city=city,
        industry=industry,
        degree=degree,
        salary_min=smin,
        salary_max=smax,
        salary_text=salary_text,
        tags=tags,
        link=url,
        remote=remote,
        collected_at=now_iso(),
        source="boss_detail",
        raw={"og_description": desc[:500] if desc else ""},
    )


def collect(run_id: str, batch: Path) -> int:
    sources = load_sources().get("boss") or {}
    delay = float(sources.get("request_delay_sec") or 1.5)
    links_name = sources.get("links_file") or "Boss待抓链接.txt"
    links_path = batch / links_name
    out_path = batch / "01_原始_Boss.jsonl"
    err_path = batch / "Boss错误.jsonl"

    # 每次运行重写结果；错误追加前先清空
    write_jsonl(out_path, [])
    write_jsonl(err_path, [])

    if not sources.get("enabled", True):
        print("Boss 已禁用，写出空文件")
        return 0

    links = read_links(links_path)
    if not links:
        print(f"无待抓链接（{links_path.name}），写出空 jsonl")
        return 0

    jobs: list[dict[str, Any]] = []
    headers = {
        **DEFAULT_HEADERS,
        "Referer": "https://www.zhipin.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    for i, url in enumerate(links, 1):
        print(f"[Boss] {i}/{len(links)} {url}", flush=True)
        try:
            r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            if r.status_code >= 400:
                append_jsonl(
                    err_path,
                    {
                        "url": url,
                        "status": "http_error",
                        "code": r.status_code,
                        "at": now_iso(),
                    },
                )
                time.sleep(delay)
                continue
            r.encoding = r.apparent_encoding or "utf-8"
            job = parse_detail(r.text, url, run_id)
            if not job.get("title"):
                append_jsonl(
                    err_path,
                    {"url": url, "status": "parse_empty", "at": now_iso()},
                )
            else:
                jobs.append(job)
        except Exception as e:
            append_jsonl(
                err_path,
                {"url": url, "status": "error", "detail": str(e)[:200], "at": now_iso()},
            )
            print(f"  ! error (continue): {e}", flush=True)
        time.sleep(delay)

    n = write_jsonl(out_path, jobs)
    print(f"[Boss] wrote {n} → {out_path}", flush=True)
    return n


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    run_id, batch = 解析或要求批号(argv)
    collect(run_id, batch)


if __name__ == "__main__":
    main()

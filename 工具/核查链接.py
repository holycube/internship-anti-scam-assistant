# -*- coding: utf-8 -*-
"""多平台低频核查链接：仅明确 404/下线才剔除；网络/登录错误保留并记录。"""
from __future__ import annotations

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 解析或要求批号  # noqa: E402
from 岗位公共 import (  # noqa: E402
    DEFAULT_HEADERS,
    clean_text,
    ensure_utf8_stdio,
    get_link,
    get_title,
    load_jsonl,
    load_sources,
    now_iso,
    write_jsonl,
)

OFFLINE_MARKERS = (
    "当前职位已下线",
    "职位已下线",
    "该职位已下线",
    "职位不存在",
    "岗位已关闭",
    "已停止招聘",
    "停止招聘",
    "招聘已结束",
    "抱歉，您访问的页面不存在",
    "页面不存在",
    "job has expired",
    "职位已经关闭",
)


def check_one(job: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = get_link(job)
    result = {
        "job_id": job.get("job_id") or "",
        "title": get_title(job),
        "platform": job.get("platform") or "",
        "link": url,
        "status": "error",
        "detail": "",
        "checked_at": now_iso(),
    }
    if not url:
        result["status"] = "error"
        result["detail"] = "无链接"
        return result
    try:
        r = requests.get(
            url,
            headers={**DEFAULT_HEADERS, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            allow_redirects=True,
        )
        text = r.text or ""
        if r.status_code == 404:
            result["status"] = "offline"
            result["detail"] = "HTTP 404"
            return result
        if r.status_code >= 400:
            result["status"] = "error"
            result["detail"] = f"HTTP {r.status_code}"
            return result
        for m in OFFLINE_MARKERS:
            if m in text:
                result["status"] = "offline"
                result["detail"] = m
                return result
        title_m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
        title = title_m.group(1) if title_m else ""
        if "页面不存在" in title or "404" in title:
            result["status"] = "offline"
            result["detail"] = "title:" + clean_text(title)[:40]
            return result
        # 登录墙 / 异常页：保守保留
        if "登录" in text and len(text) < 5000 and "职位" not in text:
            result["status"] = "error"
            result["detail"] = "页面异常/需登录"
            return result
        result["status"] = "ok"
        result["detail"] = "active"
        return result
    except Exception as e:
        result["status"] = "error"
        result["detail"] = str(e)[:160]
        return result


def run(batch: Path) -> None:
    sources = load_sources().get("verify") or {}
    delay = float(sources.get("request_delay_sec") or 0.8)
    timeout = float(sources.get("timeout_sec") or 12)
    workers = max(1, int(sources.get("max_workers") or 4))

    short_path = batch / "04_短名单.jsonl"
    jobs = load_jsonl(short_path)
    if not jobs:
        # 若短名单空，尝试用过滤结果
        jobs = load_jsonl(batch / "03_已过滤.jsonl")
        print(f"[核查] 短名单空，改用已过滤: {len(jobs)}", flush=True)
    else:
        print(f"[核查] 短名单 {len(jobs)}", flush=True)

    if not jobs:
        write_jsonl(batch / "链接核查结果.jsonl", [])
        print("[核查] 无岗位可查", flush=True)
        return

    results: list[dict[str, Any]] = []
    # 低频：线程数受限 + 每完成一条短暂 sleep（在主线程汇总时）
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(check_one, j, timeout): j for j in jobs}
        done = 0
        for fut in as_completed(futs):
            results.append(fut.result())
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"  progress {done}/{len(jobs)}", flush=True)
            time.sleep(delay / max(workers, 1))

    # 保持原顺序
    order = {
        (j.get("job_id"), get_link(j)): i for i, j in enumerate(jobs)
    }
    results.sort(
        key=lambda r: order.get((r.get("job_id"), r.get("link")), 10**9)
    )

    offline_keys: set[tuple[str, str]] = set()
    ok = offline = errors = 0
    for r in results:
        if r["status"] == "ok":
            ok += 1
        elif r["status"] == "offline":
            offline += 1
            offline_keys.add((r.get("job_id") or "", r.get("link") or ""))
        else:
            errors += 1

    write_jsonl(batch / "链接核查结果.jsonl", results)

    # 保守更新短名单：仅剔除明确 offline
    kept = [
        j
        for j in jobs
        if (j.get("job_id") or "", get_link(j)) not in offline_keys
    ]
    write_jsonl(short_path, kept)

    print(
        f"[核查] ok={ok} offline={offline} error_kept={errors} shortlist {len(jobs)}→{len(kept)}",
        flush=True,
    )
    print(f"[核查] 结果 → {batch / '链接核查结果.jsonl'}", flush=True)


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    _run_id, batch = 解析或要求批号(argv)
    run(batch)


if __name__ == "__main__":
    main()

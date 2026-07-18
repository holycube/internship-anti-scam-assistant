# -*- coding: utf-8 -*-
"""把平台结果/<平台>/可投递.jsonl 渲染成旧版风格可投递.md。"""
from __future__ import annotations

import sys
from pathlib import Path

_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 解析或要求批号  # noqa: E402
from 岗位公共 import ensure_utf8_stdio, load_jsonl, load_profile  # noqa: E402
from 岗位卡片 import render_catalog_md  # noqa: E402


def split_levels(
    jobs: list[dict],
    *,
    priority_min: int = 40,
    try_min: int = 15,
) -> tuple[list[dict], list[dict], list[dict]]:
    priority, try_jobs, caution = [], [], []
    for job in jobs:
        level = str(job.get("recommend_level") or "")
        score = int(job.get("match_score") or 0)
        if level == "谨慎":
            caution.append(job)
        elif level == "优先投递":
            priority.append(job)
        elif level == "可尝试":
            try_jobs.append(job)
        elif job.get("remote") is False and "核验" in str(job.get("remote_text") or ""):
            caution.append(job)
        elif score >= priority_min:
            priority.append(job)
        elif score >= try_min:
            try_jobs.append(job)
        else:
            caution.append(job)
    priority.sort(key=lambda j: -int(j.get("match_score") or 0))
    try_jobs.sort(key=lambda j: -int(j.get("match_score") or 0))
    caution.sort(key=lambda j: -int(j.get("match_score") or 0))
    return priority, try_jobs, caution


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    run_id, batch = 解析或要求批号(argv)
    profile = load_profile()
    summary = str(profile.get("summary") or "")
    buckets = profile.get("buckets") or {}
    priority_min = int(buckets.get("priority_min", 40))
    try_min = int(buckets.get("try_min", 15))
    root = batch / "平台结果"
    for name in ("Boss", "拉勾", "实习僧"):
        jsonl = root / name / "可投递.jsonl"
        if not jsonl.exists():
            continue
        jobs = load_jsonl(jsonl)
        if not jobs:
            continue
        # 跳过反爬占位
        jobs = [j for j in jobs if (j.get("title") or "") not in ("请稍候", "")]
        if not jobs:
            continue
        priority, try_jobs, caution = split_levels(
            jobs, priority_min=priority_min, try_min=try_min
        )
        notes = [
            "信息可能来自豆包联网摘要补全，投递前请在 App 打开链接核验。",
            "自动详情抓取若遇反爬，以本卡片字段为准，勿依赖标题为「请稍候」的原始 jsonl。",
        ]
        md = render_catalog_md(
            platform_name=name,
            run_id=run_id,
            profile_summary=summary,
            priority=priority,
            try_jobs=try_jobs,
            caution=caution,
            footer_notes=notes,
        )
        out = root / name / "可投递.md"
        out.write_text(md, encoding="utf-8")
        print(f"[卡片] {name}: 优先{len(priority)} 可尝试{len(try_jobs)} 谨慎{len(caution)} → {out}")


if __name__ == "__main__":
    main()

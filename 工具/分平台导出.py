# -*- coding: utf-8 -*-
"""将过滤结果按平台导出为可投递 JSONL 与 Markdown。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 解析或要求批号  # noqa: E402
from 岗位公共 import (  # noqa: E402
    clean_text,
    ensure_utf8_stdio,
    get_company,
    get_link,
    get_score,
    get_tags,
    get_title,
    load_jsonl,
    load_profile,
    write_jsonl,
)
from 岗位卡片 import render_job_card  # noqa: E402


PLATFORMS = {
    "shixiseng": "实习僧",
    "boss": "Boss",
    "lagou": "拉勾",
}


def render_platform_md(
    run_id: str,
    display_name: str,
    jobs: list[dict[str, Any]],
    priority_min: int,
    try_min: int,
) -> str:
    priority = [j for j in jobs if get_score(j) >= priority_min]
    try_jobs = [j for j in jobs if try_min <= get_score(j) < priority_min]
    lines = [
        f"# {display_name}可投递岗位 · {run_id}",
        "",
        f"共 {len(jobs)} 条：优先投递 {len(priority)} 条，可尝试 {len(try_jobs)} 条。",
        "",
    ]

    def section(title: str, items: list[dict[str, Any]]) -> None:
        lines.extend([f"## {title}（{len(items)}）", ""])
        if not items:
            lines.extend(["暂无", ""])
            return
        for index, job in enumerate(items, 1):
            # 与旧版「远程实习岗位_实习僧.md」同结构：公司/薪资/匹配/标签/链接/打招呼
            card = dict(job)
            if not card.get("remote_text"):
                card["remote_text"] = "明确远程" if card.get("remote") else (
                    clean_text(card.get("publish_time")) and "待核验" or "待核验"
                )
            if not card.get("industry"):
                card["industry"] = clean_text(card.get("industry")) or "未标注"
            if not card.get("degree"):
                card["degree"] = clean_text(card.get("degree")) or "未标注"
            lines.extend(render_job_card(index, card))

    section(f"优先投递（≥{priority_min}）", priority)
    section(f"可尝试（{try_min}–{priority_min - 1}）", try_jobs)
    return "\n".join(lines).rstrip() + "\n"


def write_boss_instructions(path: Path) -> None:
    text = """# Boss 待粘贴链接说明

现有脚本不会扫描 Boss 搜索页。请在 Boss 中按“最新发布 / 一周内”搜索，确认岗位明确支持远程或线上，再将详情 URL 逐行粘贴到批次根目录的 `Boss待抓链接.txt`。

推荐搜索词：

- 远程兼职、线上兼职、远程实习
- Excel 远程、Word 远程、办公助理远程、文档远程
- Notion、飞书、知识库远程
- AI 远程、AI 助理、Cursor、API 远程、Agent 远程
- 测试远程、QA、自动化测试远程
"""
    path.write_text(text, encoding="utf-8")


def run(run_id: str, batch: Path) -> int:
    profile = load_profile()
    buckets = profile.get("buckets") or {}
    priority_min = int(buckets.get("priority_min", 40))
    try_min = int(buckets.get("try_min", 15))
    filtered = load_jsonl(batch / "03_已过滤.jsonl")
    export_root = batch / "平台结果"

    total = 0
    for platform_key, display_name in PLATFORMS.items():
        platform_dir = export_root / display_name
        platform_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = platform_dir / "可投递.jsonl"

        platform_jobs = [
            job
            for job in filtered
            if clean_text(job.get("platform")).lower() == platform_key
            and get_score(job) >= try_min
        ]
        platform_jobs.sort(key=lambda job: (-get_score(job), get_title(job)))

        # Boss 反爬时常只有「请稍候」；若已有豆包补全卡片，勿覆盖
        if platform_key == "boss":
            existing = load_jsonl(jsonl_path)
            enriched = [
                j
                for j in existing
                if j.get("source") == "doubao_enrich"
                or (get_title(j) and get_title(j) != "请稍候" and (j.get("hello") or j.get("match_reason")))
            ]
            scraped_ok = [j for j in platform_jobs if get_title(j) and get_title(j) != "请稍候"]
            if enriched and not scraped_ok:
                platform_jobs = enriched
                print(f"[分平台] Boss: 保留已补全卡片 {len(enriched)} 条，不覆盖", flush=True)
            else:
                write_jsonl(jsonl_path, platform_jobs)
        else:
            write_jsonl(jsonl_path, platform_jobs)

        (platform_dir / "可投递.md").write_text(
            render_platform_md(
                run_id,
                display_name,
                platform_jobs,
                priority_min,
                try_min,
            ),
            encoding="utf-8",
        )
        if platform_key == "boss":
            write_boss_instructions(platform_dir / "待粘贴链接说明.md")
        total += len(platform_jobs)
        print(f"[分平台] {display_name}: {len(platform_jobs)}", flush=True)

    print(f"[分平台] 共导出 {total} 条 → {export_root}", flush=True)
    return total


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    run_id, batch = 解析或要求批号(argv)
    run(run_id, batch)


if __name__ == "__main__":
    main()

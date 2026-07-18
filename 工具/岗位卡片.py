# -*- coding: utf-8 -*-
"""从结构化 JSONL 渲染「旧版风格」岗位卡片 Markdown。"""
from __future__ import annotations

from typing import Any


def render_job_card(index: int, job: dict[str, Any]) -> list[str]:
    title = (job.get("title") or job.get("name") or "岗位名称待补").strip()
    link = (job.get("link") or job.get("url") or "").strip()
    company = (job.get("company") or "未标注").strip()
    city = (job.get("city") or "未标注").strip()
    industry = (job.get("industry") or "未标注").strip()
    degree = (job.get("degree") or "未标注").strip()
    salary = (job.get("salary_text") or "未标注").strip()
    score = job.get("match_score")
    score_text = str(score) if score not in (None, "") else "待评"
    reason = (job.get("match_reason") or "待核验").strip()
    remote = (job.get("remote_text") or ("明确远程" if job.get("remote") else "待核验")).strip()
    risk = job.get("risk") or job.get("risk_flags") or ""
    if isinstance(risk, list):
        risk = " / ".join(str(x) for x in risk if x)
    tags = job.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("/", "、").split("、") if t.strip()]
    hello = (job.get("hello") or job.get("打招呼") or "").strip()

    lines = [
        f"### {index}. [{title}]({link})" if link else f"### {index}. {title}",
        "",
        f"- 公司：{company}｜城市：{city}｜行业：{industry}｜学历：{degree}",
        f"- 薪资：{salary}｜匹配分：{score_text}｜远程：{remote}",
        f"- 匹配说明：{reason}",
    ]
    if tags:
        lines.append(f"- 标签：{' / '.join(str(t) for t in tags)}")
    if risk:
        lines.append(f"- 风险：{risk}")
    if link:
        lines.append(f"- 链接：{link}")
    if hello:
        lines.append(f"- **打招呼**：{hello}")
    lines.append("")
    return lines


def render_catalog_md(
    *,
    platform_name: str,
    run_id: str,
    profile_summary: str,
    priority: list[dict[str, Any]],
    try_jobs: list[dict[str, Any]],
    caution: list[dict[str, Any]] | None = None,
    footer_notes: list[str] | None = None,
) -> str:
    caution = caution or []
    total = len(priority) + len(try_jobs) + len(caution)
    lines = [
        f"# {platform_name} · 近一周可投岗位",
        "",
        f"生成批次：{run_id} · 共 {total} 个岗位",
        "",
        "## 匹配画像",
        "",
        profile_summary or "见配置/画像.json",
        "",
        f"## 优先投递（{len(priority)}）",
        "",
    ]
    if not priority:
        lines.extend(["暂无", ""])
    else:
        for i, job in enumerate(priority, 1):
            lines.extend(render_job_card(i, job))

    lines.extend([f"## 可尝试（{len(try_jobs)}）", ""])
    if not try_jobs:
        lines.extend(["暂无", ""])
    else:
        for i, job in enumerate(try_jobs, 1):
            lines.extend(render_job_card(i, job))

    if caution:
        lines.extend([f"## 谨慎（{len(caution)}）", ""])
        for i, job in enumerate(caution, 1):
            lines.extend(render_job_card(i, job))

    if footer_notes:
        lines.extend(["## 备注", ""])
        for note in footer_notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"

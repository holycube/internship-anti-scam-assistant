# -*- coding: utf-8 -*-
"""过滤：硬过滤、风险标记、同公司同类去重 → 03_已过滤 + 人工浏览；短名单空时初建。"""
from __future__ import annotations

import re
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
    get_score,
    get_tags,
    get_title,
    load_filter_rules,
    load_jsonl,
    load_profile,
    write_jsonl,
)

LANG_IN_BRACKET_RE = re.compile(
    r"[（【](?:日语|韩语|法语|德语|西班牙语|俄语|阿拉伯语|意大利语|葡萄牙语|泰语|越南语|印尼语|马来语|小语种)[）】]"
)


def normalize_role_category(name: str, categories: list[dict[str, Any]]) -> str:
    n = clean_text(name)
    n = re.sub(r"[（(【\[].*?[）)】\]]", "", n)
    n = re.sub(
        r"(远程|线上|居家|在家|急招|急聘|急|接受应届|可转正|实习证明|时间自由|时间灵活)",
        "",
        n,
    )
    n = re.sub(r"\s+", "", n)
    for cat in categories:
        cat_name = cat.get("name") or ""
        kws = cat.get("keywords") or []
        if any(kw.lower() in n.lower() for kw in kws):
            return cat_name
    base = re.sub(r"(实习生?|专员|助理|岗位)$", "", n)
    return base or n or "其他"


def hard_exclude(job: dict[str, Any], rules: dict[str, Any]) -> tuple[bool, str]:
    he = rules.get("hard_exclude") or {}
    title = get_title(job)
    company = get_company(job)
    degree = clean_text(job.get("degree"))
    tags = get_tags(job)
    blob = " ".join([title, company, degree, *tags])

    for kw in he.get("degree_keywords") or []:
        if kw in degree:
            return True, f"学历{kw}"
    for kw in he.get("name_degree_keywords") or []:
        if kw in title:
            return True, f"名称含{kw}"

    for kw in he.get("blob_keywords") or []:
        if kw == "品牌大使":
            if kw in title:
                return True, kw
        elif kw in blob:
            return True, kw

    for kw in he.get("zhongcao") or []:
        if kw in blob:
            return True, f"种草:{kw}"

    tag_key = he.get("study_abroad_tag") or "留学生实习"
    if any(t == tag_key or tag_key in t for t in tags):
        return True, "留学生实习标签"

    for kw in he.get("ai_video") or []:
        if kw in blob:
            return True, f"AI视频:{kw}"
    for kw in he.get("short_video") or []:
        if kw in blob:
            return True, f"短视频:{kw}"

    for kw in he.get("study_abroad") or []:
        if kw == "限留学":
            if kw in title or kw in company:
                return True, "限留学"
        elif kw == "留学":
            if "留学" in title or "留学" in company:
                return True, "留学相关"

    for kw in he.get("minor_languages") or []:
        if kw in title or kw in company:
            return True, f"小语种:{kw}"
    if LANG_IN_BRACKET_RE.search(title):
        return True, "括号语种要求"
    if re.search(r"精通(?:日语|韩语|法语|德语|西班牙语|俄语|阿拉伯语|泰语|越南语|印尼语)", title):
        return True, "精通小语种"

    for kw in he.get("strict_major") or []:
        if kw in title:
            return True, f"严格专业:{kw}"
    if re.search(r"(?:仅限|必须|只招).{0,8}专业", title):
        return True, "仅限/必须某专业"

    for kw in he.get("teach_english") or []:
        if kw in blob:
            return True, kw

    if "英语" in title and any(
        k in title
        for k in (
            "教学", "录制", "录课", "辅导", "老师", "教师", "助教",
            "小学", "版本", "录师", "录题", "幼教", "绘本", "陪读", "口语",
        )
    ):
        return True, "英语教学/录制"
    if ("录师" in title or "录课" in title or "录制" in title or "录题" in title) and any(
        k in title for k in ("英语", "小学", "教学", "语文", "数学", "小初", "数英")
    ):
        return True, "学科录制"

    return False, ""


def risk_and_mass(job: dict[str, Any], rules: dict[str, Any]) -> tuple[list[str], int]:
    rf_cfg = rules.get("risk_flags") or {}
    mh_cfg = rules.get("mass_hire") or {}
    title = get_title(job)
    company = get_company(job)
    blob = " ".join([title, company, *get_tags(job)])
    flags: list[str] = []
    mass = 0

    for kw in rf_cfg.get("mass_hire_title_keywords") or []:
        if kw in title:
            flags.append(f"海量招聘:{kw}")
            mass += int(mh_cfg.get("title_hit", 40))
    for kw in rf_cfg.get("agency_keywords") or []:
        if kw in blob:
            flags.append(f"中介嫌疑:{kw}")
            mass += int(mh_cfg.get("agency_hit", 30))
    for kw in rf_cfg.get("unclear_remote_keywords") or []:
        if kw in blob:
            flags.append(f"远程不清:{kw}")

    # 过泛岗位名
    if re.fullmatch(r"(实习生|实习|专员|助理)", re.sub(r"\s+", "", title)):
        flags.append("标题过泛")
        mass += int(mh_cfg.get("generic_title_hit", 20))

    threshold = int(mh_cfg.get("threshold_flag", 50))
    if mass >= threshold and "海量风险" not in flags:
        flags.append("海量风险")

    # 去重保序
    flags = list(dict.fromkeys(flags))
    return flags, mass


def dedupe_same_company_role(
    jobs: list[dict[str, Any]], categories: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    dropped = 0
    ordered = sorted(jobs, key=lambda j: (-get_score(j), get_title(j)))
    for j in ordered:
        company = get_company(j) or "未知公司"
        role = normalize_role_category(get_title(j), categories)
        key = (company, role)
        if key not in best:
            best[key] = j
        else:
            dropped += 1
    kept = list(best.values())
    kept.sort(key=lambda j: (-get_score(j), get_title(j)))
    return kept, dropped


def render_browse_md(run_id: str, jobs: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    buckets_cfg = profile.get("buckets") or {}
    pmin = int(buckets_cfg.get("priority_min", 40))
    tmin = int(buckets_cfg.get("try_min", 15))
    top = [j for j in jobs if get_score(j) >= pmin]
    mid = [j for j in jobs if tmin <= get_score(j) < pmin]
    other = [j for j in jobs if get_score(j) < tmin]

    lines = [
        f"# 人工浏览 · {run_id}",
        "",
        f"共 {len(jobs)} 条（过滤后）。优先对照链接确认是否仍招、是否真远程。",
        "",
        f"画像：{profile.get('summary') or ''}",
        "",
    ]

    def section(title: str, items: list[dict[str, Any]]) -> None:
        lines.append(f"## {title}（{len(items)}）")
        lines.append("")
        if not items:
            lines.append("暂无")
            lines.append("")
            return
        for i, j in enumerate(items, 1):
            title_j = get_title(j)
            link = clean_text(j.get("link") or "")
            lines.append(f"### {i}. [{title_j}]({link})" if link else f"### {i}. {title_j}")
            lines.append(
                f"- 平台：{j.get('platform')}｜公司：{get_company(j)}｜城市：{j.get('city') or ''}｜学历：{j.get('degree') or ''}"
            )
            lines.append(
                f"- 薪资：{j.get('salary_text') or ''}｜匹配分：{get_score(j)}｜海量分：{j.get('mass_hire_score') or 0}"
            )
            lines.append(f"- 匹配说明：{j.get('match_reason') or ''}")
            flags = j.get("risk_flags") or []
            if flags:
                lines.append(f"- 风险：{' / '.join(flags)}")
            tags = get_tags(j)
            if tags:
                lines.append(f"- 标签：{' / '.join(tags)}")
            if link:
                lines.append(f"- 链接：{link}")
            lines.append("")

    section(f"优先投递（≥{pmin}）", top)
    section(f"可尝试（{tmin}–{pmin - 1}）", mid)
    section(f"其他（<{tmin}）", other)
    return "\n".join(lines)


def shortlist_is_empty(path: Path) -> bool:
    if not path.exists():
        return True
    rows = load_jsonl(path)
    return len(rows) == 0


def run(run_id: str, batch: Path) -> int:
    rules = load_filter_rules()
    profile = load_profile()
    scored_path = batch / "02_已打分.jsonl"
    rows = load_jsonl(scored_path)
    print(f"[过滤] 输入 {len(rows)}", flush=True)

    kept: list[dict[str, Any]] = []
    dropped = 0
    for j in rows:
        bad, why = hard_exclude(j, rules)
        if bad:
            dropped += 1
            continue
        flags, mass = risk_and_mass(j, rules)
        j = dict(j)
        j["risk_flags"] = flags
        j["mass_hire_score"] = mass
        if not j.get("title") and j.get("name"):
            j["title"] = j["name"]
        kept.append(j)

    cats = rules.get("role_categories") or []
    kept, deduped = dedupe_same_company_role(kept, cats)
    print(f"[过滤] 硬过滤剔除 {dropped}；同公司同类去重 {deduped}；保留 {len(kept)}", flush=True)

    filtered_path = batch / "03_已过滤.jsonl"
    write_jsonl(filtered_path, kept)
    md_path = batch / "03_人工浏览.md"
    md_path.write_text(render_browse_md(run_id, kept, profile), encoding="utf-8")

    short_path = batch / "04_短名单.jsonl"
    if shortlist_is_empty(short_path):
        write_jsonl(short_path, kept)
        print(f"[过滤] 短名单为空，已初建 ← 过滤结果（{len(kept)}）", flush=True)
    else:
        print("[过滤] 短名单非空，不覆盖人工精选", flush=True)

    print(f"[过滤] wrote {filtered_path.name} + {md_path.name}", flush=True)
    return len(kept)


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    run_id, batch = 解析或要求批号(argv)
    run(run_id, batch)


if __name__ == "__main__":
    main()

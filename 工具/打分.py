# -*- coding: utf-8 -*-
"""读取所有 01_原始_*.jsonl，按画像打分，统一写入 02_已打分.jsonl。"""
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
    get_score,
    get_tags,
    get_title,
    list_raw_jsonl,
    load_jsonl,
    load_profile,
    merge_prefer,
    dedupe_key,
    write_jsonl,
)


def score_job(job: dict[str, Any], profile: dict[str, Any]) -> tuple[int, str]:
    kws = profile.get("keywords") or {}
    weights = profile.get("score_weights") or {}
    w_high = int(weights.get("high", 30))
    w_mid = int(weights.get("mid", 12))
    w_low = int(weights.get("low", -8))

    title = get_title(job)
    company = get_company(job)
    tags = get_tags(job)
    blob = " ".join(
        [
            title,
            company,
            clean_text(job.get("industry")),
            " ".join(tags),
            clean_text(job.get("source_keyword")),
        ]
    )
    reasons: list[str] = []
    score = 0

    for kw in kws.get("high") or []:
        if kw and kw.lower() in blob.lower():
            score += w_high
            reasons.append(f"高匹配:{kw}")
    for kw in kws.get("mid") or []:
        if kw and kw.lower() in blob.lower():
            score += w_mid
            reasons.append(f"可做:{kw}")
    for kw in kws.get("low") or []:
        if kw and kw.lower() in blob.lower():
            score += w_low
            reasons.append(f"偏远:{kw}")

    if any("大一" in t or "大二" in t for t in tags):
        score += int(weights.get("accept_freshman_sophomore", 15))
        reasons.append("接受大一大二")
    if any("远程" in t for t in tags) or job.get("remote"):
        score += int(weights.get("explicit_remote", 10))
        reasons.append("明确远程")
    if any("可转正" in t for t in tags):
        score += int(weights.get("can_convert", 5))
        reasons.append("可转正")
    if "无薪" in title:
        score += int(weights.get("unpaid", -20))
        reasons.append("无薪")

    return score, "；".join(dict.fromkeys(reasons)) or "一般相关"


def run(batch: Path) -> int:
    profile = load_profile()
    raw_files = list_raw_jsonl(batch)
    scored: list[dict[str, Any]] = []
    for path in raw_files:
        rows = load_jsonl(path)
        print(f"[打分] 读取 {path.name}: {len(rows)}", flush=True)
        for job in rows:
            s, reason = score_job(job, profile)
            job = dict(job)
            job["match_score"] = s
            job["match_reason"] = reason
            if not job.get("title") and job.get("name"):
                job["title"] = job["name"]
            scored.append(job)

    # 同批内先按去重键合并（采集阶段可能跨关键词重复）
    merged: dict[str, dict[str, Any]] = {}
    for j in scored:
        key = dedupe_key(j)
        if key not in merged:
            merged[key] = j
        else:
            merged[key] = merge_prefer(merged[key], j)

    out_rows = list(merged.values())
    out_rows.sort(key=lambda j: (-get_score(j), get_title(j)))
    out = batch / "02_已打分.jsonl"
    n = write_jsonl(out, out_rows)
    print(f"[打分] wrote {n} → {out}", flush=True)
    return n


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    _run_id, batch = 解析或要求批号(argv)
    run(batch)


if __name__ == "__main__":
    main()

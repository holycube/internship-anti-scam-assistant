# -*- coding: utf-8 -*-
"""跨平台幂等合并：按规范 URL 或 公司+标题 去重，写回 02_已打分.jsonl。"""
from __future__ import annotations

import sys
from pathlib import Path

_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 解析或要求批号  # noqa: E402
from 岗位公共 import (  # noqa: E402
    dedupe_key,
    ensure_utf8_stdio,
    get_score,
    get_title,
    load_jsonl,
    merge_prefer,
    write_jsonl,
)


def run(batch: Path) -> int:
    path = batch / "02_已打分.jsonl"
    rows = load_jsonl(path)
    before = len(rows)
    merged: dict[str, dict] = {}
    for j in rows:
        key = dedupe_key(j)
        if key not in merged:
            merged[key] = j
        else:
            merged[key] = merge_prefer(merged[key], j)
    out_rows = list(merged.values())
    out_rows.sort(key=lambda j: (-get_score(j), get_title(j)))
    n = write_jsonl(path, out_rows)
    print(f"[合并] {before} → {n}（去重 {before - n}）→ {path}", flush=True)
    return n


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    _run_id, batch = 解析或要求批号(argv)
    run(batch)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""按用户要求二次过滤已有岗位文档。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT))
from scrape_shixiseng import (  # noqa: E402
    Job,
    dedupe_same_company_role,
    render_html,
    render_md,
    should_exclude_item,
)


def main() -> None:
    path = OUT / "远程实习岗位_实习僧.json"
    jobs = json.loads(path.read_text(encoding="utf-8"))
    print(f"before={len(jobs)}")

    kept, dropped = [], []
    for j in jobs:
        bad, why = should_exclude_item(
            j, name=j.get("name") or "", company=j.get("company") or ""
        )
        if bad:
            dropped.append((why, j.get("name")))
        else:
            kept.append(j)

    print(f"after_exclude={len(kept)} dropped={len(dropped)}")
    print("exclude reasons:", Counter(w for w, _ in dropped).most_common(20))
    for w, n in dropped[:30]:
        print(f"  - {w} | {n}")

    kept, deduped = dedupe_same_company_role(kept)
    print(f"after_dedupe={len(kept)} deduped={len(deduped)}")
    for c, role, name in deduped[:40]:
        print(f"  - {c} | {role} | {name}")

    path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    objs = [Job(**j) for j in kept]
    (OUT / "远程实习岗位_实习僧.html").write_text(render_html(objs), encoding="utf-8")
    (OUT / "远程实习岗位_实习僧.md").write_text(render_md(objs), encoding="utf-8")
    top = sum(1 for j in kept if j["match_score"] >= 40)
    mid = sum(1 for j in kept if 15 <= j["match_score"] < 40)
    print(f"buckets top={top} mid={mid} other={len(kept) - top - mid}")


if __name__ == "__main__":
    main()

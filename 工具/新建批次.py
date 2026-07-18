# -*- coding: utf-8 -*-
"""新建批次：无参数自动创建当天 YYYY-MM-DD-NN；支持 --批号 / --run。"""
from __future__ import annotations

import sys
from pathlib import Path

_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 下一批号, 批次目录, 解析批号参数, 校验批号  # noqa: E402
from 岗位公共 import ensure_utf8_stdio  # noqa: E402

计划模板 = """# 检索计划 · {run_id}

## 目标
- 远程优先；匹配测试/QA/自动化及可延展能力（Python、Cursor/AI、助理、数据分析）。

## 平台边界
- **实习僧**：公开 API 采集（关键词见 `配置/数据源.json`）。
- **Boss**：不扫搜索页；仅抓取下方 `Boss待抓链接.txt` 中的详情链接。
- **拉勾**：仅公开搜索页 1–2 页；失败则空结果 + 说明，不伪造。

## 本批备注
- （人工填写检索意图、重点城市/关键词调整等）

## 流水线
1. 采集各平台 → `01_原始_*.jsonl`
2. `打分.py` → `02_已打分.jsonl`
3. （可选）`合并平台.py` 幂等去重
4. `过滤.py` → `03_已过滤.jsonl` + `03_人工浏览.md`
5. 人工筛选写入/精简 `04_短名单.jsonl`
6. `核查链接.py` 保守更新短名单
7. （可选）`企业核验.py` 联网核验短名单公司（发薪主体一致性 / 业务与任务是否错配）
8. 在 `打招呼/` 起草话术
"""

Boss链接模板 = """# 每行一个 Boss 职位详情 URL（# 开头为注释）
# 示例：
# https://www.zhipin.com/job_detail/xxxxxxxxxxxxxxxx.html
"""


def _write_if_absent(path: Path, text: str) -> str:
    if path.exists():
        return "reuse"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "create"


def _touch_empty(path: Path) -> str:
    if path.exists():
        return "reuse"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return "create"


def 初始化批次(run_id: str) -> Path:
    batch = 批次目录(run_id)
    batch.mkdir(parents=True, exist_ok=True)
    (batch / "打招呼").mkdir(parents=True, exist_ok=True)

    actions: list[tuple[str, str]] = []
    actions.append(
        (
            "00_检索计划.md",
            _write_if_absent(batch / "00_检索计划.md", 计划模板.format(run_id=run_id)),
        )
    )
    actions.append(
        (
            "Boss待抓链接.txt",
            _write_if_absent(batch / "Boss待抓链接.txt", Boss链接模板),
        )
    )
    for name in (
        "01_原始_实习僧.jsonl",
        "01_原始_Boss.jsonl",
        "01_原始_拉勾.jsonl",
        "02_已打分.jsonl",
        "03_已过滤.jsonl",
        "04_短名单.jsonl",
    ):
        actions.append((name, _touch_empty(batch / name)))

    md = batch / "03_人工浏览.md"
    if not md.exists():
        md.write_text(
            f"# 人工浏览 · {run_id}\n\n（运行 `过滤.py` 后自动生成；也可手改）\n",
            encoding="utf-8",
        )
        actions.append(("03_人工浏览.md", "create"))
    else:
        actions.append(("03_人工浏览.md", "reuse"))

    print(f"批次: {batch}")
    for name, act in actions:
        print(f"  [{act}] {name}")
    return batch


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    args = 解析批号参数(argv)
    if args.run_id:
        run_id = 校验批号(args.run_id)
    else:
        run_id = 下一批号()
    初始化批次(run_id)
    print(f"OK run_id={run_id}")


if __name__ == "__main__":
    main()

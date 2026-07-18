# -*- coding: utf-8 -*-
"""批次路径解析与批号工具。路径均基于本文件，不依赖当前工作目录。"""
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

工具目录 = Path(__file__).resolve().parent
根目录 = 工具目录.parent
配置目录 = 根目录 / "配置"
批次根目录 = 根目录 / "日期"
归档目录 = 根目录 / "归档"

批号模式 = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}$")


def 确保目录() -> None:
    配置目录.mkdir(parents=True, exist_ok=True)
    批次根目录.mkdir(parents=True, exist_ok=True)
    归档目录.mkdir(parents=True, exist_ok=True)


def 解析批号参数(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--批号", "--run", dest="run_id", default=None, help="批次号 YYYY-MM-DD-NN")
    return parser.parse_args(argv)


def 校验批号(run_id: str) -> str:
    run_id = (run_id or "").strip()
    if not 批号模式.match(run_id):
        raise ValueError(f"批号格式应为 YYYY-MM-DD-NN，收到: {run_id!r}")
    return run_id


def 下一批号(当天: date | None = None) -> str:
    当天 = 当天 or date.today()
    前缀 = 当天.strftime("%Y-%m-%d")
    已有: list[int] = []
    if 批次根目录.exists():
        for p in 批次根目录.iterdir():
            if p.is_dir() and p.name.startswith(前缀 + "-"):
                尾 = p.name[len(前缀) + 1 :]
                if 尾.isdigit():
                    已有.append(int(尾))
    nxt = (max(已有) + 1) if 已有 else 1
    return f"{前缀}-{nxt:02d}"


def 批次目录(run_id: str | None = None, *, 自动创建批号: bool = False) -> Path:
    确保目录()
    if run_id:
        rid = 校验批号(run_id)
    elif 自动创建批号:
        rid = 下一批号()
    else:
        raise ValueError("未指定批号。请传 --批号/--run，或使用 新建批次.py")
    return 批次根目录 / rid


def 解析或要求批号(argv: list[str] | None = None) -> tuple[str, Path]:
    """命令行工具通用入口：必须给出批号（或仅有一个当天批次时可扩展）。"""
    args = 解析批号参数(argv)
    if not args.run_id:
        # 若当天只有一个批次，自动选用；否则报错提示
        当天前缀 = date.today().strftime("%Y-%m-%d")
        candidates = []
        if 批次根目录.exists():
            candidates = sorted(
                p for p in 批次根目录.iterdir()
                if p.is_dir() and p.name.startswith(当天前缀 + "-")
            )
        if len(candidates) == 1:
            rid = candidates[0].name
            return rid, candidates[0]
        raise SystemExit(
            "请指定 --批号 YYYY-MM-DD-NN（也可用 --run）。"
            + (f" 当天已有: {[p.name for p in candidates]}" if candidates else "")
        )
    rid = 校验批号(args.run_id)
    path = 批次目录(rid)
    if not path.exists():
        raise SystemExit(f"批次不存在: {path}\n请先运行: python 工具/新建批次.py --批号 {rid}")
    return rid, path

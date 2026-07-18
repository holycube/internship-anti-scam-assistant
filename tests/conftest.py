# -*- coding: utf-8 -*-
"""让测试可以直接 import 工具/ 目录下的中文文件名模块。"""
from __future__ import annotations

import sys
from pathlib import Path

工具目录 = Path(__file__).resolve().parent.parent / "工具"
if str(工具目录) not in sys.path:
    sys.path.insert(0, str(工具目录))

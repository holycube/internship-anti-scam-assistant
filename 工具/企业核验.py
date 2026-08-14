# -*- coding: utf-8 -*-
"""联网核查招聘公司真实性、发薪主体一致性、业务与任务内容是否错配。

背景：真实踩坑曾出现「运营助理」岗——做了两天后发现实际发薪方与招聘展示主体
不一致，且任务（整理电商商品链接）与发薪方公开主营（如环保科技）明显不符，
联网核验后判断为高危/灰产。本脚本把这类信号固化为可复用的核查维度，
而不只是查"公司是否存在"。公开仓库不写真实主体全称。

用法：
    python 工具/企业核验.py --公司 "示例招聘展示公司|实习僧|运营助理|发薪方为另一家环保科技公司，与招聘主体不一致；任务为整理电商商品链接"
    python 工具/企业核验.py --输入文件 待核查.txt --输出 核验结果.md

--输入文件 每行一条，格式自由，建议：公司名|渠道|岗位|异常线索（没有异常线索可以省略）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_工具 = Path(__file__).resolve().parent
if str(_工具) not in sys.path:
    sys.path.insert(0, str(_工具))

from 批次路径 import 根目录  # noqa: E402
from 岗位公共 import ensure_utf8_stdio  # noqa: E402

# API Key 放在项目根目录 .env（勿提交到仓库）。也可设置环境变量 ARK_API_KEY。
ENV_CANDIDATES = [根目录 / ".env"]

PROMPT_TEMPLATE = """请先联网搜索获取最新公开信息，再回答，标注来源。逐条严格按以下格式输出，字段间用 | 分隔，不要省略字段：
公司|可信度(高/中/低/高危)|主营业务一句话|发薪主体一致性(一致/不一致/未知)|业务与任务是否匹配(匹配/错配/未知)|风险点|建议(可投/慎投/排除)

判断时重点核查这几类红线信号（这是比"公司是否存在"更关键的信号，务必逐条给出结论而不是笼统写"未知"）：
1. 发薪/合同主体与招聘展示的公司名是否一致——如果条目里说明了学生实际收到打款的公司名，请直接对比判断，一旦不一致直接判"高危"。
2. 实际任务内容与该公司公开的主营业务是否明显不符（例如环保、科技类公司却安排电商链接整理、刷单、点击任务、砍单类工作）。
3. 是否属于"整理商品链接/刷单/点击任务/砍单/领取任务佣金/关注店铺"这类常见诈骗或灰产前置信任任务——这类任务哪怕先给了小额真实报酬，也应判"高危"或"慎投"，因为常见套路是用几次小额真实转账建立信任，后续再引导垫付或升级任务。
4. 是否有诈骗、培训贷、付费实习、退费纠纷等公开投诉。

待核查条目：
"""


def load_env() -> None:
    for path in ENV_CANDIDATES:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def ask(query: str) -> str:
    load_env()
    key = os.environ["ARK_API_KEY"]
    model = os.environ.get("ARK_MODEL", "doubao-seed-2-0-lite-260215")
    base = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    body: dict = {
        "model": model,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": query}]}],
        "tools": [{"type": "web_search"}],
    }
    req = urllib.request.Request(
        f"{base}/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parts = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for c in item.get("content") or []:
            if c.get("type") == "output_text" and c.get("text"):
                parts.append(c["text"])
    return f"[model={data.get('model') or model}]\n" + (
        "\n".join(parts) or json.dumps(data, ensure_ascii=False)[:3000]
    )


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--公司", action="append", default=[], help="一条待核查条目，可重复传入")
    parser.add_argument("--输入文件", default=None, help="每行一条待核查条目的文本文件")
    parser.add_argument("--输出", default=None, help="结果输出路径；不传则打印到终端")
    args = parser.parse_args(argv)

    entries = list(args.公司)
    if args.输入文件:
        entries += [
            line.strip()
            for line in Path(args.输入文件).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if not entries:
        raise SystemExit("请用 --公司 或 --输入文件 提供至少一条待核查条目")

    query = PROMPT_TEMPLATE + "\n".join(f"- {e}" for e in entries)
    try:
        result = ask(query)
    except urllib.error.HTTPError as e:
        result = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:800]}"
    except Exception as e:
        result = f"ERR: {e}"

    if args.输出:
        Path(args.输出).write_text(result, encoding="utf-8")
        print(f"已写入 {args.输出}")
    else:
        print(result)


if __name__ == "__main__":
    main()

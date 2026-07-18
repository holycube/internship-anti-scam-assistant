# -*- coding: utf-8 -*-
"""爬取实习僧近几天远程实习岗位，并按简历匹配度整理成可跳转 HTML。"""

from __future__ import annotations

import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

BASE = "https://www.shixiseng.com"
API = f"{BASE}/app/interns/search/v2"
OUT_DIR = Path(__file__).resolve().parent
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE}/interns?k={quote('远程')}&p=1",
}

ENTITY_RE = re.compile(r"&#x([0-9a-fA-F]+);?")

PROFILE_KEYWORDS = {
    "high": [
        "测试", "QA", "质量", "自动化", "软件测试", "功能测试", "回归",
        "移动端", "Android", "Flutter", "缺陷", "用例", "真机",
    ],
    "mid": [
        "Python", "脚本", "Git", "AI", "Cursor", "产品", "助理",
        "数据分析", "文档", "运营助理", "项目助理", "Excel", "办公",
        "前端", "开发", "小程序", "自动化流程", "Agent", "业务",
        "流程", "效率", "工具", "信息化",
    ],
    "low": [
        "新媒体", "剪辑", "教培", "辅导", "主播", "销售", "客服",
    ],
}

SEARCHES = [
    {"keyword": "远程", "publishTime": "day", "sortType": "new", "pages": 5},
    {"keyword": "远程", "publishTime": "week", "sortType": "new", "pages": 10},
    {"keyword": "远程实习", "publishTime": "week", "sortType": "new", "pages": 5},
    {"keyword": "线上", "publishTime": "week", "sortType": "new", "pages": 4},
    {"keyword": "测试 远程", "publishTime": "week", "sortType": "new", "pages": 4},
    {"keyword": "软件测试", "publishTime": "week", "sortType": "new", "pages": 4},
    {"keyword": "QA", "publishTime": "week", "sortType": "new", "pages": 3},
    {"keyword": "自动化测试", "publishTime": "week", "sortType": "new", "pages": 3},
    {"keyword": "Python 远程", "publishTime": "week", "sortType": "new", "pages": 3},
    {"keyword": "AI 远程", "publishTime": "week", "sortType": "new", "pages": 3},
    {"keyword": "产品助理 远程", "publishTime": "week", "sortType": "new", "pages": 3},
    {"keyword": "数据分析 远程", "publishTime": "week", "sortType": "new", "pages": 3},
    {"keyword": "项目助理 远程", "publishTime": "week", "sortType": "new", "pages": 2},
    {"keyword": "Cursor", "publishTime": "week", "sortType": "new", "pages": 2},
]


@dataclass
class Job:
    uuid: str
    name: str
    company: str
    city: str
    industry: str
    degree: str
    minsalary: int
    maxsalary: int
    tags: list[str]
    company_tags: list[str]
    link: str
    match_score: int
    match_reason: str
    remote: bool


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = ENTITY_RE.sub("", s)
    s = re.sub(r"[\ue000-\uf8ff]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_remote(item: dict[str, Any]) -> bool:
    tags = [clean_text(t) for t in (item.get("i_tags") or [])]
    name = clean_text(item.get("name"))
    blob = " ".join(tags + [name])
    keys = ["远程", "线上", "在家", "居家", "SOHO", "soho", "不坐班"]
    return any(k in blob for k in keys)


# 短视频 / 留学限定 / 小语种 / 严格专业限制 / AI视频生成 / 种草
SHORT_VIDEO_KW = ("抖音", "短视频", "快手", "视频号", "TikTok", "tiktok")
AI_VIDEO_KW = ("AI视频生成", "AI视频", "视频生成", "AIGC视频", "文生视频", "图生视频")
ZHONGCAO_KW = ("种草专员", "种草官", "种草实习", "种草")
MINOR_LANG_KW = (
    "小语种",
    "日语", "韩语", "法语", "德语", "西班牙语", "俄语",
    "阿拉伯语", "意大利语", "葡萄牙语", "泰语", "越南语", "印尼语", "马来语",
    "蒙古语", "荷兰语", "瑞典语", "波兰语", "土耳其语", "希伯来语",
)
STRICT_MAJOR_KW = (
    "医学图像", "医学专业", "临床医学", "法学专业", "财会专业",
    "土木工程专业", "生物专业", "化学专业", "材料专业", "航空航天",
    "仅限", "限报", "必须", "只招", "理工科",
)
LANG_IN_BRACKET_RE = re.compile(
    r"[（【](?:日语|韩语|法语|德语|西班牙语|俄语|阿拉伯语|意大利语|葡萄牙语|泰语|越南语|印尼语|马来语|小语种)[）】]"
)

# 同公司同类去重时的角色归类（按优先级匹配）
ROLE_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("软件测试", ("软件测试", "测试开发", "自动化测试", "QA", "质量保证")),
    ("测试", ("测试",)),
    ("数据分析", ("数据分析", "数据统计", "数据标注", "数据采集")),
    ("产品助理", ("产品助理", "产品经理", "产品实习", "产品运营")),
    ("项目助理", ("项目助理", "项目运营", "项目实习")),
    ("HR招聘", ("HRBP", "招聘", "人事")),
    ("开发工程", ("开发", "工程师", "前端", "后端", "全栈", "算法")),
    ("内容运营", ("内容运营", "内容策划", "文案", "转化文案")),
    ("新媒体运营", ("新媒体运营", "新媒体", "社媒", "社交媒")),
    ("小红书运营", ("小红书",)),
    ("用户运营", ("用户运营", "用户增长")),
    ("增长运营", ("增长运营", "增长")),
    ("海外运营", ("海外运营", "出海")),
    ("运营助理", ("运营助理", "运营实习", "运营")),
    ("市场商务", ("市场", "商务", "BD", "销售")),
    ("视觉设计", ("视觉", "设计", "UI", "UX")),
    ("广告投放", ("广告测试", "投放", "营销")),
]


def normalize_role_category(name: str) -> str:
    """把岗位名归到同公司可去重的角色类别。"""
    n = clean_text(name)
    # 去掉城市/紧急/远程等噪声，方便同类合并
    n = re.sub(
        r"[（(【\[].*?[）)】\]]",
        "",
        n,
    )
    n = re.sub(
        r"(远程|线上|居家|在家|急招|急聘|急|接受应届|可转正|实习证明|时间自由|时间灵活)",
        "",
        n,
    )
    n = re.sub(r"\s+", "", n)
    for cat, kws in ROLE_CATEGORIES:
        if any(kw.lower() in n.lower() for kw in kws):
            return cat
    # 兜底：去掉常见后缀后的标准化名称
    base = re.sub(r"(实习生?|专员|助理|岗位)$", "", n)
    return base or n or "其他"


def dedupe_same_company_role(
    jobs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    """同公司 + 同类角色只保留匹配分最高的一条。"""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    dropped: list[tuple[str, str, str]] = []
    # 先按匹配分高→低，保证先留下更好的
    ordered = sorted(
        jobs,
        key=lambda j: (-int(j.get("match_score") or 0), j.get("name") or ""),
    )
    for j in ordered:
        company = (j.get("company") or j.get("cname") or "").strip() or "未知公司"
        role = normalize_role_category(j.get("name") or "")
        key = (company, role)
        if key not in best:
            best[key] = j
        else:
            dropped.append((company, role, j.get("name") or ""))
    kept = list(best.values())
    kept.sort(key=lambda j: (-int(j.get("match_score") or 0), j.get("name") or ""))
    return kept, dropped


def should_exclude_item(
    item: dict[str, Any],
    name: str = "",
    company: str = "",
) -> tuple[bool, str]:
    """返回 (是否剔除, 原因)。"""
    name = name or clean_text(item.get("name"))
    company = company or clean_text(item.get("cname") or item.get("company"))
    degree = clean_text(item.get("degree"))
    raw_tags = item.get("i_tags") or item.get("tags") or []
    tags = [clean_text(t) for t in raw_tags]
    blob = " ".join([name, company, degree, *tags])

    if any(x in degree for x in ("硕士", "博士")):
        return True, "学历硕士博士"
    if "硕士" in name or "博士" in name:
        return True, "名称含硕博"
    if "剪辑" in blob:
        return True, "剪辑"
    if "校园大使" in blob or "品牌大使" in name:
        return True, "校园大使"

    for kw in ZHONGCAO_KW:
        if kw in blob:
            return True, f"种草:{kw}"

    if any(t == "留学生实习" or "留学生实习" in t for t in tags):
        return True, "留学生实习标签"

    for kw in AI_VIDEO_KW:
        if kw in blob:
            return True, f"AI视频:{kw}"

    for kw in SHORT_VIDEO_KW:
        if kw in blob:
            return True, f"短视频:{kw}"

    # 限留学：岗位名/公司名含留学，或明确写限留学
    if "限留学" in name or "限留学" in company:
        return True, "限留学"
    if "留学" in name or "留学" in company:
        return True, "留学相关"

    for kw in MINOR_LANG_KW:
        if kw in name or kw in company:
            return True, f"小语种:{kw}"
    if LANG_IN_BRACKET_RE.search(name):
        return True, "括号语种要求"
    if re.search(r"精通(?:日语|韩语|法语|德语|西班牙语|俄语|阿拉伯语|泰语|越南语|印尼语)", name):
        return True, "精通小语种"

    for kw in STRICT_MAJOR_KW:
        if kw in name:
            return True, f"严格专业:{kw}"
    if re.search(r"(?:仅限|必须|只招).{0,8}专业", name):
        return True, "仅限/必须某专业"

    teach_en = (
        "录课", "录制师", "录题老", "英语版本课", "版本课", "英语伴学", "伴学",
        "小学英语", "教学英语", "英语教学", "在线英语", "远程英语",
        "英语老师", "英语教师", "英语老", "线上英语", "英语助教", "口语外教", "外教",
        "学课辅导", "伴学老师", "录制课", "录课师", "英语绘本", "绘本陪读", "绘本导",
        "英语口语", "少儿英语", "口语幼教", "无抗遗忘", "留学辅导", "数学英语", "数英",
    )
    for kw in teach_en:
        if kw in blob:
            return True, kw

    if "英语" in name and any(
        k in name
        for k in (
            "教学", "录制", "录课", "辅导", "老师", "教师", "助教",
            "小学", "版本", "录师", "录题", "幼教", "绘本", "陪读", "口语",
        )
    ):
        return True, "英语教学/录制"
    if ("录师" in name or "录课" in name or "录制" in name or "录题" in name) and any(
        k in name for k in ("英语", "小学", "教学", "语文", "数学", "小初", "数英")
    ):
        return True, "学科录制"
    return False, ""


def should_exclude(item: dict[str, Any], name: str = "") -> bool:
    excluded, _ = should_exclude_item(item, name=name)
    return excluded


def score_job(item: dict[str, Any], name: str) -> tuple[int, str]:
    tags = [clean_text(t) for t in (item.get("i_tags") or [])]
    blob = " ".join(
        [
            name,
            clean_text(item.get("cname")),
            clean_text(item.get("industry")),
            " ".join(tags),
        ]
    )
    reasons: list[str] = []
    score = 0
    for kw in PROFILE_KEYWORDS["high"]:
        if kw.lower() in blob.lower():
            score += 30
            reasons.append(f"高匹配:{kw}")
    for kw in PROFILE_KEYWORDS["mid"]:
        if kw.lower() in blob.lower():
            score += 12
            reasons.append(f"可做:{kw}")
    for kw in PROFILE_KEYWORDS["low"]:
        if kw.lower() in blob.lower():
            score -= 8
            reasons.append(f"偏远:{kw}")
    if any("大一" in t or "大二" in t for t in tags):
        score += 15
        reasons.append("接受大一大二")
    if any("远程" in t for t in tags):
        score += 10
        reasons.append("明确远程")
    if any("可转正" in t for t in tags):
        score += 5
        reasons.append("可转正")
    if "无薪" in name:
        score -= 20
        reasons.append("无薪")
    return score, "；".join(dict.fromkeys(reasons)) or "一般相关"


def fetch_page(keyword: str, page: int, publish_time: str, sort_type: str) -> list[dict]:
    params = {
        "keyword": keyword,
        "page": page,
        "pageSize": 20,
        "city": "",
        "type": "intern",
        "sortType": sort_type,
        "publishTime": publish_time,
    }
    r = requests.get(API, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    msg = data.get("msg") or {}
    if isinstance(msg, dict):
        return msg.get("data") or []
    return []


def enrich_name_from_detail(uuid: str) -> str | None:
    url = f"{BASE}/intern/{uuid}"
    try:
        r = requests.get(
            url,
            headers={**HEADERS, "Accept": "text/html"},
            timeout=8,
        )
        r.encoding = "utf-8"
        m = re.search(r"<title>(.*?)</title>", r.text, re.I | re.S)
        if not m:
            return None
        title = html.unescape(m.group(1)).strip()
        title = re.split(r"实习招聘|实习生招聘|-实习僧", title)[0].strip(" -_|")
        return title or None
    except Exception:
        return None


def collect_jobs() -> list[Job]:
    seen: set[str] = set()
    jobs: list[Job] = []
    for cfg in SEARCHES:
        keyword = cfg["keyword"]
        for page in range(1, cfg["pages"] + 1):
            print(f"[fetch] {keyword} page={page} publishTime={cfg['publishTime']}", flush=True)
            try:
                items = fetch_page(keyword, page, cfg["publishTime"], cfg["sortType"])
            except Exception as e:
                print(f"  ! error: {e}", flush=True)
                time.sleep(1.2)
                continue
            if not items:
                print("  empty, stop paging", flush=True)
                break
            for item in items:
                uuid = item.get("uuid") or ""
                if not uuid or uuid in seen:
                    continue
                if not is_remote(item):
                    continue
                raw_name = clean_text(item.get("name"))
                if should_exclude(item, raw_name):
                    continue
                seen.add(uuid)
                score, reason = score_job(item, raw_name)
                jobs.append(
                    Job(
                        uuid=uuid,
                        name=raw_name or uuid,
                        company=clean_text(item.get("cname")),
                        city=clean_text(item.get("city")),
                        industry=clean_text(item.get("industry")),
                        degree=clean_text(item.get("degree")),
                        minsalary=int(item.get("minsalary") or 0),
                        maxsalary=int(item.get("maxsalary") or 0),
                        tags=[clean_text(t) for t in (item.get("i_tags") or [])],
                        company_tags=[clean_text(t) for t in (item.get("c_tags") or [])],
                        link=f"{BASE}/intern/{uuid}",
                        match_score=score,
                        match_reason=reason,
                        remote=True,
                    )
                )
            time.sleep(0.3)
    jobs.sort(key=lambda j: (-j.match_score, j.name))
    return jobs


def repair_names(jobs: list[Job], limit: int = 35) -> None:
    targets = [j for j in jobs if j.match_score >= 15][:limit]
    print(f"[enrich] parallel repair {len(targets)} names", flush=True)
    if not targets:
        return

    def work(j: Job) -> tuple[Job, str | None]:
        return j, enrich_name_from_detail(j.uuid)

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(work, j) for j in targets]
        for fut in as_completed(futs):
            try:
                j, detail = fut.result()
            except Exception:
                continue
            if detail and len(detail) >= max(4, len(j.name) - 2):
                j.name = detail
                # 名称补全后重算匹配分
                fake_item = {
                    "cname": j.company,
                    "industry": j.industry,
                    "i_tags": j.tags,
                    "minsalary": j.minsalary,
                    "maxsalary": j.maxsalary,
                }
                j.match_score, j.match_reason = score_job(fake_item, j.name)
                print(f"  + {j.name} ({j.match_score})", flush=True)


def salary_text(j: Job) -> str:
    if j.minsalary == 0 and j.maxsalary == 0:
        return "薪资面议/未标注"
    if j.minsalary and j.maxsalary:
        return f"{j.minsalary}-{j.maxsalary}元/天"
    return f"{j.maxsalary or j.minsalary}元/天"


def render_html(jobs: list[Job]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    top = [j for j in jobs if j.match_score >= 40]
    mid = [j for j in jobs if 15 <= j.match_score < 40]
    other = [j for j in jobs if j.match_score < 15]

    def section(title: str, items: list[Job], note: str) -> str:
        if not items:
            return f"<h2>{html.escape(title)}</h2><p class='muted'>暂无</p>"
        rows = []
        for i, j in enumerate(items, 1):
            tags = " ".join(f"<span class='tag'>{html.escape(t)}</span>" for t in j.tags[:8])
            rows.append(
                f"""
<article class="card">
  <div class="idx">{i}</div>
  <div class="body">
    <h3><a href="{html.escape(j.link)}" target="_blank" rel="noopener">{html.escape(j.name)}</a></h3>
    <p class="meta">{html.escape(j.company)} · {html.escape(j.city)} · {html.escape(j.industry)} · {html.escape(j.degree)}</p>
    <p class="meta">{html.escape(salary_text(j))} · 匹配分 <strong>{j.match_score}</strong></p>
    <p class="reason">{html.escape(j.match_reason)}</p>
    <div class="tags">{tags}</div>
    <p class="link"><a href="{html.escape(j.link)}" target="_blank" rel="noopener">打开实习僧岗位页 →</a></p>
  </div>
</article>"""
            )
        return (
            f"<h2>{html.escape(title)} <span class='count'>({len(items)})</span></h2>"
            f"<p class='muted'>{html.escape(note)}</p>"
            + "".join(rows)
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>实习僧远程实习岗位精选 · {now}</title>
<style>
  :root {{
    --bg: #f6f3ee;
    --ink: #1c1a17;
    --muted: #6b645c;
    --accent: #0f6e56;
    --card: #fffdf9;
    --line: #e4ddd2;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background:
      radial-gradient(1200px 500px at 10% -10%, #d9efe6 0%, transparent 55%),
      radial-gradient(900px 400px at 100% 0%, #f0e6d4 0%, transparent 50%),
      var(--bg);
    color: var(--ink); line-height: 1.55;
  }}
  main {{ max-width: 920px; margin: 0 auto; padding: 32px 20px 64px; }}
  h1 {{ font-size: 1.75rem; margin: 0 0 8px; letter-spacing: .02em; }}
  h2 {{ margin-top: 36px; border-bottom: 2px solid var(--accent); padding-bottom: 6px; }}
  .count {{ color: var(--muted); font-weight: 500; font-size: .9em; }}
  .lead, .muted {{ color: var(--muted); }}
  .profile {{
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 16px 18px; margin: 18px 0 8px;
  }}
  .card {{
    display: grid; grid-template-columns: 40px 1fr; gap: 8px 12px;
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 14px 16px; margin: 12px 0;
  }}
  .idx {{
    width: 32px; height: 32px; border-radius: 999px; background: #e7f4ef;
    color: var(--accent); display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: .85rem;
  }}
  h3 {{ margin: 0 0 6px; font-size: 1.05rem; }}
  h3 a {{ color: var(--ink); text-decoration: none; }}
  h3 a:hover {{ color: var(--accent); text-decoration: underline; }}
  .meta {{ margin: 2px 0; color: var(--muted); font-size: .92rem; }}
  .reason {{ margin: 6px 0; font-size: .9rem; }}
  .tag {{
    display: inline-block; background: #eef7f3; color: #0b5a46;
    border-radius: 6px; padding: 2px 8px; margin: 2px 4px 2px 0; font-size: .78rem;
  }}
  .link a {{ color: var(--accent); font-weight: 600; }}
  footer {{ margin-top: 40px; color: var(--muted); font-size: .85rem; }}
</style>
</head>
<body>
<main>
  <h1>实习僧 · 近一周可远程实习岗位</h1>
  <p class="lead">生成时间：{html.escape(now)} · 共收录 <strong>{len(jobs)}</strong> 个明确含远程/线上标签的岗位</p>
  <div class="profile">
    <strong>匹配画像（示例用户）</strong>
    <p class="muted" style="margin:6px 0 0">
      优先：软件测试 / QA / 移动端自动化 / Flutter·Android 真机验证；
      可扩展：Python 脚本、Cursor/AI 辅助业务、Excel 办公、产品/项目助理、数据分析辅助。
      形式：远程；大二；每周约 3–4 天亦可。
    </p>
  </div>
  {section("优先投递（与测试/QA/自动化/开发相关）", top, "匹配分 ≥ 40，建议优先点开投递")}
  {section("可尝试（办公/助理/AI/数据分析等能力可覆盖）", mid, "匹配分 15–39，说明能力可延展到这些业务")}
  {section("其他远程岗位（供浏览，匹配较低）", other, "多为新媒体/剪辑等，仅作备选")}
  <footer>
    数据来源：实习僧公开搜索接口（publishTime=day/week）。岗位更新快，投递前请再确认是否仍招、是否真远程。
    字体反爬导致个别岗位名可能缺字，请以链接详情页为准。
  </footer>
</main>
</body>
</html>
"""


def render_md(jobs: list[Job]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 实习僧 · 近一周可远程实习岗位",
        "",
        f"生成时间：{now} · 共 {len(jobs)} 个岗位",
        "",
        "## 匹配画像",
        "优先测试/QA/移动端自动化；可扩展 Python、Cursor/AI、Excel、产品助理、数据分析。",
        "",
    ]
    buckets = [
        ("优先投递", [j for j in jobs if j.match_score >= 40]),
        ("可尝试", [j for j in jobs if 15 <= j.match_score < 40]),
        ("其他远程", [j for j in jobs if j.match_score < 15]),
    ]
    for title, items in buckets:
        lines.append(f"## {title}（{len(items)}）")
        lines.append("")
        if not items:
            lines.append("暂无")
            lines.append("")
            continue
        for i, j in enumerate(items, 1):
            lines.append(f"### {i}. [{j.name}]({j.link})")
            lines.append(
                f"- 公司：{j.company}｜城市：{j.city}｜行业：{j.industry}｜学历：{j.degree}"
            )
            lines.append(f"- 薪资：{salary_text(j)}｜匹配分：{j.match_score}")
            lines.append(f"- 匹配说明：{j.match_reason}")
            if j.tags:
                lines.append(f"- 标签：{' / '.join(j.tags)}")
            lines.append(f"- 链接：{j.link}")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    jobs = collect_jobs()
    print(f"[collect] remote jobs={len(jobs)}", flush=True)

    html_path = OUT_DIR / "远程实习岗位_实习僧.html"
    md_path = OUT_DIR / "远程实习岗位_实习僧.md"
    json_path = OUT_DIR / "远程实习岗位_实习僧.json"

    # 先落盘一份，避免补全失败导致无文档
    html_path.write_text(render_html(jobs), encoding="utf-8")
    md_path.write_text(render_md(jobs), encoding="utf-8")
    json_path.write_text(
        json.dumps([asdict(j) for j in jobs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[draft] wrote preliminary docs", flush=True)

    repair_names(jobs, limit=35)
    as_dicts = [asdict(j) for j in jobs]
    as_dicts, deduped = dedupe_same_company_role(as_dicts)
    print(f"[dedupe] removed {len(deduped)} same-company/same-role", flush=True)
    jobs = [Job(**d) for d in as_dicts]
    jobs.sort(key=lambda x: (-x.match_score, x.name))

    html_path.write_text(render_html(jobs), encoding="utf-8")
    md_path.write_text(render_md(jobs), encoding="utf-8")
    json_path.write_text(
        json.dumps([asdict(j) for j in jobs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OK jobs={len(jobs)}", flush=True)
    print(f"HTML: {html_path}", flush=True)
    print(f"MD:   {md_path}", flush=True)
    print(f"JSON: {json_path}", flush=True)
    print("TOP8:", flush=True)
    for j in jobs[:8]:
        print(f"  [{j.match_score}] {j.name} | {j.company} | {j.link}", flush=True)


if __name__ == "__main__":
    main()

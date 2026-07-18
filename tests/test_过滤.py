# -*- coding: utf-8 -*-
"""覆盖 工具/过滤.py 的硬过滤、风险标记与同公司同类去重逻辑。"""
from __future__ import annotations

from 过滤 import dedupe_same_company_role, hard_exclude, normalize_role_category, risk_and_mass

RULES = {
    "hard_exclude": {
        "degree_keywords": ["研究生", "硕士", "博士"],
        "name_degree_keywords": ["研究生", "硕士", "博士"],
        "blob_keywords": ["剪辑", "校园大使", "品牌大使", "数据标注"],
        "zhongcao": ["种草专员", "种草官"],
        "ai_video": ["AI视频生成", "文生视频"],
        "short_video": ["抖音", "短视频"],
        "study_abroad": ["限留学", "留学"],
        "minor_languages": ["日语", "韩语"],
        "strict_major": ["仅限", "必须", "只招"],
        "teach_english": ["英语老师", "外教"],
        "study_abroad_tag": "留学生实习",
    },
    "risk_flags": {
        "mass_hire_title_keywords": ["批量", "大量招聘", "急招多人"],
        "agency_keywords": ["外包", "劳务派遣", "代招"],
        "unclear_remote_keywords": ["可协商", "视情况"],
    },
    "mass_hire": {
        "title_hit": 40,
        "agency_hit": 30,
        "generic_title_hit": 20,
        "threshold_flag": 50,
    },
    "role_categories": [
        {"name": "知识库运维", "keywords": ["知识库", "Notion", "语雀"]},
        {"name": "运营助理", "keywords": ["运营助理", "运营"]},
    ],
}


def make_job(**kwargs) -> dict:
    job = {"title": "运营助理", "company": "示例公司", "degree": "本科", "tags": []}
    job.update(kwargs)
    return job


def test_hard_exclude_by_degree():
    job = make_job(degree="硕士")
    bad, why = hard_exclude(job, RULES)
    assert bad is True
    assert "学历" in why


def test_hard_exclude_by_blob_keyword():
    job = make_job(title="视频剪辑实习生")
    bad, why = hard_exclude(job, RULES)
    assert bad is True
    assert why == "剪辑"


def test_hard_exclude_by_study_abroad_tag():
    job = make_job(tags=["留学生实习"])
    bad, why = hard_exclude(job, RULES)
    assert bad is True
    assert "留学生实习" in why


def test_hard_exclude_minor_language_in_bracket():
    # RULES["hard_exclude"]["minor_languages"] 只列了日语/韩语，法语只能靠括号正则兜底命中
    job = make_job(title="运营助理【法语】")
    bad, why = hard_exclude(job, RULES)
    assert bad is True
    assert why == "括号语种要求"


def test_hard_exclude_passes_normal_job():
    job = make_job(title="AI知识库运维实习生")
    bad, why = hard_exclude(job, RULES)
    assert bad is False
    assert why == ""


def test_risk_flags_mass_hire_and_agency():
    job = make_job(title="批量招聘运营助理", company="某劳务派遣公司")
    flags, mass = risk_and_mass(job, RULES)
    assert any("海量招聘" in f for f in flags)
    assert any("中介嫌疑" in f for f in flags)
    assert "海量风险" in flags
    assert mass >= 50


def test_risk_flags_generic_title_is_flagged():
    job = make_job(title="助理")
    flags, _mass = risk_and_mass(job, RULES)
    assert "标题过泛" in flags


def test_normalize_role_category_strips_noise_words():
    cats = RULES["role_categories"]
    assert normalize_role_category("远程知识库运维实习生（可转正）", cats) == "知识库运维"
    assert normalize_role_category("运营助理", cats) == "运营助理"


def test_dedupe_same_company_role_keeps_highest_score():
    jobs = [
        make_job(title="运营助理A", company="公司A", match_score=20),
        make_job(title="运营助理B", company="公司A", match_score=50),
        make_job(title="知识库运维", company="公司A", match_score=10),
    ]
    kept, dropped = dedupe_same_company_role(jobs, RULES["role_categories"])
    assert dropped == 1
    titles = {j["title"] for j in kept}
    assert "运营助理B" in titles
    assert "运营助理A" not in titles
    assert "知识库运维" in titles

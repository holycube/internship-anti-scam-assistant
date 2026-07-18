# -*- coding: utf-8 -*-
"""覆盖 工具/打分.py 的核心打分逻辑（score_job）。"""
from __future__ import annotations

import pytest

from 打分 import score_job

PROFILE = {
    "keywords": {
        "high": ["知识库", "Agent", "AI"],
        "mid": ["运营助理", "文档"],
        "low": ["新媒体", "剪辑"],
    },
    "score_weights": {
        "high": 30,
        "mid": 12,
        "low": -8,
        "accept_freshman_sophomore": 15,
        "explicit_remote": 10,
        "can_convert": 5,
        "unpaid": -20,
    },
}


def make_job(**kwargs) -> dict:
    job = {
        "title": "运营助理",
        "company": "示例公司",
        "tags": [],
        "industry": "",
        "source_keyword": "",
        "remote": False,
    }
    job.update(kwargs)
    return job


def test_high_keyword_hits_and_reason():
    job = make_job(title="知识库运维实习生")
    score, reason = score_job(job, PROFILE)
    assert score == 30
    assert "高匹配:知识库" in reason


def test_mid_and_low_keywords_combine():
    job = make_job(title="运营助理（新媒体方向）")
    score, _reason = score_job(job, PROFILE)
    # mid: 运营助理(+12) ；low: 新媒体(-8)
    assert score == 12 - 8


def test_explicit_remote_and_freshman_bonus_from_tags():
    job = make_job(title="其他岗位", tags=["远程", "大二可投"])
    score, reason = score_job(job, PROFILE)
    assert score == 15 + 10
    assert "接受大一大二" in reason
    assert "明确远程" in reason


def test_remote_flag_true_also_scores_bonus():
    job = make_job(title="其他岗位", remote=True)
    score, reason = score_job(job, PROFILE)
    assert score == 10
    assert "明确远程" in reason


def test_unpaid_penalty_applies():
    job = make_job(title="无薪实习生（知识库）")
    score, reason = score_job(job, PROFILE)
    # high: 知识库(+30) + unpaid(-20)
    assert score == 30 - 20
    assert "无薪" in reason


def test_no_match_returns_zero_and_default_reason():
    job = make_job(title="完全不相关的岗位名称")
    score, reason = score_job(job, PROFILE)
    assert score == 0
    assert reason == "一般相关"


@pytest.mark.parametrize("kw", ["知识库", "Agent", "AI"])
def test_each_high_keyword_is_case_insensitive(kw):
    job = make_job(title=f"远程{kw.lower()}实习")
    score, _reason = score_job(job, PROFILE)
    assert score >= 30

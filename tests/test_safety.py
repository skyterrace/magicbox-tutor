from __future__ import annotations

from magicbox_tutor.safety import check_user_text


def test_self_harm_short_circuit() -> None:
    reply = check_user_text("我不想活了")
    assert reply is not None
    assert reply.category == "self_harm"
    assert "大人" in reply.text


def test_abuse_short_circuit() -> None:
    reply = check_user_text("妈妈打我")
    assert reply is not None
    assert reply.category == "abuse"
    assert "不是你的错" in reply.text


def test_danger_short_circuit() -> None:
    reply = check_user_text("厨房着火了")
    assert reply is not None
    assert reply.category == "danger"
    assert "119" in reply.text


def test_normal_school_question_is_not_blocked() -> None:
    assert check_user_text("我想学分数怎么比较大小") is None
    assert check_user_text("今天数学作业有一道题不会") is None

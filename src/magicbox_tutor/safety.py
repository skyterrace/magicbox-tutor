"""Small, deterministic safety layer for a primary-school voice assistant.

This is deliberately not a classifier.  It catches a narrow set of high-risk
phrases before they reach the model, so the device always answers with a calm,
adult-help instruction instead of improvising.  The model still receives its
own safety persona for everything else.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyReply:
    category: str
    text: str


_SELF_HARM = (
    "自杀",
    "不想活",
    "活不下去",
    "死了算了",
    "割腕",
    "跳楼",
    "自残",
    "伤害自己",
)

_ABUSE = (
    "打我",
    "揍我",
    "虐待",
    "猥亵",
    "摸我",
    "脱我衣服",
    "不让我吃饭",
)

_DANGER = (
    "着火了",
    "火灾",
    "煤气泄漏",
    "触电",
    "有人闯进来",
    "陌生人敲门",
    "溺水",
)

_CRISIS_TEXT = (
    "听起来你现在很不容易。请马上告诉身边的爸爸妈妈、老师，"
    "或者你信任的大人，让他们陪着你。如果有危险，请拨打 110 或 120。"
)

_ABUSE_TEXT = (
    "这不是你的错。请马上告诉你信任的大人，比如爸爸妈妈、老师，"
    "让他们保护你。如果你现在不安全，请拨打 110。"
)

_DANGER_TEXT = (
    "这件事很危险。先离开危险的地方，马上找身边的大人帮忙。"
    "有火情或有人受伤，请拨打 119、110 或 120。"
)


def check_user_text(text: str) -> SafetyReply | None:
    """Return a fixed reply for a high-risk phrase, otherwise ``None``."""

    normalized = "".join(str(text).split())
    if not normalized:
        return None

    if any(word in normalized for word in _SELF_HARM):
        return SafetyReply("self_harm", _CRISIS_TEXT)
    if any(word in normalized for word in _ABUSE):
        return SafetyReply("abuse", _ABUSE_TEXT)
    if any(word in normalized for word in _DANGER):
        return SafetyReply("danger", _DANGER_TEXT)
    return None

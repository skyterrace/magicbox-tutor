"""Conversation policy: normalization, reset commands, safety, then the agent."""

from __future__ import annotations

import logging
import re

from .agent import AgentError, TutorAgent
from .config import BehaviorConfig
from .safety import check_user_text


class DialogError(RuntimeError):
    """Raised when a turn cannot produce a useful answer."""


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_user_text(text: str, wake_word: str = "") -> str:
    """Clean an ASR result without changing its meaning."""

    value = _WHITESPACE_RE.sub(" ", str(text or "")).strip()
    value = value.strip("，,。.!！?？；;：:")
    if wake_word and value.startswith(wake_word):
        value = value[len(wake_word) :].lstrip("，,。.!！?？；;：: ")
    return value.strip()


class Dialog:
    def __init__(
        self,
        agent: TutorAgent,
        behavior: BehaviorConfig,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._agent = agent
        self._behavior = behavior
        self._logger = logger or logging.getLogger(__name__)

    @property
    def agent(self) -> TutorAgent:
        return self._agent

    def respond(self, text: str) -> str:
        question = normalize_user_text(text, self._behavior.wake_word)
        if not question:
            return ""

        safety = check_user_text(question)
        if safety is not None:
            self._logger.info("安全短路径: %s", safety.category)
            return safety.text

        if self._is_reset(question):
            self._agent.reset()
            return "好，我们重新开始。你想学什么？"

        try:
            answer = self._agent.ask(question)
        except AgentError as exc:
            self._logger.error("Agent 未能回答: %s", exc)
            raise DialogError(str(exc)) from exc

        answer = str(answer or "").strip()
        if not answer:
            raise DialogError("Agent 返回空内容")
        return answer

    def _is_reset(self, text: str) -> bool:
        compact = text.replace(" ", "")
        for phrase in self._behavior.reset_phrases:
            phrase = str(phrase).replace(" ", "")
            if compact == phrase:
                return True
            if compact.startswith(phrase) and len(compact) <= len(phrase) + 4:
                return True
        return False

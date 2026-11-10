from __future__ import annotations

import time
from pathlib import Path

from magicbox_tutor.agent import TutorAgent
from magicbox_tutor.config import (
    AgentConfig,
    AudioConfig,
    BehaviorConfig,
    StatusConfig,
    TutorConfig,
)
from magicbox_tutor.dialog import Dialog
from magicbox_tutor.service import TutorService
from magicbox_tutor.status import StatusWriter


class FakeSpeaker:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.ends = 0

    def say(self, text: str) -> None:
        self.messages.append(text)

    def end(self) -> None:
        self.ends += 1


class FakeAgent:
    def __init__(self, answer: str = "三加四等于七。", delay: float = 0.0) -> None:
        self.answer = answer
        self.delay = delay
        self.questions: list[str] = []
        self.resets = 0
        self.closed = False
        self.warmed = False

    @property
    def session_id(self) -> str:
        return "fake-session"

    def warmup(self) -> None:
        self.warmed = True

    def ask(self, text: str) -> str:
        self.questions.append(text)
        if self.delay:
            time.sleep(self.delay)
        return self.answer

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closed = True


def make_config(
    tmp_path: Path,
    *,
    filler_delay: float = 0.0,
    timeout: float = 2.0,
    answer_chars: int = 200,
) -> TutorConfig:
    return TutorConfig(
        agent=AgentConfig(
            dsh_home=tmp_path / "home",
            workspace=tmp_path / "work",
            system_prompt_file=tmp_path / "prompt.md",
            patch_file=tmp_path / "patch.yml",
            session_id_file=tmp_path / "state" / "session_id",
            answer_timeout_s=timeout,
        ),
        audio=AudioConfig(),
        behavior=BehaviorConfig(
            thinking_filler_delay_s=filler_delay,
            max_answer_chars=answer_chars,
            max_sentence_chars=80,
        ),
        status=StatusConfig(status_file=tmp_path / "run" / "status.json"),
    )


def make_service(tmp_path: Path, agent: TutorAgent, **kwargs) -> tuple[TutorService, FakeSpeaker]:
    config = make_config(tmp_path, **kwargs)
    speaker = FakeSpeaker()
    status = StatusWriter(config.status.status_file)
    dialog = Dialog(agent, config.behavior)
    service = TutorService(config, dialog, speaker, status=status)
    return service, speaker


def wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_turn_speaks_answer_and_end(tmp_path: Path) -> None:
    agent = FakeAgent()
    service, speaker = make_service(tmp_path, agent)
    service.start()
    assert wait_until(lambda: agent.warmed)
    assert service.submit("三加四等于几？") is True
    assert wait_until(lambda: not service.busy)
    assert agent.questions == ["三加四等于几"]
    assert speaker.messages == ["三加四等于七"]
    assert speaker.ends == 1
    service.close()


def test_busy_rejects_second_submit(tmp_path: Path) -> None:
    agent = FakeAgent(delay=0.2)
    service, speaker = make_service(tmp_path, agent)
    service.start()
    assert wait_until(lambda: agent.warmed)
    assert service.submit("第一题") is True
    assert service.submit("第二题") is False
    assert wait_until(lambda: not service.busy)
    assert agent.questions == ["第一题"]
    assert speaker.ends == 1
    service.close()


def test_filler_is_spoken_before_slow_answer(tmp_path: Path) -> None:
    agent = FakeAgent(delay=0.25)
    service, speaker = make_service(tmp_path, agent, filler_delay=0.05)
    service.start()
    assert wait_until(lambda: agent.warmed)
    service.submit("这道题怎么做？")
    assert wait_until(lambda: not service.busy)
    assert speaker.messages[0] == "让我想一想"
    assert "三加四等于七" in speaker.messages
    assert speaker.ends == 1
    service.close()


def test_timeout_speaks_fallback_and_late_answer_is_suppressed(tmp_path: Path) -> None:
    agent = FakeAgent(answer="迟到的答案。", delay=0.3)
    service, speaker = make_service(tmp_path, agent, timeout=0.05)
    service.start()
    assert wait_until(lambda: agent.warmed)
    service.submit("很难的题")
    assert wait_until(lambda: "这个问题有点难" in "".join(speaker.messages), timeout=1.0)
    assert wait_until(lambda: not service.busy, timeout=1.0)
    joined = "".join(speaker.messages)
    assert "迟到的答案" not in joined
    assert speaker.ends == 1
    service.close()


def test_reset_phrase_uses_agent_reset(tmp_path: Path) -> None:
    agent = FakeAgent()
    service, speaker = make_service(tmp_path, agent)
    service.start()
    assert wait_until(lambda: agent.warmed)
    service.submit("重新开始")
    assert wait_until(lambda: not service.busy)
    assert agent.resets == 1
    assert "我们重新开始" in "".join(speaker.messages)
    service.close()

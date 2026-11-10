from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from magicbox_tutor.agent import AgentError, DSHTutorAgent, build_harness_kwargs
from magicbox_tutor.config import AgentConfig, BehaviorConfig
from magicbox_tutor.dialog import Dialog, DialogError, normalize_user_text


class FakeAgent:
    def __init__(self) -> None:
        self.questions: list[str] = []
        self.resets = 0
        self.closed = False

    @property
    def session_id(self) -> str:
        return "fake-session"

    def warmup(self) -> None:
        pass

    def ask(self, text: str) -> str:
        self.questions.append(text)
        return "答案是七。"

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closed = True


def behavior() -> BehaviorConfig:
    return BehaviorConfig(
        thinking_filler_delay_s=0,
        max_answer_chars=200,
        max_sentence_chars=40,
    )


def test_normalize_strips_wake_word() -> None:
    assert normalize_user_text("你好地瓜，3加4等于几？", "你好地瓜") == "3加4等于几"
    assert normalize_user_text("  你好  ", "") == "你好"


def test_dialog_strips_wake_word_and_asks_agent() -> None:
    agent = FakeAgent()
    dialog = Dialog(agent, behavior())
    assert dialog.respond("你好地瓜，三加四等于几？") == "答案是七。"
    assert agent.questions == ["三加四等于几"]


def test_reset_phrase_starts_new_session() -> None:
    agent = FakeAgent()
    dialog = Dialog(agent, behavior())
    reply = dialog.respond("重新开始")
    assert "重新开始" in reply
    assert agent.resets == 1
    assert agent.questions == []


def test_safety_bypasses_agent() -> None:
    agent = FakeAgent()
    dialog = Dialog(agent, behavior())
    reply = dialog.respond("我不想活了")
    assert "大人" in reply
    assert agent.questions == []


def test_empty_asr_is_ignored() -> None:
    agent = FakeAgent()
    dialog = Dialog(agent, behavior())
    assert dialog.respond("   ") == ""
    assert agent.questions == []


def test_agent_error_becomes_dialog_error() -> None:
    class Broken(FakeAgent):
        def ask(self, text: str) -> str:
            raise AgentError("boom")

    with pytest.raises(DialogError):
        Dialog(Broken(), behavior()).respond("你好")


class FakeSession:
    id = "session-123"

    def __init__(self) -> None:
        self.inputs: list[str] = []

    def run(self, text: str) -> SimpleNamespace:
        self.inputs.append(text)
        return SimpleNamespace(finish_reason="completed", final_response="答案")


class FakeHarness:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.started = False
        self.closed = False
        self.sessions: list[FakeSession] = []
        self.resumed: list[str] = []

    def start(self) -> None:
        self.started = True

    def start_session(self) -> FakeSession:
        session = FakeSession()
        session.id = f"session-{len(self.sessions) + 1}"
        self.sessions.append(session)
        return session

    def resume_session(self, session_id: str) -> FakeSession:
        for session in self.sessions:
            if session.id == session_id:
                self.resumed.append(session_id)
                return session
        raise KeyError(session_id)

    def close(self) -> None:
        self.closed = True


def make_agent_config(tmp_path, provider_patch_file=None):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("你是小地瓜老师。", encoding="utf-8")
    patch = tmp_path / "voice-only.yml"
    patch.write_text(
        "- id: persistent-bash\n  disabled: true\n"
        "- id: persistent-pwsh\n  disabled: true\n"
        "- id: tool-fs\n  disabled: true\n"
        "- id: tool-working-directory\n  disabled: true\n"
        "- id: session-log-deepseek\n  disabled: true\n",
        encoding="utf-8",
    )
    return AgentConfig(
        dsh_home=tmp_path / "home",
        workspace=tmp_path / "work",
        system_prompt_file=prompt,
        patch_file=patch,
        session_id_file=tmp_path / "state" / "session_id",
        provider_patch_file=provider_patch_file,
        max_tokens=128,
    )


def test_build_harness_kwargs_includes_prompt_and_patch(tmp_path) -> None:
    config = make_agent_config(tmp_path)
    kwargs = build_harness_kwargs(config, "你是小地瓜老师。")
    assert kwargs["profile"] == "sdk-minimal"
    assert kwargs["env"]["DSH_SYSTEM_PROMPT"] == "你是小地瓜老师。"
    assert kwargs["patches"] == (str(config.patch_file),)


def test_provider_patch_is_included_after_the_safety_patch(tmp_path) -> None:
    provider_patch = tmp_path / "qwen-bailian.yml"
    provider_patch.write_text("- insert: []\n", encoding="utf-8")
    config = make_agent_config(tmp_path, provider_patch_file=provider_patch)
    kwargs = build_harness_kwargs(config, "你是小地瓜老师。")
    assert kwargs["patches"] == (str(config.patch_file), str(provider_patch))


def test_missing_provider_patch_fails_closed(tmp_path) -> None:
    config = make_agent_config(
        tmp_path, provider_patch_file=tmp_path / "missing-qwen.yml"
    )
    with pytest.raises(Exception):
        build_harness_kwargs(config, "你是小地瓜老师。")


def test_incomplete_safety_patch_fails_closed(tmp_path) -> None:
    config = make_agent_config(tmp_path)
    config.patch_file.write_text(
        "- id: persistent-bash\n  disabled: true\n", encoding="utf-8"
    )
    with pytest.raises(Exception):
        build_harness_kwargs(config, "你是小地瓜老师。")


def test_agent_ask_and_reset_use_sessions(tmp_path) -> None:
    config = make_agent_config(tmp_path)
    agent = DSHTutorAgent(config, harness_factory=FakeHarness)
    assert agent.ask("三加四") == "答案"
    assert agent.session_id == "session-1"
    agent.reset()
    assert agent.session_id == "session-2"
    agent.close()


def test_agent_resumes_saved_session_across_restart(tmp_path) -> None:
    config = make_agent_config(tmp_path)
    shared = FakeHarness()
    first = DSHTutorAgent(config, harness_factory=lambda **kwargs: shared)
    first.warmup()
    saved = first.session_id
    first.close()

    second = DSHTutorAgent(config, harness_factory=lambda **kwargs: shared)
    second.warmup()
    assert second.session_id == saved
    assert shared.resumed == [saved]
    second.close()


def test_agent_falls_back_when_saved_session_is_missing(tmp_path) -> None:
    config = make_agent_config(tmp_path)
    config.session_id_file.parent.mkdir(parents=True, exist_ok=True)
    config.session_id_file.write_text("session-does-not-exist\n", encoding="utf-8")
    harness = FakeHarness()
    agent = DSHTutorAgent(config, harness_factory=lambda **kwargs: harness)
    agent.warmup()
    assert agent.session_id == "session-1"
    assert harness.resumed == []
    agent.close()


def test_session_meta_is_written_and_resumed(tmp_path) -> None:
    config = make_agent_config(tmp_path)
    first = DSHTutorAgent(config, harness_factory=FakeHarness)
    first.warmup()
    meta = json.loads((tmp_path / "state" / "session_id.meta.json").read_text())
    assert meta["session_id"] == first.session_id
    assert meta["provider"] == "deepseek-official"
    assert meta["model"] == "deepseek-flash"
    first.close()


def test_session_meta_mismatch_starts_new_session(tmp_path) -> None:
    config = make_agent_config(tmp_path)
    config.session_id_file.parent.mkdir(parents=True, exist_ok=True)
    config.session_id_file.write_text("session-1\n", encoding="utf-8")
    (tmp_path / "state" / "session_id.meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "provider": "qwen-token-plan-cn",
                "model": "qwen3.8-flash",
                "prompt_sha256": "different",
            }
        ),
        encoding="utf-8",
    )
    harness = FakeHarness()
    agent = DSHTutorAgent(config, harness_factory=lambda **kwargs: harness)
    agent.warmup()
    assert harness.resumed == []
    assert agent.session_id == "session-1"
    agent.close()


def test_short_answer_resets_and_retries(tmp_path) -> None:
    class ShortThenFullHarness(FakeHarness):
        def start_session(self):
            session = super().start_session()
            if len(self.sessions) == 1:
                session.run = lambda text: SimpleNamespace(
                    finish_reason="completed", final_response="三"
                )
            else:
                session.run = lambda text: SimpleNamespace(
                    finish_reason="completed", final_response="三乘四等于十二。"
                )
            return session

    config = make_agent_config(tmp_path)
    agent = DSHTutorAgent(config, harness_factory=ShortThenFullHarness)
    assert agent.ask("三乘四等于多少？") == "三乘四等于十二。"
    assert agent.session_id == "session-2"
    agent.close()


def test_agent_can_disable_resume(tmp_path) -> None:
    config = replace(make_agent_config(tmp_path), resume_session=False)
    shared = FakeHarness()
    first = DSHTutorAgent(config, harness_factory=lambda **kwargs: shared)
    first.warmup()
    first.close()
    second = DSHTutorAgent(config, harness_factory=lambda **kwargs: shared)
    second.warmup()
    assert second.session_id == "session-2"
    second.close()


def test_agent_rejects_empty_response(tmp_path) -> None:
    class EmptyHarness(FakeHarness):
        def start_session(self):
            session = super().start_session()
            session.run = lambda text: SimpleNamespace(
                finish_reason="completed", final_response=""
            )
            return session

    config = make_agent_config(tmp_path)
    agent = DSHTutorAgent(config, harness_factory=EmptyHarness)
    with pytest.raises(AgentError):
        agent.ask("你好")

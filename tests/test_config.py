from __future__ import annotations

from pathlib import Path

import pytest

from magicbox_tutor.config import ConfigError, load_config


def write_config(tmp_path: Path, *, extra: str = "") -> Path:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("你是小学学习助手。", encoding="utf-8")
    patch = tmp_path / "voice-only.yml"
    patch.write_text("- id: persistent-bash\n  disabled: true\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
agent:
  dsh_home: {tmp_path / 'home'}
  workspace: {tmp_path / 'work'}
  system_prompt_file: {prompt}
  patch_file: {patch}
  session_id_file: {tmp_path / 'state' / 'session_id'}
  model: deepseek-flash
  max_tokens: 256
audio:
  asr_topic: /prompt_text
  tts_topic: /tts_text
status:
  status_file: {tmp_path / 'run' / 'status.json'}
  log_level: debug
{extra}
""",
        encoding="utf-8",
    )
    return config


def test_load_config_resolves_and_reads(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    assert config.agent.model == "deepseek-flash"
    assert config.agent.max_tokens == 256
    assert config.agent.dsh_home == (tmp_path / "home").resolve()
    assert config.status.log_level == "DEBUG"
    assert config.behavior.wake_word == "你好地瓜"
    assert config.agent.resume_session is True


def test_environment_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGICBOX_TUTOR_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("MAGICBOX_TUTOR_MAX_TOKENS", "768")
    monkeypatch.setenv("MAGICBOX_TUTOR_LOG_TRANSCRIPTS", "true")
    config = load_config(write_config(tmp_path))
    assert config.agent.model == "deepseek-v4-flash"
    assert config.agent.max_tokens == 768
    assert config.agent.log_transcripts is True


def test_qwen_config_selects_pi_ai_provider(tmp_path: Path) -> None:
    config = load_config("config/tutor.qwen.yaml")
    assert config.agent.provider == "qwen-token-plan-cn"
    assert config.agent.model == "qwen3.8-flash"
    assert config.agent.api_key_env == "QWEN_TOKEN_PLAN_CN_API_KEY"
    assert config.agent.provider_patch_file is not None
    assert config.agent.provider_patch_file.name == "qwen-bailian.yml"


def test_resume_can_be_disabled_by_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAGICBOX_TUTOR_RESUME_SESSION", "false")
    config = load_config(write_config(tmp_path))
    assert config.agent.resume_session is False


def test_missing_explicit_config_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")


def test_invalid_topic_is_rejected(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    text = config.read_text(encoding="utf-8").replace(
        "asr_topic: /prompt_text", "asr_topic: nope"
    )
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(config)


def test_full_sdk_profile_is_rejected_for_child_safety(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    text = config.read_text(encoding="utf-8").replace(
        "model: deepseek-flash", "profile: sdk\n  model: deepseek-flash"
    )
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(config)

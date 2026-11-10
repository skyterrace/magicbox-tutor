"""Configuration loading for the MagicBox voice tutor.

The runtime is designed to be configured once by an adult and then started by
systemd.  It never reads keyboard input.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("MAGICBOX_TUTOR_CONFIG", "/etc/magicbox-tutor/config.yaml")
)
DEFAULT_SYSTEM_PROMPT = PROJECT_ROOT / "config" / "tutor_system_prompt.md"
DEFAULT_PATCH = PROJECT_ROOT / "patches" / "voice-only.yml"


class ConfigError(ValueError):
    """Raised when the deployment configuration is unusable."""


@dataclass(frozen=True)
class AgentConfig:
    dsh_home: Path
    workspace: Path
    system_prompt_file: Path
    patch_file: Path
    session_id_file: Path
    provider_patch_file: Path | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"
    profile: str = "sdk-minimal"
    provider: str = "deepseek-official"
    model: str = "deepseek-flash"
    max_tokens: int = 512
    request_timeout_s: float = 90.0
    answer_timeout_s: float = 75.0
    log_transcripts: bool = False
    resume_session: bool = True


@dataclass(frozen=True)
class AudioConfig:
    asr_topic: str = "/prompt_text"
    tts_topic: str = "/tts_text"
    device: str = "plughw:0,0"
    asr_model: Path = Path("/userdata/magicbox/config/sense-voice-small-fp16.gguf")
    tts_model_dir: Path = Path("/userdata/magicbox/dep/matcha-icefall-zh-baker")
    kws_model_dir: Path = Path(
        "/userdata/magicbox/dep/sherpa-onnx/"
        "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
    )


@dataclass(frozen=True)
class BehaviorConfig:
    wake_word: str = "你好地瓜"
    thinking_filler_delay_s: float = 1.5
    thinking_filler: str = "让我想一想。"
    max_answer_chars: int = 600
    max_sentence_chars: int = 80
    reset_phrases: tuple[str, ...] = ("重新开始", "新对话", "换个话题")
    startup_greeting: str = "小地瓜老师准备好啦。说你好地瓜，就可以开始。"
    startup_greeting_delay_s: float = 4.0
    fallback_error: str = "哎呀，我的小脑袋卡住了。我们再说一次，好吗？"
    fallback_empty: str = "我没听清，可以再说一遍吗？"
    fallback_timeout: str = "这个问题有点难，我先想一想。你可以先说说你已经知道什么。"


@dataclass(frozen=True)
class StatusConfig:
    status_file: Path
    log_level: str = "INFO"


@dataclass(frozen=True)
class TutorConfig:
    agent: AgentConfig
    audio: AudioConfig
    behavior: BehaviorConfig
    status: StatusConfig


def _as_path(value: Any, base: Path) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"配置项 {name} 必须是对象")
    return value


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value is not None and value.strip() else None


def _env_int(name: str) -> int | None:
    raw = _env(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 必须是整数") from exc


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "是"}


def _env_bool(name: str) -> bool | None:
    raw = _env(name)
    if raw is None:
        return None
    return _coerce_bool(raw)


def load_config(path: str | Path | None = None) -> TutorConfig:
    """Load YAML configuration, with a few environment overrides.

    Relative paths in the YAML file are resolved against that file's directory.
    This makes a development config portable while production paths stay
    absolute.
    """

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    config_path = config_path.expanduser().resolve()
    base = config_path.parent
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件 YAML 格式错误 {config_path}: {exc}") from exc
    if loaded is not None and not isinstance(loaded, dict):
        raise ConfigError(f"配置文件根节点必须是对象: {config_path}")
    raw: dict[str, Any] = loaded or {}

    agent_raw = _section(raw, "agent")
    audio_raw = _section(raw, "audio")
    behavior_raw = _section(raw, "behavior")
    status_raw = _section(raw, "status")

    dsh_home = _env("MAGICBOX_TUTOR_DSH_HOME") or agent_raw.get(
        "dsh_home", "/userdata/magicbox-tutor/dsh-home"
    )
    workspace = _env("MAGICBOX_TUTOR_WORKSPACE") or agent_raw.get(
        "workspace", "/userdata/magicbox-tutor/workspace"
    )
    system_prompt = _env("MAGICBOX_TUTOR_SYSTEM_PROMPT") or agent_raw.get(
        "system_prompt_file", str(DEFAULT_SYSTEM_PROMPT)
    )
    patch_file = agent_raw.get("patch_file", str(DEFAULT_PATCH))
    provider_patch_raw = agent_raw.get("provider_patch_file", "")
    provider_patch_file = (
        _as_path(provider_patch_raw, base)
        if provider_patch_raw not in (None, "")
        else None
    )
    api_key_env = _env("MAGICBOX_TUTOR_API_KEY_ENV") or agent_raw.get(
        "api_key_env", "DEEPSEEK_API_KEY"
    )
    session_id_file = agent_raw.get(
        "session_id_file", "/userdata/magicbox-tutor/state/session_id"
    )
    status_file = status_raw.get(
        "status_file", "/run/magicbox-tutor/status.json"
    )

    model = _env("MAGICBOX_TUTOR_MODEL") or agent_raw.get("model", "deepseek-flash")
    provider = _env("MAGICBOX_TUTOR_PROVIDER") or agent_raw.get(
        "provider", "deepseek-official"
    )
    max_tokens = _env_int("MAGICBOX_TUTOR_MAX_TOKENS") or int(
        agent_raw.get("max_tokens", 512)
    )
    log_level = _env("MAGICBOX_TUTOR_LOG_LEVEL") or status_raw.get(
        "log_level", "INFO"
    )
    log_transcripts = _env_bool("MAGICBOX_TUTOR_LOG_TRANSCRIPTS")
    if log_transcripts is None:
        log_transcripts = _coerce_bool(agent_raw.get("log_transcripts", False))

    resume_session = _env_bool("MAGICBOX_TUTOR_RESUME_SESSION")
    if resume_session is None:
        resume_session = _coerce_bool(agent_raw.get("resume_session", True))

    reset_phrases_raw = behavior_raw.get(
        "reset_phrases", ("重新开始", "新对话", "换个话题")
    )
    if isinstance(reset_phrases_raw, str):
        reset_phrases = tuple(
            part.strip() for part in reset_phrases_raw.split(",") if part.strip()
        )
    elif isinstance(reset_phrases_raw, (list, tuple)):
        reset_phrases = tuple(str(part).strip() for part in reset_phrases_raw if str(part).strip())
    else:
        raise ConfigError("behavior.reset_phrases 必须是字符串或列表")

    behavior = BehaviorConfig(
        wake_word=str(behavior_raw.get("wake_word", "你好地瓜")),
        thinking_filler_delay_s=float(
            behavior_raw.get("thinking_filler_delay_s", 1.5)
        ),
        thinking_filler=str(behavior_raw.get("thinking_filler", "让我想一想。")),
        max_answer_chars=int(behavior_raw.get("max_answer_chars", 600)),
        max_sentence_chars=int(behavior_raw.get("max_sentence_chars", 80)),
        reset_phrases=reset_phrases,
        startup_greeting=str(
            behavior_raw.get(
                "startup_greeting",
                "小地瓜老师准备好啦。说你好地瓜，就可以开始。",
            )
        ),
        startup_greeting_delay_s=float(
            behavior_raw.get("startup_greeting_delay_s", 4.0)
        ),
        fallback_error=str(
            behavior_raw.get(
                "fallback_error", "哎呀，我的小脑袋卡住了。我们再说一次，好吗？"
            )
        ),
        fallback_empty=str(
            behavior_raw.get("fallback_empty", "我没听清，可以再说一遍吗？")
        ),
        fallback_timeout=str(
            behavior_raw.get(
                "fallback_timeout",
                "这个问题有点难，我先想一想。你可以先说说你已经知道什么。",
            )
        ),
    )

    config = TutorConfig(
        agent=AgentConfig(
            dsh_home=_as_path(dsh_home, base),
            workspace=_as_path(workspace, base),
            system_prompt_file=_as_path(system_prompt, base),
            patch_file=_as_path(patch_file, base),
            session_id_file=_as_path(session_id_file, base),
            provider_patch_file=provider_patch_file,
            api_key_env=str(api_key_env),
            profile=str(agent_raw.get("profile", "sdk-minimal")),
            provider=str(provider),
            model=str(model),
            max_tokens=max_tokens,
            request_timeout_s=float(agent_raw.get("request_timeout_s", 90.0)),
            answer_timeout_s=float(agent_raw.get("answer_timeout_s", 75.0)),
            log_transcripts=log_transcripts,
            resume_session=resume_session,
        ),
        audio=AudioConfig(
            asr_topic=str(audio_raw.get("asr_topic", "/prompt_text")),
            tts_topic=str(audio_raw.get("tts_topic", "/tts_text")),
            device=str(audio_raw.get("device", "plughw:0,0")),
            asr_model=_as_path(
                audio_raw.get(
                    "asr_model", "/userdata/magicbox/config/sense-voice-small-fp16.gguf"
                ),
                base,
            ),
            tts_model_dir=_as_path(
                audio_raw.get(
                    "tts_model_dir", "/userdata/magicbox/dep/matcha-icefall-zh-baker"
                ),
                base,
            ),
            kws_model_dir=_as_path(
                audio_raw.get(
                    "kws_model_dir",
                    "/userdata/magicbox/dep/sherpa-onnx/"
                    "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01",
                ),
                base,
            ),
        ),
        behavior=behavior,
        status=StatusConfig(
            status_file=_as_path(status_file, base),
            log_level=log_level.upper(),
        ),
    )
    _validate(config)
    return config


def _validate(config: TutorConfig) -> None:
    if not config.agent.dsh_home.is_absolute():
        raise ConfigError("agent.dsh_home 必须是绝对路径")
    if not config.agent.workspace.is_absolute():
        raise ConfigError("agent.workspace 必须是绝对路径")
    if not config.agent.api_key_env:
        raise ConfigError("agent.api_key_env 不能为空")
    if config.agent.provider_patch_file is not None and not config.agent.provider_patch_file.is_absolute():
        raise ConfigError("agent.provider_patch_file 必须是绝对路径")
    if config.agent.profile != "sdk-minimal":
        raise ConfigError(
            "为儿童设备安全，agent.profile 必须是 sdk-minimal；"
            "sdk/web 会重新暴露编码工具"
        )
    if config.agent.max_tokens < 64:
        raise ConfigError("agent.max_tokens 至少为 64")
    if config.agent.request_timeout_s <= 0:
        raise ConfigError("agent.request_timeout_s 必须大于 0")
    if config.agent.answer_timeout_s <= 0:
        raise ConfigError("agent.answer_timeout_s 必须大于 0")
    if config.behavior.max_answer_chars < 40:
        raise ConfigError("behavior.max_answer_chars 至少为 40")
    if config.behavior.max_sentence_chars < 20:
        raise ConfigError("behavior.max_sentence_chars 至少为 20")
    if not config.audio.asr_topic.startswith("/"):
        raise ConfigError("audio.asr_topic 必须以 / 开头")
    if not config.audio.tts_topic.startswith("/"):
        raise ConfigError("audio.tts_topic 必须以 / 开头")
    if not config.behavior.reset_phrases:
        raise ConfigError("behavior.reset_phrases 不能为空")


def _probe_writable(path: Path, label: str) -> None:
    """Fail with an actionable message when a runtime path is not writable."""

    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".magicbox-tutor-write-test-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        reason = "只读文件系统" if exc.errno == 30 else str(exc)
        raise ConfigError(
            f"{label} 不可写（{reason}）: {path}\n"
            "  如果这是重启后出现的，请先恢复根文件系统为可写：\n"
            "    sudo mount -o remount,rw /\n"
            "  再重启服务：sudo systemctl restart magicbox-tutor\n"
            "  如果 remount 失败，请检查 dmesg 是否有 ext4/SD 卡错误。"
        ) from exc


def ensure_runtime_dirs(config: TutorConfig) -> None:
    """Create runtime directories and verify they are actually writable."""

    for path, label in (
        (config.agent.dsh_home, "agent.dsh_home"),
        (config.agent.workspace, "agent.workspace"),
        (config.agent.session_id_file.parent, "session_id_file 目录"),
        (config.status.status_file.parent, "status_file 目录"),
    ):
        _probe_writable(path, label)
        try:
            path.chmod(0o700)
        except OSError:
            # The service may run as a user that does not own /run; that is fine.
            pass


def with_overrides(config: TutorConfig, **kwargs: Any) -> TutorConfig:
    """Small helper used by tests and the simulator."""

    return replace(config, **kwargs)

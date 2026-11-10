"""Adapter between the voice loop and the DeepSeek Harness Python SDK.

The SDK runs the real `dsh` runtime as a child process and talks JSON-RPC over
stdio.  We use the `sdk-minimal` profile plus ``patches/voice-only.yml`` so the
model has no shell, filesystem, web, or plugin tools: a child's spoken words can
only become conversation, never device actions. An optional provider patch
(for example ``qwen-bailian.yml``) can add another OpenAI-compatible route.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

from .config import AgentConfig, ConfigError


_REQUIRED_DISABLED = {
    "persistent-bash",
    "persistent-pwsh",
    "tool-fs",
    "tool-working-directory",
    # Privacy: sdk-minimal otherwise uploads unaccepted session-log events.
    "session-log-deepseek",
}


def validate_voice_only_patch(path: Path) -> None:
    """Fail closed if the child-safety patch stops disabling every tool."""

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"无法读取安全补丁 {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"安全补丁 YAML 格式错误 {path}: {exc}") from exc
    if not isinstance(loaded, list):
        raise ConfigError(f"安全补丁必须是 patch 列表: {path}")
    disabled = {
        row.get("id")
        for row in loaded
        if isinstance(row, dict) and row.get("disabled") is True
    }
    missing = _REQUIRED_DISABLED - disabled
    if missing:
        raise ConfigError(
            "安全补丁没有禁用全部模型工具，缺少: " + ", ".join(sorted(missing))
        )


class AgentError(RuntimeError):
    """Raised when the DSH agent cannot produce a usable answer."""


class TutorAgent(Protocol):
    @property
    def session_id(self) -> str: ...

    def warmup(self) -> None: ...

    def ask(self, text: str) -> str: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


HarnessFactory = Callable[..., Any]


def read_system_prompt(path: Path) -> str:
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigError(f"无法读取人设文件 {path}: {exc}") from exc
    if not prompt:
        raise ConfigError(f"人设文件为空: {path}")
    return prompt


def build_harness_kwargs(config: AgentConfig, system_prompt: str) -> dict[str, Any]:
    """Build the public Python SDK keyword arguments.

    Kept pure so deployment wiring can be tested without an API key.
    """

    env = {
        "DSH_SYSTEM_PROMPT": system_prompt,
    }
    kwargs: dict[str, Any] = {
        "dsh_home": str(config.dsh_home),
        "cwd": str(config.workspace),
        "profile": config.profile,
        "provider": config.provider,
        "model": config.model,
        "max_tokens": config.max_tokens,
        "request_timeout_seconds": config.request_timeout_s,
        "env": env,
        "initialize_timeout_seconds": 60.0,
        "shutdown_timeout_seconds": 3.0,
    }
    if not config.patch_file.exists():
        raise ConfigError(f"安全补丁不存在: {config.patch_file}")
    validate_voice_only_patch(config.patch_file)
    patches = [str(config.patch_file)]
    if config.provider_patch_file is not None:
        if not config.provider_patch_file.exists():
            raise ConfigError(f"Provider 补丁不存在: {config.provider_patch_file}")
        patches.append(str(config.provider_patch_file))
    kwargs["patches"] = tuple(patches)
    return kwargs


class DSHTutorAgent:
    """Lazy, serialized DSH conversation session."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        logger: logging.Logger | None = None,
        harness_factory: HarnessFactory | None = None,
    ) -> None:
        self._config = config
        self._logger = logger or logging.getLogger(__name__)
        self._harness_factory = harness_factory
        self._harness: Any = None
        self._session: Any = None
        self._session_id = ""
        self._prompt_hash = ""
        self._lock = threading.RLock()

    @property
    def session_id(self) -> str:
        with self._lock:
            return self._session_id

    def warmup(self) -> None:
        """Start the runtime and open a session before the first question.

        Startup can take several seconds; doing it in the background keeps the
        first child question feeling responsive.
        """

        with self._lock:
            self._ensure_started_locked()

    def ask(self, text: str) -> str:
        with self._lock:
            self._ensure_started_locked()
            response = self._run_once_locked(text)
            # A long question answered with 1–2 characters usually means the
            # persisted history has drifted into a one-word pattern (seen when
            # switching a long DeepSeek session to Qwen).  A fresh session is
            # safer than repeating a broken answer, and keeps the device usable.
            if self._looks_truncated(text, response):
                self._logger.warning(
                    "模型回答过短（%d 字），重置会话后重试一次", len(response)
                )
                self._session = self._harness.start_session()
                self._session_id = str(getattr(self._session, "id", "") or "")
                self._write_session_id_locked()
                self._write_session_meta_locked()
                retry = self._run_once_locked(text)
                if retry:
                    response = retry
            return response

    def _run_once_locked(self, text: str) -> str:
        try:
            result = self._session.run(text)
        except Exception as exc:  # SDK/transport/provider errors
            self._logger.error("DSH 请求失败: %s", type(exc).__name__)
            raise AgentError("Agent 请求失败") from exc

        finish = getattr(result, "finish_reason", None)
        if finish not in (None, "completed"):
            self._logger.error("DSH 回合未正常结束: %s", finish)
            raise AgentError(f"Agent 回合结束原因异常: {finish}")

        response = str(getattr(result, "final_response", "") or "").strip()
        if not response:
            raise AgentError("Agent 返回空内容")
        return response

    @staticmethod
    def _looks_truncated(question: str, answer: str) -> bool:
        compact = re.sub(r"\s+", "", answer)
        return len(question.strip()) >= 6 and len(compact) <= 2

    def reset(self) -> None:
        """Start a new DSH session, leaving the old one persisted on disk."""

        with self._lock:
            self._ensure_started_locked()
            self._session = self._harness.start_session()
            self._session_id = str(getattr(self._session, "id", "") or "")
            self._write_session_id_locked()
            self._write_session_meta_locked()
            self._logger.info("已开始新的对话会话: %s", self._session_id)

    def close(self) -> None:
        with self._lock:
            harness = self._harness
            self._harness = None
            self._session = None
            if harness is not None:
                try:
                    harness.close()
                except Exception as exc:
                    self._logger.warning("关闭 DSH 运行时失败: %s", type(exc).__name__)

    def _ensure_started_locked(self) -> None:
        if self._harness is not None and self._session is not None:
            return

        prompt = read_system_prompt(self._config.system_prompt_file)
        self._prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        kwargs = build_harness_kwargs(self._config, prompt)

        if self._harness_factory is None:
            try:
                from deepseek_harness import DeepSeekHarness
            except ImportError as exc:
                raise AgentError(
                    "未安装 deepseek-harness-sdk；请运行 scripts/install.sh"
                ) from exc
            factory: HarnessFactory = DeepSeekHarness
        else:
            factory = self._harness_factory

        if not os.environ.get(self._config.api_key_env):
            self._logger.warning(
                "未设置 %s；DSH 运行时可能无法调用模型",
                self._config.api_key_env,
            )

        self._config.dsh_home.mkdir(parents=True, exist_ok=True)
        self._config.workspace.mkdir(parents=True, exist_ok=True)

        self._logger.info(
            "启动 DSH SDK: profile=%s provider=%s model=%s",
            self._config.profile,
            self._config.provider,
            self._config.model,
        )
        harness = factory(**kwargs)
        self._harness = harness
        try:
            harness.start()
            self._session = self._open_session_locked(harness)
        except Exception as exc:
            self._harness = None
            self._session = None
            try:
                harness.close()
            except Exception:
                pass
            # Include the SDK's stderr tail: it names the real cause (bad model,
            # read-only home, missing key).  It never contains the API key.
            self._logger.error("DSH 运行时启动失败: %s", exc)
            raise AgentError(f"DSH 运行时启动失败: {exc}") from exc

        self._session_id = str(getattr(self._session, "id", "") or "")
        self._write_session_id_locked()
        self._write_session_meta_locked()
        self._logger.info("DSH 会话已就绪: %s", self._session_id)

    def _open_session_locked(self, harness: Any) -> Any:
        """Resume the saved Session when possible, otherwise start a new one.

        A saved ID can become unusable after a DSH upgrade, a changed profile,
        a moved working directory, or a corrupted/occupied Session.  Falling
        back to a new Session keeps the device usable, while the log records
        why the old history was not loaded.
        """

        saved = self._read_saved_session_id_locked() if self._config.resume_session else ""
        if saved:
            meta = self._read_session_meta_locked()
            reason = self._session_mismatch(meta, saved)
            if reason is None:
                try:
                    session = harness.resume_session(saved)
                    if not str(getattr(session, "id", "") or ""):
                        raise AgentError("恢复后的会话 ID 为空")
                    self._logger.info("已恢复上次会话: %s", saved)
                    return session
                except Exception as exc:
                    self._logger.warning(
                        "恢复会话失败 (%s)，将新建会话: %s",
                        type(exc).__name__,
                        saved,
                    )
            else:
                self._logger.info("不恢复旧会话（%s），将新建会话", reason)

        session = harness.start_session()
        self._logger.info("已新建对话会话: %s", getattr(session, "id", ""))
        return session

    def _session_mismatch(self, meta: dict[str, Any] | None, saved: str) -> str | None:
        if meta is None:
            return "旧会话没有兼容标记"
        if meta.get("session_id") != saved:
            return "会话 ID 不一致"
        if meta.get("provider") != self._config.provider:
            return f"provider 从 {meta.get('provider')} 变成 {self._config.provider}"
        if meta.get("model") != self._config.model:
            return f"model 从 {meta.get('model')} 变成 {self._config.model}"
        if meta.get("prompt_sha256") != self._prompt_hash:
            return "人设文件已变化"
        return None

    def _read_saved_session_id_locked(self) -> str:
        try:
            return self._config.session_id_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @property
    def _session_meta_file(self) -> Path:
        path = self._config.session_id_file
        return path.with_name(path.name + ".meta.json")

    def _read_session_meta_locked(self) -> dict[str, Any] | None:
        try:
            raw = self._session_meta_file.read_text(encoding="utf-8")
            value = json.loads(raw)
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _write_session_meta_locked(self) -> None:
        payload = {
            "session_id": self._session_id,
            "provider": self._config.provider,
            "model": self._config.model,
            "prompt_sha256": self._prompt_hash,
        }
        path = self._session_meta_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except OSError as exc:
            self._logger.warning("写入会话兼容标记失败: %s", type(exc).__name__)

    def _write_session_id_locked(self) -> None:
        path = self._config.session_id_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(self._session_id + "\n", encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            self._logger.warning("写入会话标识失败: %s", type(exc).__name__)

"""Async turn orchestration: one question at a time, with filler and timeout."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from .config import BehaviorConfig, TutorConfig
from .dialog import Dialog, DialogError
from .speech import prepare_speech
from .status import StatusWriter


class Speaker(Protocol):
    def say(self, text: str) -> None: ...

    def end(self) -> None: ...


class TutorService:
    """Serialize agent turns while keeping the ROS callback thread free."""

    def __init__(
        self,
        config: TutorConfig,
        dialog: Dialog,
        speaker: Speaker,
        *,
        status: StatusWriter | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._dialog = dialog
        self._speaker = speaker
        self._logger = logger or logging.getLogger(__name__)
        self._status = status or StatusWriter(config.status.status_file)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="magicbox-tutor"
        )
        self._lock = threading.RLock()
        self._busy = False
        self._active_turn: int | None = None
        self._turn_seq = 0
        self._answer_ready = False
        self._abandoned = False
        self._filler_timer: threading.Timer | None = None
        self._timeout_timer: threading.Timer | None = None
        self._closed = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def start(self) -> None:
        self._status.update("starting", busy=False)
        thread = threading.Thread(
            target=self._warmup, name="magicbox-tutor-warmup", daemon=True
        )
        thread.start()

    def _warmup(self) -> None:
        with self._lock:
            if self._closed:
                return
        try:
            self._dialog.agent.warmup()
        except Exception as exc:
            self._logger.error("DSH 预热失败: %s", type(exc).__name__)
            self._status.update("error", busy=False, last_error="warmup")
            return
        with self._lock:
            if self._closed:
                return
        if not self.busy:
            self._status.update(
                "idle", busy=False, session_id=self._dialog.agent.session_id
            )

    def submit(self, text: str) -> bool:
        """Queue one ASR result.  Returns False when another answer is running."""

        with self._lock:
            if self._closed:
                return False
            if self._busy:
                self._logger.info("上一轮仍在处理，忽略新的语音输入")
                return False
            self._turn_seq += 1
            turn = self._turn_seq
            self._busy = True
            self._active_turn = turn
            self._answer_ready = False
            self._abandoned = False
            self._status.update("thinking", busy=True, turn=turn)
            self._start_timers_locked(turn)
            self._executor.submit(self._run_turn, turn, text)
            return True

    def greet(self, text: str) -> None:
        """Speak a startup greeting if the device is idle."""

        if not text:
            return
        with self._lock:
            if self._closed or self._busy:
                return
            self._busy = True
            self._active_turn = None
            self._status.update("speaking", busy=True, turn=None)
        try:
            self._speak(text)
        finally:
            with self._lock:
                self._busy = False
                self._active_turn = None
                self._status.update("idle", busy=False)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancel_timers_locked()
            self._status.update("stopped", busy=False)
        self._executor.shutdown(wait=False, cancel_futures=True)
        try:
            self._dialog.agent.close()
        except Exception as exc:
            self._logger.warning("关闭 Agent 失败: %s", type(exc).__name__)

    def _run_turn(self, turn: int, text: str) -> None:
        started = time.monotonic()
        error_name: str | None = None
        try:
            answer = self._dialog.respond(text)
        except DialogError:
            answer = self._config.behavior.fallback_error
            error_name = "dialog"
        except Exception as exc:
            self._logger.error("回答生成异常: %s", type(exc).__name__)
            answer = self._config.behavior.fallback_error
            error_name = type(exc).__name__

        with self._lock:
            if self._abandoned or self._active_turn != turn:
                self._busy = False
                self._active_turn = None
                self._status.update("idle", busy=False, last_error="timeout")
                return
            self._answer_ready = True
            self._cancel_timers_locked()
            self._status.update(
                "speaking",
                busy=True,
                turn=turn,
                last_error=error_name,
            )

        try:
            self._speak(answer)
        except Exception as exc:
            self._logger.error("TTS 发布失败: %s", type(exc).__name__)
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            with self._lock:
                if self._active_turn == turn:
                    self._busy = False
                    self._active_turn = None
                    self._status.update(
                        "idle",
                        busy=False,
                        turn=turn,
                        last_turn_ms=elapsed_ms,
                        last_error=error_name,
                    )

    def _speak(self, text: str) -> None:
        chunks = prepare_speech(
            text,
            max_chars=self._config.behavior.max_answer_chars,
            max_sentence_chars=self._config.behavior.max_sentence_chars,
        )
        if not chunks:
            chunks = [self._config.behavior.fallback_empty]
        try:
            for chunk in chunks:
                # audio_io appends "。" to every TTS message; avoid "。。".
                self._speaker.say(chunk.rstrip("。！？!?；;"))
        finally:
            self._speaker.end()

    def _start_timers_locked(self, turn: int) -> None:
        self._cancel_timers_locked()
        behavior: BehaviorConfig = self._config.behavior
        if behavior.thinking_filler_delay_s > 0 and behavior.thinking_filler:
            self._filler_timer = threading.Timer(
                behavior.thinking_filler_delay_s, self._on_filler, args=(turn,)
            )
            self._filler_timer.daemon = True
            self._filler_timer.start()
        if self._config.agent.answer_timeout_s > 0:
            self._timeout_timer = threading.Timer(
                self._config.agent.answer_timeout_s, self._on_timeout, args=(turn,)
            )
            self._timeout_timer.daemon = True
            self._timeout_timer.start()

    def _cancel_timers_locked(self) -> None:
        for timer in (self._filler_timer, self._timeout_timer):
            if timer is not None:
                timer.cancel()
        self._filler_timer = None
        self._timeout_timer = None

    def _on_filler(self, turn: int) -> None:
        with self._lock:
            if (
                self._closed
                or self._active_turn != turn
                or self._answer_ready
                or self._abandoned
            ):
                return
            # Publish while holding the same lock used before the real answer so
            # the filler can never be queued after it.
            try:
                self._speaker.say(
                    self._config.behavior.thinking_filler.rstrip("。！？!?；;")
                )
            except Exception as exc:
                self._logger.warning("思考提示播放失败: %s", type(exc).__name__)

    def _on_timeout(self, turn: int) -> None:
        with self._lock:
            if (
                self._closed
                or self._active_turn != turn
                or self._answer_ready
                or self._abandoned
            ):
                return
            self._abandoned = True
            self._answer_ready = True
            self._cancel_timers_locked()
            self._status.update("timeout", busy=True, turn=turn, last_error="timeout")
            try:
                self._speaker.say(
                    self._config.behavior.fallback_timeout.rstrip("。！？!?；;")
                )
                self._speaker.end()
            except Exception as exc:
                self._logger.warning("超时提示播放失败: %s", type(exc).__name__)

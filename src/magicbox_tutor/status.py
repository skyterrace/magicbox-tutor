"""A tiny, transcript-free status file for headless operation and support."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any


class StatusWriter:
    def __init__(
        self,
        path: Path,
        *,
        enabled: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._path = path
        self._enabled = enabled
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "state": "starting",
            "updated_at": time.time(),
        }

    def update(self, state: str, **fields: Any) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._state.update(fields)
            self._state["state"] = state
            self._state["updated_at"] = time.time()
            payload = json.dumps(self._state, ensure_ascii=False, sort_keys=True)
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_name(self._path.name + ".tmp")
                tmp.write_text(payload + "\n", encoding="utf-8")
                os.replace(tmp, self._path)
            except OSError as exc:
                self._logger.debug("写入状态文件失败: %s", type(exc).__name__)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

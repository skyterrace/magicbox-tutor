#!/usr/bin/env python3
"""Development-only one-shot simulator.

The product runtime is started by systemd and never reads stdin.  This helper is
for checking persona / speech formatting on a workstation without a robot:

    .venv/bin/python tools/simulate_dialog.py --config config/tutor.dev.yaml \
        --text "你好地瓜，三加四等于几？"

It prints the spoken chunks to stdout.  It is not installed as the service
entry point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from magicbox_tutor.agent import DSHTutorAgent  # noqa: E402
from magicbox_tutor.config import load_config  # noqa: E402
from magicbox_tutor.dialog import Dialog  # noqa: E402
from magicbox_tutor.speech import prepare_speech  # noqa: E402


class FakeAgent:
    @property
    def session_id(self) -> str:
        return "simulated"

    def warmup(self) -> None:
        pass

    def ask(self, text: str) -> str:
        return f"这是模拟回答。你刚才说的是：{text}。真正使用时请配置 API 密钥。"

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "tutor.dev.yaml")
    parser.add_argument("--text", required=True)
    parser.add_argument("--fake", action="store_true", help="do not call the model")
    args = parser.parse_args()

    config = load_config(args.config)
    agent = FakeAgent() if args.fake else DSHTutorAgent(config.agent)
    try:
        answer = Dialog(agent, config.behavior).respond(args.text)
        chunks = prepare_speech(
            answer,
            max_chars=config.behavior.max_answer_chars,
            max_sentence_chars=config.behavior.max_sentence_chars,
        )
        for chunk in chunks:
            print(chunk)
    finally:
        agent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

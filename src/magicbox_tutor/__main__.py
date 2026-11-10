"""Process entry point.  Product operation is voice-only; no stdin is read."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import ConfigError, ensure_runtime_dirs, load_config


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="magicbox-tutor",
        description="RDK MagicBox voice tutor using DeepSeek Harness as the agent.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="YAML configuration path (default: /etc/magicbox-tutor/config.yaml)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and exit; does not start ROS or the agent",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="check config, files, writability, key presence, and exit",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        setup_logging("ERROR")
        logging.getLogger(__name__).error("配置错误: %s", exc)
        return 2

    setup_logging(config.status.log_level)
    logger = logging.getLogger(__name__)

    if args.doctor:
        return _doctor(config)

    if args.check:
        from .agent import build_harness_kwargs, read_system_prompt

        try:
            build_harness_kwargs(
                config.agent, read_system_prompt(config.agent.system_prompt_file)
            )
        except ConfigError as exc:
            logger.error("配置错误: %s", exc)
            return 2
        logger.info(
            "配置有效: profile=%s model=%s audio=%s->%s",
            config.agent.profile,
            config.agent.model,
            config.audio.asr_topic,
            config.audio.tts_topic,
        )
        return 0

    try:
        ensure_runtime_dirs(config)
    except (OSError, ConfigError) as exc:
        logger.error("运行目录不可用: %s", exc)
        return 3

    try:
        from .ros_node import run
    except ImportError as exc:
        logger.error("无法加载 ROS 2 运行环境: %s", exc)
        return 4

    return run(config)



def _doctor(config) -> int:
    """Print a human-readable preflight report without calling the model."""

    logger = logging.getLogger(__name__)
    failures = 0

    def ok(label: str, detail: str = "") -> None:
        print(f"[ OK ] {label}" + (f"  {detail}" if detail else ""))

    def fail(label: str, detail: str) -> None:
        nonlocal failures
        failures += 1
        print(f"[FAIL] {label}  {detail}")

    def warn(label: str, detail: str) -> None:
        print(f"[WARN] {label}  {detail}")

    print("MagicBox Tutor doctor")
    print(f"  profile : {config.agent.profile}")
    print(f"  provider: {config.agent.provider}")
    print(f"  model   : {config.agent.model}")
    print(f"  key env : {config.agent.api_key_env}")
    print()

    for label, path in (
        ("system prompt", config.agent.system_prompt_file),
        ("safety patch", config.agent.patch_file),
    ):
        if path.is_file():
            ok(label, str(path))
        else:
            fail(label, f"missing: {path}")
    if config.agent.provider_patch_file is not None:
        if config.agent.provider_patch_file.is_file():
            ok("provider patch", str(config.agent.provider_patch_file))
        else:
            fail("provider patch", f"missing: {config.agent.provider_patch_file}")

    try:
        ensure_runtime_dirs(config)
        ok("runtime dirs", "writable")
    except (OSError, ConfigError) as exc:
        fail("runtime dirs", str(exc))

    if os.environ.get(config.agent.api_key_env):
        ok("API key", f"{config.agent.api_key_env} is set")
    else:
        warn(
            "API key",
            f"{config.agent.api_key_env} is not in this shell; "
            "systemd loads /etc/magicbox-tutor.env",
        )

    if Path("/dev/snd").exists():
        ok("audio devices", "/dev/snd exists")
    else:
        warn("audio devices", "/dev/snd missing")

    print()
    if failures:
        logger.error("doctor 发现 %d 个问题", failures)
        return 1
    print("doctor: no blocking problems found")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

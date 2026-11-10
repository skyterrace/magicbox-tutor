"""ROS 2 <-> voice tutor bridge.

`audio_io` owns the microphone, wake word, ASR and TTS.  It publishes recognized
text on /prompt_text and plays any Chinese text published on /tts_text.  This
node replaces the stock qwen_llm node: it sends text to DeepSeek Harness and
publishes the answer back, sentence by sentence, followed by the "end" control
message that reopens the microphone.
"""

from __future__ import annotations

import logging
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .agent import DSHTutorAgent
from .config import TutorConfig
from .dialog import Dialog
from .service import TutorService
from .status import StatusWriter


class RosSpeaker:
    def __init__(self, node: Node, topic: str, logger: logging.Logger) -> None:
        self._publisher = node.create_publisher(String, topic, 10)
        self._logger = logger
        self._lock = threading.Lock()

    def say(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._publisher.publish(String(data=text))
        self._logger.info("TTS -> %d 字", len(text))

    def end(self) -> None:
        with self._lock:
            self._publisher.publish(String(data="end"))
        self._logger.info("TTS -> end")


class TutorNode(Node):
    def __init__(self, config: TutorConfig) -> None:
        super().__init__("magicbox_tutor")
        self._config = config
        self._logger = logging.getLogger("magicbox_tutor.node")
        self._speaker = RosSpeaker(self, config.audio.tts_topic, self._logger)
        self._status = StatusWriter(config.status.status_file, logger=self._logger)
        self._agent = DSHTutorAgent(config.agent, logger=logging.getLogger("magicbox_tutor.agent"))
        self._dialog = Dialog(
            self._agent, config.behavior, logger=logging.getLogger("magicbox_tutor.dialog")
        )
        self._service = TutorService(
            config,
            self._dialog,
            self._speaker,
            status=self._status,
            logger=logging.getLogger("magicbox_tutor.service"),
        )
        self._subscription = self.create_subscription(
            String, config.audio.asr_topic, self._on_asr, 10
        )
        self._greeting_timer = None
        if config.behavior.startup_greeting and config.behavior.startup_greeting_delay_s >= 0:
            self._greeting_timer = self.create_timer(
                max(0.1, config.behavior.startup_greeting_delay_s), self._greet_once
            )
        self._service.start()
        self._logger.info(
            "语音助手已启动: %s -> %s, model=%s",
            config.audio.asr_topic,
            config.audio.tts_topic,
            config.agent.model,
        )

    def _on_asr(self, message: String) -> None:
        text = str(message.data or "").strip()
        if not text:
            return
        # Never log the transcript unless the operator explicitly opted in.
        if self._config.agent.log_transcripts:
            self._logger.info("ASR: %s", text)
        else:
            self._logger.info("ASR: %d 字", len(text))
        if "结束对话" in text:
            self._logger.info("收到结束对话，交由 audio_io 休眠")
            return
        if text.strip("，,。.!！?？ ") == self._config.behavior.wake_word:
            # Some ASR/KWS combinations publish the wake word alone.
            return
        if not self._service.submit(text):
            self._logger.info("本轮忙碌，忽略输入")

    def _greet_once(self) -> None:
        timer = self._greeting_timer
        self._greeting_timer = None
        if timer is not None:
            self.destroy_timer(timer)
        self._service.greet(self._config.behavior.startup_greeting)

    def destroy_node(self) -> None:
        self._service.close()
        super().destroy_node()


def run(config: TutorConfig) -> int:
    rclpy.init(args=None)
    node: TutorNode | None = None
    try:
        node = TutorNode(config)
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


def main(config: TutorConfig) -> int:
    return run(config)

#!/usr/bin/env bash
# Start the vendor audio front-end (KWS + ASR + TTS) without qwen_llm.
# audio_io is the only component that touches the microphone and speaker.
set -eo pipefail

source /opt/tros/humble/setup.bash
source /userdata/magicbox/app/ros_ws/install/setup.bash
set -u

export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

AUDIO_DEVICE="${AUDIO_DEVICE:-plughw:0,0}"
ASR_MODEL_PATH="${ASR_MODEL_PATH:-/userdata/magicbox/config/sense-voice-small-fp16.gguf}"
TTS_MODEL_DIR="${TTS_MODEL_DIR:-/userdata/magicbox/dep/matcha-icefall-zh-baker}"
KWS_MODEL_DIR="${KWS_MODEL_DIR:-/userdata/magicbox/dep/sherpa-onnx/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01}"

for path in "$ASR_MODEL_PATH" "$TTS_MODEL_DIR" "$KWS_MODEL_DIR"; do
  if [ ! -e "$path" ]; then
    echo "magicbox-tutor-audio: missing model path: $path" >&2
    exit 1
  fi
done

# wait_for_llm=false is essential: the stock audio node otherwise waits forever
# for a qwen_llm node that this project intentionally does not run.
exec ros2 run audio_io audio_io --ros-args \
  -p "micphone_name:=$AUDIO_DEVICE" \
  -p "wait_for_llm:=false" \
  -p "continuous_wake_mode:=false" \
  -p "asr_pub_topic_name:=/prompt_text" \
  -p "tts_sub_topic_name:=/tts_text" \
  -p "asr_model_path:=$ASR_MODEL_PATH" \
  -p "tts_config_path:=$TTS_MODEL_DIR" \
  -p "kws_config_path:=$KWS_MODEL_DIR" \
  --log-level warn

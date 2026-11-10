#!/usr/bin/env bash
# One-time installer for the MagicBox voice tutor.
#
# Run as root from the repository checkout:
#   sudo ./scripts/install.sh
#
# It does NOT ask for the API key interactively.  Put the key in
# /etc/magicbox-tutor.env before or after installation, then restart the tutor.
set -euo pipefail

APP_DIR="/opt/magicbox-tutor"
ETC_DIR="/etc/magicbox-tutor"
ENV_FILE="/etc/magicbox-tutor.env"
DATA_DIR="/userdata/magicbox-tutor"
RUN_USER="${MAGICBOX_TUTOR_USER:-${SUDO_USER:-sunrise}}"
SKIP_DEPS=0
NO_START=0

for arg in "$@"; do
  case "$arg" in
    --skip-deps) SKIP_DEPS=1 ;;
    --no-start) NO_START=1 ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行：sudo $0" >&2
  exit 1
fi

if ! id "$RUN_USER" >/dev/null 2>&1; then
  echo "运行用户不存在: $RUN_USER（可用 MAGICBOX_TUTOR_USER=... 指定）" >&2
  exit 1
fi
if [ "$RUN_USER" = "root" ]; then
  echo "拒绝以 root 运行语音助手；请用普通桌面用户（默认 sunrise）" >&2
  exit 1
fi
RUN_GROUP="$(id -gn "$RUN_USER")"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/7] 检查 RDK / TROS / audio_io"
if [ ! -f /opt/tros/humble/setup.bash ]; then
  echo "找不到 /opt/tros/humble/setup.bash，请确认这是 RDK X5 MagicBox 系统" >&2
  exit 1
fi
if ! bash -c 'source /opt/tros/humble/setup.bash; source /userdata/magicbox/app/ros_ws/install/setup.bash; ros2 pkg prefix audio_io >/dev/null 2>&1'; then
  echo "找不到 audio_io 包，请确认 MagicBox 官方应用已安装" >&2
  exit 1
fi
if ! arecord -l 2>/dev/null | grep -q '^card '; then
  echo "警告：当前没有检测到声卡。请检查 MagicBox 音频排线/设备树，再启动服务。" >&2
fi

echo "[2/7] 安装应用文件到 $APP_DIR"
install -d -m 755 "$APP_DIR"
if [ "$ROOT" != "$APP_DIR" ]; then
  for item in src config patches scripts systemd; do
    install -d "$APP_DIR/$item"
    cp -a "$ROOT/$item/." "$APP_DIR/$item/"
  done
  cp -a "$ROOT/pyproject.toml" "$APP_DIR/pyproject.toml"
  cp -a "$ROOT/README.md" "$APP_DIR/README.md"
fi

echo "[3/7] 创建运行目录 $DATA_DIR"
install -d -m 700 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_DIR"
install -d -m 700 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_DIR/dsh-home"
install -d -m 700 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_DIR/workspace"
install -d -m 700 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_DIR/state"

echo "[4/7] 安装 Python 依赖到 $APP_DIR/venv"
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
  python3 -m venv --system-site-packages "$APP_DIR/venv"
fi
if [ "$SKIP_DEPS" -eq 0 ]; then
  "$APP_DIR/venv/bin/python" -m pip install --upgrade pip >/dev/null
  "$APP_DIR/venv/bin/pip" install "deepseek-harness-sdk==0.2.1rc2" "PyYAML>=6"
else
  echo "  跳过第三方依赖安装（--skip-deps）"
fi
# The editable install itself is offline and must always run so that
# `python -m magicbox_tutor` resolves the package.
"$APP_DIR/venv/bin/pip" install --no-deps -e "$APP_DIR"
chmod -R a+rX "$APP_DIR"

echo "[5/7] 安装配置与密钥模板"
install -d -m 755 "$ETC_DIR"
if [ ! -f "$ETC_DIR/config.yaml" ]; then
  install -m 644 "$ROOT/config/tutor.yaml" "$ETC_DIR/config.yaml"
else
  echo "  保留已有配置: $ETC_DIR/config.yaml"
fi
install -m 644 "$ROOT/config/tutor_system_prompt.md" "$ETC_DIR/tutor_system_prompt.md"
install -m 644 "$ROOT/config/tutor.qwen.yaml" "$ETC_DIR/tutor.qwen.yaml"
if [ ! -f "$ENV_FILE" ]; then
  install -m 600 /dev/null "$ENV_FILE"
  {
    echo "# MagicBox Tutor secrets. Keep this file 0600."
    echo "DEEPSEEK_API_KEY="
    echo "# Optional DeepSeek-compatible gateway:"
    echo "# DEEPSEEK_BASE_URL=https://api.deepseek.com"
    echo "# Optional Qwen Bailian / DashScope (see config/tutor.qwen.yaml):"
    echo "# QWEN_TOKEN_PLAN_CN_API_KEY="
    echo "# QWEN_TOKEN_PLAN_API_KEY="
    echo "# DASHSCOPE_API_KEY="
    echo "AUDIO_DEVICE=plughw:0,0"
  } > "$ENV_FILE"
  echo "  已创建 $ENV_FILE（请填入 DeepSeek / Qwen 对应的 API key）"
else
  echo "  保留已有密钥文件: $ENV_FILE"
fi
chown "$RUN_USER:$RUN_GROUP" "$ENV_FILE" 2>/dev/null || true
chmod 600 "$ENV_FILE" 2>/dev/null || true

if ! grep -Eq '^(DEEPSEEK_API_KEY|DASHSCOPE_API_KEY|QWEN_TOKEN_PLAN_CN_API_KEY|QWEN_TOKEN_PLAN_API_KEY)=.+' "$ENV_FILE"; then
  echo "警告：$ENV_FILE 里还没有可用的 API key（DeepSeek 或千问百炼）。" >&2
  echo "      填入后运行: systemctl restart magicbox-tutor" >&2
fi

echo "[6/7] 校验安装并安装 systemd 服务"
if command -v runuser >/dev/null 2>&1; then
  runuser -u "$RUN_USER" -- "$APP_DIR/venv/bin/python" -m magicbox_tutor \
    --config "$ETC_DIR/config.yaml" --check
else
  su -s /bin/sh "$RUN_USER" -c \
    "'$APP_DIR/venv/bin/python' -m magicbox_tutor --config '$ETC_DIR/config.yaml' --check"
fi
if systemctl is-active --quiet magicbox-start 2>/dev/null; then
  systemctl stop magicbox-start || true
fi
if systemctl is-enabled --quiet magicbox-start 2>/dev/null; then
  systemctl disable magicbox-start || true
fi
echo "  已确保官方 magicbox-start 不再占用音频（如原本启用）。"
for unit in magicbox-tutor-audio.service magicbox-tutor.service; do
  sed -e "s/__RUN_USER__/$RUN_USER/g" -e "s/__RUN_GROUP__/$RUN_GROUP/g" \
    "$ROOT/systemd/$unit" > "/etc/systemd/system/$unit"
  chmod 644 "/etc/systemd/system/$unit"
done
systemctl daemon-reload

echo "[7/7] 启动服务"
if [ "$NO_START" -eq 0 ]; then
  if ! systemctl enable --now magicbox-tutor-audio.service; then
    echo "警告：audio 服务启动失败，请检查声卡/音频排线。" >&2
  fi
  if ! systemctl enable --now magicbox-tutor.service; then
    echo "警告：tutor 服务启动失败，请检查 DSH/API key。" >&2
  fi
else
  systemctl enable magicbox-tutor-audio.service magicbox-tutor.service
fi

cat <<EOF

安装完成。

  运行用户: $RUN_USER
  配置:     $ETC_DIR/config.yaml
  人设:     $ETC_DIR/tutor_system_prompt.md
  密钥:     $ENV_FILE
  状态:     /run/magicbox-tutor/status.json
  日志:     journalctl -u magicbox-tutor -f

第一次使用前：
  1. 编辑 $ENV_FILE，填入 DEEPSEEK_API_KEY。
  2. systemctl restart magicbox-tutor
  3. 对设备说“你好地瓜”，听到提示音后再提问。
  4. 说“结束对话”让设备休眠。

恢复官方演示：systemctl disable --now magicbox-tutor magicbox-tutor-audio
                systemctl enable --now magicbox-start
EOF

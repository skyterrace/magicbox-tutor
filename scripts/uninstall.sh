#!/usr/bin/env bash
# Stop and remove the MagicBox Tutor services.
# Data is kept by default; pass --purge to delete /userdata/magicbox-tutor.
set -euo pipefail

ETC_DIR="/etc/magicbox-tutor"
ENV_FILE="/etc/magicbox-tutor.env"
PURGE=0
RESTORE_STOCK=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    --restore-stock) RESTORE_STOCK=1 ;;
    -h|--help)
      sed -n '2,3p' "$0"
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

systemctl disable --now magicbox-tutor.service magicbox-tutor-audio.service 2>/dev/null || true
rm -f /etc/systemd/system/magicbox-tutor.service
rm -f /etc/systemd/system/magicbox-tutor-audio.service
systemctl daemon-reload

if [ "$RESTORE_STOCK" -eq 1 ]; then
  systemctl enable --now magicbox-start 2>/dev/null || true
  echo "已尝试恢复官方 magicbox-start。"
fi

if [ "$PURGE" -eq 1 ]; then
  target="/userdata/magicbox-tutor"
  if [ "$(realpath -m "$target")" = "/userdata/magicbox-tutor" ]; then
    rm -rf -- "$target"
    echo "已删除 $target"
  else
    echo "拒绝删除异常路径: $target" >&2
    exit 1
  fi
fi

echo "服务已移除。配置 $ETC_DIR 与密钥 $ENV_FILE 未自动删除。"

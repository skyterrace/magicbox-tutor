#!/usr/bin/env bash
# Archive the current DSH conversation history, then restart with a clean one.
# Requires explicit --yes because it moves persisted sessions.
set -euo pipefail

DATA_DIR="/userdata/magicbox-tutor"
SESSIONS="$DATA_DIR/dsh-home/sessions"

if [ "${1:-}" != "--yes" ]; then
  echo "用法: sudo $0 --yes" >&2
  echo "会把当前 sessions 目录移动为带时间戳的备份，不会直接删除。" >&2
  exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行：sudo $0 --yes" >&2
  exit 1
fi

systemctl stop magicbox-tutor.service 2>/dev/null || true
if [ -d "$SESSIONS" ]; then
  backup="$DATA_DIR/sessions.bak.$(date +%Y%m%d-%H%M%S)"
  mv -- "$SESSIONS" "$backup"
  echo "已备份到 $backup"
else
  echo "没有找到 $SESSIONS，跳过备份。"
fi
systemctl start magicbox-tutor.service 2>/dev/null || true
echo "已重启 magicbox-tutor。"

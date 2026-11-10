#!/usr/bin/env bash
# If the root filesystem came up read-only, try a standard remount and restart.
# This is intentionally explicit: it changes a system-wide mount, not app state.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行：sudo $0" >&2
  exit 1
fi

echo "before: $(findmnt -no TARGET,OPTIONS /)"
mount -o remount,rw /
echo "after : $(findmnt -no TARGET,OPTIONS /)"
touch /userdata/.magicbox-write-test
rm -f /userdata/.magicbox-write-test
echo "root filesystem is writable again."

if systemctl list-unit-files magicbox-tutor.service >/dev/null 2>&1; then
  systemctl restart magicbox-tutor
  echo "magicbox-tutor restarted."
fi

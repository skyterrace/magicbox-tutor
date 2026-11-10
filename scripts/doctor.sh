#!/usr/bin/env bash
# Read-only-ish preflight: config, files, writability, key presence.
# Run as the service user so permissions match the real runtime:
#   sudo -u sunrise /opt/magicbox-tutor/scripts/doctor.sh
set -uo pipefail

CONFIG="${MAGICBOX_TUTOR_CONFIG:-/etc/magicbox-tutor/config.yaml}"
ENV_FILE="${MAGICBOX_TUTOR_ENV_FILE:-/etc/magicbox-tutor.env}"
VENV="${MAGICBOX_TUTOR_VENV:-/opt/magicbox-tutor/venv}"

if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  echo "[WARN] cannot read $ENV_FILE as $(id -un); key check may be incomplete" >&2
fi

exec "$VENV/bin/python" -m magicbox_tutor --doctor --config "$CONFIG"

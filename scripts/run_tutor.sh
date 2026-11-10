#!/usr/bin/env bash
# Start the voice-only tutor.  No stdin is read; systemd runs this with
# StandardInput=null and sends logs to the journal.
set -eo pipefail

source /opt/tros/humble/setup.bash
source /userdata/magicbox/app/ros_ws/install/setup.bash
set -u

export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export PYTHONUNBUFFERED=1

CONFIG="${MAGICBOX_TUTOR_CONFIG:-/etc/magicbox-tutor/config.yaml}"
if [ ! -f "$CONFIG" ]; then
  echo "magicbox-tutor: missing config: $CONFIG" >&2
  exit 1
fi

VENV="${MAGICBOX_TUTOR_VENV:-/opt/magicbox-tutor/venv}"
exec "$VENV/bin/python" -m magicbox_tutor --config "$CONFIG" "$@"

#!/usr/bin/env bash
# Captures the OSOYOO car's CSI camera and publishes it to mediamtx.
# Run this alongside mediamtx (see pi_setup/systemd/streaming.service for
# running both on boot).
#
# rpicam-vid is the modern libcamera-based capture tool on current
# Raspberry Pi OS (successor to raspivid) — confirmed as the right tool
# since this kit's camera is CSI, not USB (docs/architecture.md section 5).
set -euo pipefail

MEDIAMTX_RTSP_URL="rtsp://localhost:8554/car"

rpicam-vid \
  --timeout 0 \
  --width 1280 --height 720 --framerate 30 \
  --codec libav --libav-format rtsp \
  --output "$MEDIAMTX_RTSP_URL"

# TODO: tune resolution/framerate/bitrate for actual Wi-Fi conditions once
# testing on the real network — 1280x720@30 is a starting point, not a
# measured-good value.

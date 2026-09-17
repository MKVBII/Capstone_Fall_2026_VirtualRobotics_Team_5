#!/usr/bin/env bash
# Provisioning script for the Raspberry Pi running the OSOYOO car.
#
# OS: stock Raspberry Pi OS (Bookworm, 64-bit) — now that there's no
# ROS 2 in this design, there's no reason to use Ubuntu Server instead.
# Raspberry Pi OS already has rpicam-vid/picamera2 and GPIO tooling set
# up, and matches what OSOYOO's own tutorials assume.
#
# TODO: this is a skeleton — fill in and test on real hardware, then
# remove this warning.
set -euo pipefail

echo "== Enabling I2C (required for the PWM HAT / PCA9685) and the camera =="
# sudo raspi-config nonint do_i2c 0
# sudo raspi-config nonint do_camera 0

echo "== Installing Python + venv =="
sudo apt update
sudo apt install -y python3-pip python3-venv i2c-tools

echo "== Setting up pi-server =="
cd "$(dirname "$0")/../pi-server"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Once wiring up real hardware, also:
# pip install RPi.GPIO adafruit-circuitpython-pca9685 adafruit-blinka

echo "== Installing mediamtx (video streaming server) =="
# Download the arm64 release matching your Pi from:
#   https://github.com/bluenviron/mediamtx/releases
# and place the binary at streaming/mediamtx

echo "== Done. Install systemd services from pi_setup/systemd/ to run on boot. =="
echo "== Serve quest-client/ over https:// — see docs/setup_guide.md, WebXR requires a secure context. =="

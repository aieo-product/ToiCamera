#!/usr/bin/env bash
# Build & flash the ToiCamera CamS3 firmware (factory UserDemo + STA-server patch).
# Prereq: ESP-IDF v5.1.4 at ~/esp/esp-idf (see vlogCamera/firmware/README.md)
#   ./build.sh          — build only
#   ./build.sh flash    — build + erase config + flash (CamS3 on USB-C)
set -euo pipefail
cd "$(dirname "$0")"

TREE=build-tree
if [ ! -d "$TREE" ]; then
  git clone -b unitcams3-5mp --depth 1 https://github.com/m5stack/UnitCamS3-UserDemo.git "$TREE"
  (cd "$TREE" && python3 fetch_repos.py && git apply ../patches/0001-toicamera-sta-server.patch)
fi

source ~/esp/esp-idf/export.sh >/dev/null
cd "$TREE/platforms/unitcam_s3_5mp"
idf.py build

if [ "${1:-}" = "flash" ]; then
  PORT=$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)
  # erase wipes the stored LittleFS config -> camera boots in AP mode for pairing
  idf.py -p "$PORT" erase-flash
  idf.py -p "$PORT" flash -b 1500000
fi

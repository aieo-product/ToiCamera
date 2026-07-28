#!/usr/bin/env bash
# One-shot CamS3 STA setup from a Mac.
# Temporarily joins the camera's AP (UnitCamS3-WiFi), posts the WiFi config,
# then switches the Mac back to its previous network.
#
#   ./setup-sta.sh <2.4GHz-ssid> <password>
#
# Run this in your own Terminal (not through an agent session) so the WiFi
# password stays out of transcripts. ESP32 supports 2.4GHz only.
set -euo pipefail

SSID="${1:?usage: ./setup-sta.sh <2.4GHz-ssid> <password>}"
PASS="${2:?missing password}"
CAM_AP="UnitCamS3-WiFi"
CAM_IP="192.168.4.1"
IF="$(networksetup -listallhardwareports | awk '/Wi-Fi/{getline; print $2}')"

CURRENT="$(ipconfig getsummary "$IF" | awk -F' SSID : ' '/ SSID :/{print $2}' | head -1)"
echo "Wi-Fi IF=$IF current='${CURRENT:-?}' -> joining $CAM_AP ..."
networksetup -setairportnetwork "$IF" "$CAM_AP"

echo -n "waiting for $CAM_IP "
for i in $(seq 1 30); do
  if curl -s -m 2 "http://$CAM_IP/api/v1/get_mac" >/dev/null 2>&1; then echo " ok"; break; fi
  echo -n "."; sleep 1
  [ "$i" = 30 ] && { echo " TIMEOUT — is the CamS3 powered? (LED on?)"; exit 1; }
done

echo "camera: $(curl -s http://$CAM_IP/api/v1/get_mac)"
echo "posting STA config (ssid=$SSID) ..."
curl -s -X POST "http://$CAM_IP/api/v1/set_config" -H "Content-Type: application/json" \
  -d "{\"wifiSsid\":\"$SSID\",\"wifiPass\":\"$PASS\",\"startPoster\":\"no\",\"postInterval\":5,\"nickname\":\"ToiCamera\",\"timeZone\":\"GMT+9\"}"
echo
echo "saved config: $(curl -s http://$CAM_IP/api/v1/get_config)"

if [ -n "${CURRENT:-}" ]; then
  echo "switching Mac back to '$CURRENT' ..."
  networksetup -setairportnetwork "$IF" "$CURRENT" || true
fi

cat <<'NEXT'

Done. Next steps:
  1. Power-cycle the CamS3 (unplug/replug Grove or Stopwatch off/on)
  2. It should join your LAN as "ToiCamera" — find its IP from the router's
     DHCP table, or run: ./find-cams3.sh
  3. Verify:  curl http://<ip>/api/v1/capture -o test.jpg && open test.jpg
  (To return the camera to AP mode later: re-run with an empty ssid "" )
NEXT

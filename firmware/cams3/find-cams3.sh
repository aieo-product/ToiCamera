#!/usr/bin/env bash
# Locate the CamS3 on the LAN after STA setup (matches by MAC OUI / probe).
# Sweeps the local /24, then probes candidates for the factory API.
set -euo pipefail

IF="$(networksetup -listallhardwareports | awk '/Wi-Fi/{getline; print $2}')"
MYIP="$(ipconfig getifaddr "$IF")"
NET="${MYIP%.*}"
echo "sweeping ${NET}.0/24 from $MYIP ..."

for i in $(seq 1 254); do (ping -c1 -W1 "${NET}.${i}" >/dev/null 2>&1 &) ; done
sleep 3

arp -a -i "$IF" | awk -F'[()]' '{print $2}' | while read -r ip; do
  [ "$ip" = "$MYIP" ] && continue
  mac=$(curl -s -m 1 "http://$ip/api/v1/get_mac" 2>/dev/null || true)
  if echo "$mac" | grep -q '"mac"'; then
    echo "FOUND CamS3 at $ip  ($mac)"
    echo "→ firmware/stopwatch/gen-secrets.sh の第5引数にこの IP を渡してください"
  fi
done
echo "sweep done."

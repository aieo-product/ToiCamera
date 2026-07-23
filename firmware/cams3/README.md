# Unit CamS3 firmware

## ✅ Variant: 5MP — confirmed via the vlogCamera project

The exact unit was verified on 2026-06-02 in
[aieo-product/vlogCamera](https://github.com/aieo-product/vlogCamera)
(`hardware-verification/`, device MAC `3C:DC:75:77:82:94`): it runs the
**factory firmware `UnitCamS3-UserDemo` branch `unitcams3-5mp`** (5MP, max
QSXGA 2592×1944). No variant identification step needed.

## Strategy: use the factory firmware as-is (no custom build for MVP)

The factory firmware already serves a full REST API
(19/19 smoke tests passed in vlogCamera):

| Endpoint | Use in ToiCamera |
|---|---|
| `GET /api/v1/capture` | still JPEG — the Stopwatch polls this |
| `GET /api/v1/control?var=<k>&val=<v>` | `framesize`/`quality`/`awb`/`aec`/`agc`/`vflip`/`hmirror`… |
| `GET /api/v1/status` | sensor state (JSON) |
| `GET /api/v1/led_on` / `led_off` | capture LED feedback |
| `POST /api/v1/set_config` | `{wifiSsid, wifiPass, ...}` → STA mode on reboot |
| `GET /api/v1/stream` | MJPEG (VGA ≈11fps) — future pseudo-preview |

Full reference: `vlogCamera/hardware-verification/api-reference.md`.

### ⚠️ Known gotcha: near-black images by default

Factory defaults ship with `awb/aec/agc` **all OFF** → captures average
luminance ~3/255. The Stopwatch firmware fixes this at boot by calling
`configureCamera()` (awb=1, awb_gain=1, aec=1, agc=1, gainceiling=2,
framesize=SVGA, quality=12). If testing the camera standalone, apply the same
via curl first.

### WiFi modes are exclusive (AP ⇔ STA)

- `wifiSsid` empty → AP mode `UnitCamS3-WiFi` (192.168.4.1)
- `wifiSsid` set → STA mode joins your LAN (**the AP disappears**)

**Setup procedure for ToiCamera (one-time):**

```bash
# 1. Join the camera's AP "UnitCamS3-WiFi" (e.g. from a phone or the Mac)
H=192.168.4.1
# 2. Point it at your LAN (factory get_wifi_list is buggy/empty — set directly)
curl -s -X POST http://$H/api/v1/set_config -H "Content-Type: application/json" \
  -d '{"wifiSsid":"<your-ssid>","wifiPass":"<your-pass>","startPoster":"no","postInterval":5,"nickname":"ToiCamera","timeZone":"GMT+9"}'
# 3. Power-cycle. Find its LAN IP (router DHCP table / arp) and give it a
#    DHCP reservation; put "http://<ip>" into firmware/stopwatch/secrets.ini (CAM_BASE)
# 4. Verify from the LAN:
curl -s http://<ip>/api/v1/status | jq .
curl -s http://<ip>/api/v1/capture -o test.jpg && file test.jpg
```

**Open verification point:** vlogCamera confirmed STA mode joins the LAN for
the EzData poster flow, but did not verify that the HTTP server stays
reachable on the STA IP. Step 4 above is the go/no-go check. To return to AP
mode, set `wifiSsid` back to empty (or `reset_config`).

### Fallback if STA + HTTP server doesn't work

Rebuild the firmware with vlogCamera's patch/overlay approach
(`vlogCamera/firmware/` — ESP-IDF v5.1.4, patches onto UserDemo
`unitcams3-5mp`, includes a WiFi reconnect watchdog and an AP-fallback patch).
That repo's `firmware/README.md` + `BUILD-lite-page.md` document the build.
Vendor the result into this directory if we go that route.

## Power

No battery on board. Grove red=5V / black=GND from the Stopwatch powers it
(200–400mA peaks). The Grove data pins are **USB D+/D- (G19/G20)** — do not
drive UART signals into them. The Stopwatch enables its PMIC-gated 5V output
at boot (`cfg.output_power` / `M5.Power.setExtOutput(true)`).

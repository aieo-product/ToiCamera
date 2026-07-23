# Unit CamS3 firmware

The camera unit runs its own ESP32-S3. Our target firmware behavior:

- Join the LAN in **STA mode** (same WiFi as the Stopwatch)
- Serve `GET /capture` → still JPEG (SVGA〜XGA, quality ≈12)
- Optional `GET /stream` → MJPEG (for a future pseudo-preview)
- Blink the LED on capture

## Step 0 — identify your sensor variant (do this first!)

The 2MP (OV2640) and 5MP (PY260) versions share the same PCB and silkscreen.
With the **factory firmware** installed:

1. Power the unit, connect to its WiFi AP `UnitCamS3-WiFi`
2. Open `http://192.168.4.1/` and press **Capture**
3. Check the saved image resolution:
   - **1600×1200** → 2MP OV2640
   - **2592×1944** → 5MP PY260

(Alternatively, M5Burner shows which factory firmware the unit matches.)

## Path A — 5MP PY260 variant

The PY260 driver is **not** in mainline `espressif/esp32-camera`
([esphome#10286](https://github.com/esphome/issues/issues/10286)). Base on
[hbentel/M5Stack-Unit-CamS3-5MP](https://github.com/hbentel/M5Stack-Unit-CamS3-5MP)
(Apache-2.0, ESP-IDF 5.3.2), which vendors a working PY260 driver (XCLK pinned
at 10MHz) and already serves a JPEG snapshot on port 80 and MJPEG on port 81.

Planned modifications (fork into this directory):

- Hard-code STA credentials via build config (or keep its BLE provisioning)
- Default frame size SVGA–XGA, JPEG quality ~12
- Strip MQTT/Frigate integration
- Keep `/health`, add capture LED blink

**Pin the esp32-camera fork version — never upgrade it** (2.1.6 broke PY260).

Fallback: M5Stack's official `UnitCamS3-UserDemo` branch `unitcams3-5mp` (MIT).

## Path B — 2MP OV2640 variant

Mainline `esp32-camera` supports OV2640 — a small Arduino/ESP-IDF sketch with
`esp_camera` + an HTTP server (~100 lines) is simpler than modifying anything.
Sketch will be added here once the variant is confirmed.

## Last-resort fallback

The factory firmware itself serves JPEG over HTTP in AP mode. The Stopwatch
could join `UnitCamS3-WiFi` to capture — but then it loses internet access for
the AI call, so this is only useful for demos with pre-canned analysis.

## Power

No battery on board. Grove red=5V / black=GND from the Stopwatch powers it
(expect 200–400mA peaks during capture/WiFi). The Grove data pins are **USB
D+/D- (G19/G20)** — do not drive UART signals into them with stock firmware.

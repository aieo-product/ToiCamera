# ToiCamera — a watch that tells you about what it sees

> **Toi** (問い) is Japanese for *a question* — and it sounds like *toy*.
> ToiCamera is a wrist-worn AI camera you ask questions with: point, shoot,
> and it explains the world — on screen and out loud.

Built on the **M5Stack StopWatch Dev Kit (ESP32-S3, C152)** + **Unit CamS3 5MP** + **Unit GPS v1.1**, with a **Cloudflare Worker** as the AI relay.
Entry for the [M5Stack Global Innovation Contest 2026](https://m5stack.com/global-innovation-contest-2026).

| | |
|---|---|
| 📷 | **Zero-lag shutter** — the live finder frame *is* the photo |
| 🗣 | **AI explanations** spoken in on-device Animal-Crossing-style chirps (no cloud TTS) |
| 🎤 | **Hold-to-talk Q&A** about the photo (STT → context-aware answer) |
| 📍 | **Location-aware** — reverse-geocoded town, nearest station, place-flavored explanations |
| ⌚ | **A real watch** — clock (NTP→RX8130), battery ring, steps, daily AI one-liner |
| 🌐 | **Multilingual** — AI content in 日本語 / English / 中文, switchable on the watch |
| 🧱 | **LEGO-compatible expansion plate** — 3D-printed backpack, camera & GPS clip anywhere |

## Architecture

```
Unit CamS3 (custom firmware)
   │  Wi-Fi: joins the watch's own SoftAP "ToiCamera" (192.168.4.1)
   │  Grove: 5 V power only
   ▼
M5Stack StopWatch (Arduino + M5Unified, single-file app)
   │  Wi-Fi STA: home LAN or phone hotspot (internet only)
   ▼
Cloudflare Worker (TypeScript — holds every API key; device sends a token)
   ├─ POST /analyze  vision LLM, strict JSON schema, location-hint injection
   ├─ POST /ask      STT + answer in the photo's context
   ├─ POST /digest   one-line "what am I doing today" summary
   └─ GET  /place    OSM Nominatim reverse geocode + nearest station (edge-cached)
```

No router or PC on the camera path — the watch hosts a private AP for the camera
(SoftAP+STA simultaneously), so the whole rig works outdoors on a phone hotspot.

## Repository layout

| Path | Contents |
|---|---|
| `firmware/stopwatch/` | Watch firmware (PlatformIO / Arduino / M5Unified). State machine: Home dashboard / finder / capture / result / sleep / Wi-Fi + token portal |
| `firmware/cams3/` | Build script + patches adding an "STA server" boot mode to the vendor UnitCamS3-5MP firmware (ESP-IDF 5.1) |
| `worker/` | Cloudflare Worker: multilingual prompts (ja/en/zh), strict JSON schemas, free-quota handling with reset-time reporting |
| `case/` | Parametric Blender→STL scripts for the LEGO-compatible back plates + a three.js assembly simulator (`case/simulator/`) |
| `docs/` | Design doc (`DESIGN.md`, JA), wiring, photos, demo script |

## Getting started

Everything here runs against **your own Cloudflare Worker** — this repo contains no
live backend. Deploying one takes about 10 minutes: **[Worker setup guide](docs/worker-setup.md)**.

1. **Worker** — deploy your own AI relay first: `cd worker && npx wrangler deploy`, then `wrangler secret put` the keys listed in `wrangler.jsonc` comments (OpenAI API key, a device token you make up). Full walkthrough: [docs/worker-setup.md](docs/worker-setup.md).
2. **Camera firmware** — `firmware/cams3/build.sh` (ESP-IDF v5.1.4). Flash with `erase-flash` first; see `firmware/cams3/README.md` for the sensor's quirks (the 5 MP PY260 ignores its quality register — verified on hardware).
3. **Secrets** — `cp firmware/stopwatch/secrets.ini.example firmware/stopwatch/secrets.ini` and fill in Wi-Fi credentials, your Worker URL from step 1 and the same device token (`gen-secrets.sh` automates this). `secrets.ini` is gitignored; real values never enter the repo.
4. **Watch firmware** — `cd firmware/stopwatch && pio run -t upload`.
5. **First boot** — the watch auto-provisions the camera onto its own AP (one-time, no PC involved). Wi-Fi and the device token can later be changed from the watch itself: Settings → WiFi → scan the QR → `http://192.168.4.1`.
6. **Back plate** — print `case/blender/out/toicamera_duo.stl` for simultaneous CamS3 + GPS mounting (camera upper row, GPS lower-left or lower-right), `toicamera_grid3.stl` for the watch-outline 3-column plate, or `toicamera.stl` for the taller 12-hole rack. Swap the two rear M2 screws for ~3 mm longer ones and attach the units with M5Stack CLIP-A/B or pin brackets; see [`case/README.md`](case/README.md).

## Security notes

- **No secrets in this repo** — API keys live only as Worker secrets; the device authenticates with a device token from `secrets.ini` (or provisioned at runtime via the portal, stored in NVS, never logged).
- The watch's AP password defaults to the value in `firmware/stopwatch/src/main.cpp` (`TOI_AP_PASS`). **Override it via build flag before deploying your own** — anyone who joins that AP can reach the setup portal.
- Device→Worker TLS uses `setInsecure()` — acceptable here because the device only talks to its own Worker and sends nothing beyond the device token; pin the root CA if you fork this for anything serious.

## Demo

- 2-minute demo video: *[YouTube link — see the Hackster article]*
- Hackster article: *[link once published]*

## License

MIT — see [LICENSE](LICENSE). The CamS3 patches apply on top of M5Stack's open-source UnitCamS3 firmware (see `firmware/cams3/README.md` for provenance).

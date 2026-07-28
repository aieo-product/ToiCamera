# ToiCamera — AI Explainer Camera

> **Toi** (問い) is Japanese for "a question" — and it sounds like *toy*.
> ToiCamera is a toy-like camera you ask questions with: shoot something,
> and the AI tells you what you're looking at.

A pocket AI camera built from the **M5Stack Stopwatch Dev Kit (ESP32-S3, SKU C152)** and the **M5Stack Unit CamS3**. Press the yellow shutter button, and the device captures a photo, shows it on the 1.75" round AMOLED, and an AI narrator explains what it sees — on screen and out loud through the built-in speaker (Japanese TTS).

Built for the [M5Stack Global Innovation Contest 2026](https://m5stack.com/global-innovation-contest-2026).

## How it works

```
┌─────────────┐   Grove (5V power only)   ┌──────────┐
│  Stopwatch  │═════════════════════════│  CamS3   │
│ SoftAP+STA  │◀── WiFi: its own AP ───── │(custom FW)│
│ AMOLED/SPK  │    "ToiCamera"            └──────────┘
└──────┬──────┘    GET /api/v1/capture (JPEG)
       │  WiFi STA (home LAN or phone hotspot — internet only)
       └─ HTTPS POST /analyze ─▶ Cloudflare Worker ─▶ AI vision
          HTTPS POST /tts ─────▶ Cloudflare Worker ─▶ TTS (WAV stream)
```

No router or PC on the camera path: the Stopwatch hosts a private AP for the
camera (ESP32 SoftAP+STA), so the whole rig works outdoors on a phone hotspot.

- **Stopwatch** (host/UI): captures via HTTP from the CamS3, displays the JPEG, calls the AI relay, renders Japanese text (M5GFX efontJA) and plays the TTS WAV through its 1W speaker.
- **Unit CamS3** (camera): custom firmware (factory OSS + STA-server patch) joins the Stopwatch's private AP and serves the factory REST API (`/api/v1/capture`). Powered from the Stopwatch's Grove 5V — no battery needed.
- **Cloudflare Worker** (AI relay): holds all API keys as secrets, calls the Claude vision API for a structured `{caption, detail}` explanation, and proxies TTS audio as WAV.

## Repository layout

| Path | Contents |
|---|---|
| `firmware/stopwatch/` | Main device firmware (PlatformIO + Arduino + M5Unified) |
| `firmware/cams3/` | Camera unit firmware notes / build (variant-dependent, see its README) |
| `worker/` | Cloudflare Worker AI relay (TypeScript + wrangler) |
| `case/` | 3D-printed compact-camera-style case (Bambu Lab X2D) |
| `docs/` | [Design doc (JA)](docs/DESIGN.md), [wiring](docs/wiring.md), photos, Hackster.io write-up draft |

## Getting started

1. **Camera firmware** — identify your CamS3 sensor variant first, then follow
   [`firmware/cams3/README.md`](firmware/cams3/README.md)
2. **Worker** — deploy the AI relay per [`worker/README.md`](worker/README.md)
3. **Stopwatch secrets** — `./firmware/stopwatch/gen-secrets.sh <ssid> <pass>`
   (WiFi from args, device token pulled from the macOS Keychain via akc)
4. **Stopwatch firmware** — `pio run -t upload` in `firmware/stopwatch/`
   (see [`platformio.ini`](firmware/stopwatch/platformio.ini))

Architecture decisions and the full schedule live in
[`docs/DESIGN.md`](docs/DESIGN.md) (Japanese).

## Security notes

- No API keys live on the device. The Worker holds `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` as wrangler secrets and authenticates the device with an `X-Device-Token` header.
- The device uses `WiFiClientSecure::setInsecure()` for the Worker TLS connection. This skips certificate validation — acceptable here because the device only ever talks to our own Worker and sends no secrets beyond the device token, but pin the root CAs before reusing this in anything sensitive.

## Status

Work in progress — targeting the 2026-08-07 contest deadline. See `docs/` for build progress.

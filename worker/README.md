# AI relay Worker

Cloudflare Worker that holds all API keys and turns a JPEG into a spoken
explanation (ja/en/zh). The device never talks to an AI provider directly.

## Endpoints

| Endpoint | Auth | In | Out |
|---|---|---|---|
| `GET /health` | none | — | `{ok, model}` |
| `GET /config` | `X-Device-Token` | — | `{models, voice, tts}` — model menu + TTS voice name (cached on-device) |
| `POST /analyze` | `X-Device-Token` | raw `image/jpeg` body | `{caption, detail}` (JSON, schema-enforced) |
| `POST /ask` | `X-Device-Token` | raw `audio/wav` + query `caption`, `detail` | `{question, answer}` — STT, then answer in photo context |
| `GET /place` | `X-Device-Token` | query `lat`, `lon` | `{place, station, distance_m, walk_min}` |
| `POST /digest` | `X-Device-Token` | `{"items": ["…"]}` | `{summary}` — one-line day summary |
| `POST /tts` | `X-Device-Token` | `{"text": "..."}` | `audio/wav` (24kHz mono) |

## Setup

```bash
npm install

# Secrets — entered via hidden stdin prompt, never in shell history
npx wrangler secret put TOICAMERA_MAIN_API_KEY   # key for your chat/vision backend (OpenAI by default)
npx wrangler secret put TOICAMERA_TTS_API_KEY    # key for TTS (OpenAI by default; optional — chirp fallback without it)
openssl rand -hex 16 | npx wrangler secret put DEVICE_TOKEN
# (copy the same token into firmware/stopwatch/secrets.ini)

npx wrangler deploy
```

Vars (see `wrangler.jsonc` for defaults and comments): `MODELS`,
`MAIN_API_BASE_URL`, `AUDIO_API_BASE_URL`, `TTS_VOICE`, `TTS_MODEL`,
`ANALYZE_MAX_TOKENS`, `ANALYZE_STYLE_LOW`, `ANALYZE_STYLE_HIGH`.

## Testing

```bash
BASE=https://toicamera.<your-subdomain>.workers.dev
TOKEN=<device token>

curl -s $BASE/health

curl -s -X POST "$BASE/analyze" \
  -H "X-Device-Token: $TOKEN" -H "Content-Type: image/jpeg" \
  --data-binary @test.jpg | jq .

curl -s -X POST "$BASE/tts" \
  -H "X-Device-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"こんにちは、AIカメラです。"}' -o out.wav && afplay out.wav
```

## Model switching / local LLM

The device shows the model menu from the `MODELS` var (comma-separated,
fetched via `GET /config`) and echoes the selection back as `X-Model` — so
adding or swapping chat models is a Worker redeploy, never a firmware change.

Point `MAIN_API_BASE_URL` at any OpenAI-compatible endpoint (e.g. a local
Ollama behind a Cloudflare Tunnel) to run chat/vision on your own hardware.
Note: your `TOICAMERA_MAIN_API_KEY` is sent as a Bearer token to whatever URL
you configure here — only point it at endpoints you control or trust.

Voice caveat: STT for `/ask` authenticates with `TOICAMERA_MAIN_API_KEY`
against `AUDIO_API_BASE_URL` (default `api.openai.com`). If you point
`MAIN_API_BASE_URL` at a local LLM whose key is not valid at OpenAI, voice
questions stop working (TTS keeps working via `TOICAMERA_TTS_API_KEY`).

TTS voice is `TTS_VOICE` (model `TTS_MODEL`, default OpenAI
`gpt-4o-mini-tts`). Any OpenAI-compatible `/audio/speech` backend works via
`AUDIO_API_BASE_URL` — device side needs no change (still WAV).

## Attribution

Reverse geocoding by [Nominatim](https://nominatim.org/) — location data
© OpenStreetMap contributors (ODbL). Station lookup by
[HeartRails Express](https://express.heartrails.com/).

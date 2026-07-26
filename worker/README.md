# AI relay Worker

Cloudflare Worker that holds all API keys and turns a JPEG into a Japanese
explanation + TTS audio.

## Endpoints

| Endpoint | Auth | In | Out |
|---|---|---|---|
| `GET /health` | none | — | `{ok, model}` |
| `POST /analyze` | `X-Device-Token` | raw `image/jpeg` body | `{caption, detail}` (JSON, schema-enforced) |
| `POST /tts` | `X-Device-Token` | `{"text": "..."}` | `audio/wav` (24kHz mono, streamed) |

## Setup

```bash
npm install

# Secrets — values come from the macOS Keychain via akc, never typed in plain text
akc get ANTHROPIC_API_KEY --reveal   | npx wrangler secret put ANTHROPIC_API_KEY
akc get OPENAI_API_KEY --reveal      | npx wrangler secret put OPENAI_API_KEY
akc get OPENAI_FREE_API_KEY --reveal | npx wrangler secret put OPENAI_FREE_API_KEY
openssl rand -hex 16               | npx wrangler secret put DEVICE_TOKEN
# (copy the same token into firmware/stopwatch/secrets.ini)

npx wrangler deploy
```

## Testing

```bash
BASE=https://toicamera.<account>.workers.dev
TOKEN=<device token>

curl -s $BASE/health

curl -s -X POST "$BASE/analyze" \
  -H "X-Device-Token: $TOKEN" -H "Content-Type: image/jpeg" \
  --data-binary @test.jpg | jq .

curl -s -X POST "$BASE/tts" \
  -H "X-Device-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"こんにちは、AIカメラです。"}' -o out.wav && afplay out.wav
```

## Model switching

`/analyze` backend is `ANALYZE_PROVIDER` (currently `openai` = free daily-token
key, model `ANALYZE_MODEL`). Once the Anthropic account is funded:

```bash
npx wrangler deploy --var ANALYZE_PROVIDER:anthropic            # Claude (MODEL var)
npx wrangler deploy --var ANALYZE_PROVIDER:anthropic --var MODEL:claude-sonnet-5  # demo tier
```

TTS voice is `TTS_VOICE` (OpenAI `gpt-4o-mini-tts`). If Japanese quality is not
good enough, swap `handleTts` to Google Cloud TTS `ja-JP-Neural2` with
`LINEAR16` — device side needs no change (still WAV).

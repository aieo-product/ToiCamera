# AI relay Worker

Cloudflare Worker that holds all API keys and turns a JPEG into a spoken
explanation (ja/en/zh). The device never talks to an AI provider directly.

## Endpoints

| Endpoint | Auth | In | Out |
|---|---|---|---|
| `GET /health` | none | — | `{ok, model}` |
| `GET /config` | `X-Device-Token` | — | `{models, voice, tts, realtime, realtimeVoice}` — model menu + TTS voice name + GPT Realtime availability/voice (cached on-device) |
| `POST /analyze` | `X-Device-Token` | raw `image/jpeg` body | `{caption, detail}` (JSON, schema-enforced) |
| `POST /ask` | `X-Device-Token` | raw `audio/wav` + query `caption`, `detail` | `{question, answer}` — STT, then answer in photo context |
| `GET /place` | `X-Device-Token` | query `lat`, `lon` | `{place, station, distance_m, walk_min}` |
| `POST /digest` | `X-Device-Token` | `{"items": ["…"]}` | `{summary}` — one-line day summary |
| `POST /tts` | `X-Device-Token` | `{"text": "...", "engine"?: "realtime"}` | `audio/wav` (24kHz mono), header `X-Voice-Engine: tts\|realtime` — `engine:"realtime"` speaks via the OpenAI Realtime API, falling back to the regular TTS engine (and then on-device chirps) on any failure |
| `POST /kana` | `X-Device-Token` | `{"text": "..."}` | `{kana}` — kana intermediate representation (pitch-accent marks) for the on-device sanoTTS voice |
| `POST /live` | `X-Device-Token` | headers `X-Live: capture\|ask`, `X-Jpeg-Length: N`, `X-Lang`; body = JPEG (N bytes) + WAV (`ask` only) | `application/octet-stream`, chunked — `"TOI1"` then `A`/`T`/`E`/`X` frames, header `X-Voice-Engine: realtime-live`. One Realtime session answers with speech while it is still being generated |

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
`ANALYZE_MAX_TOKENS`, `ANALYZE_STYLE_LOW`, `ANALYZE_STYLE_HIGH`,
`KANA_MODEL`, `KANA_REASONING_EFFORT`, `KANA_BUNDLE`, `ANALYZE_KANA_REASONING_EFFORT`,
`REALTIME_MODEL`, `REALTIME_VOICE`, `REALTIME_API_BASE_URL`.

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

## GPT Realtime voice

The device's fourth Voice option, "GPT Realtime", asks `/tts` for
`{"engine":"realtime"}`. The Worker opens an outbound WebSocket to the OpenAI
Realtime API (`REALTIME_API_BASE_URL`, default `api.openai.com/v1`,
`REALTIME_MODEL` default `gpt-realtime`), reusing `TOICAMERA_TTS_API_KEY` as
the bearer token — Realtime is OpenAI-only, so it does not follow
`AUDIO_API_BASE_URL`. Realtime speaks the text (unmodified — asked to read it
verbatim) as PCM16 24kHz mono, which the Worker collects and wraps into the
same WAV shape `/audio/speech` already returns, so the device's playback path
is unchanged. Voice is `REALTIME_VOICE` (default `marin`; must be a Realtime voice —
alloy/ash/ballad/coral/echo/sage/shimmer/verse/marin/cedar; empty = reuse
`TTS_VOICE`).

If Realtime errors, times out (15 s), disconnects before `response.done`, or
returns no audio, `/tts` discards any partial audio and transparently falls
back to the regular TTS engine (the device allows 45 s for a Realtime request
so both attempts fit), and the device falls back further to chirps if that
also fails — GPT Realtime never causes silence. The response
carries `X-Voice-Engine: realtime` or `tts` so you can see which one answered.
`GET /config` reports `realtime: true` whenever `TOICAMERA_TTS_API_KEY` is set,
plus `realtimeVoice`, so the device can show `Realtime(<voice>)` in Settings.

```bash
curl -s -X POST "$BASE/tts" \
  -H "X-Device-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"こんにちは、AIカメラです。","engine":"realtime"}' \
  -D - -o out.wav && afplay out.wav
```

## Live (Realtime, streaming)

`POST /live` replaces `/analyze` + `/tts` (and `/ask` + `/tts`) for the device's
"GPT Realtime" voice with a **single** Realtime session: the photo — and, for a
voice question, the recorded audio — go up in one `response.create`, and the
spoken answer is streamed back frame by frame as it is generated, so the device
can start playing after the first chunk instead of waiting for a finished WAV.

**Request**

| Header | Value |
|---|---|
| `X-Live` | `capture` (explain the photo) or `ask` (answer the spoken question about it) |
| `X-Jpeg-Length` | byte length `N` of the JPEG that starts the body (1 … 2 MB) |
| `X-Lang` | `ja` (default) / `en` / `zh` — instructions and speech are pinned to it |

Body = `N` bytes of JPEG (must start `FF D8`), then, for `ask`, a RIFF/WAVE file
(PCM 16-bit mono, any sample rate, 4 KB … 2 MB). The Worker linearly resamples
it to the 24 kHz mono PCM the Realtime API accepts (the device records 16 kHz).

**Response** — `application/octet-stream`, chunked, `X-Voice-Engine:
realtime-live`, `Cache-Control: no-store`. The body is the 4-byte magic `TOI1`
followed by frames of `type (1 B) + length (uint32 LE) + payload`:

| Type | Payload |
|---|---|
| `A` | PCM16 mono 24 kHz audio bytes — one Realtime `output_audio` delta, verbatim |
| `T` | transcript delta (UTF-8), interleaved with the audio |
| `E` | terminal JSON `{caption, detail, transcript, status:"completed", pcmBytes, ms}` — `caption` is the first sentence (≤15 chars ja/zh, ≤15 words en), `detail` the rest |
| `X` | error JSON `{error}` — the device falls back to `/analyze` + `/tts`, then to chirps |

Exactly one `E` or `X` frame ends the stream. Everything after the upgrade is
reported inside the stream: a Realtime `error` event, a disconnect before
`response.done`, a non-`completed` status, or the 30 s timeout all produce `X`.
Failures *before* the WebSocket opens are plain JSON instead — 503
`{"error":"realtime unavailable"}` when `TOICAMERA_TTS_API_KEY` is unset, 502 on
an upgrade or connect failure, 400/413 on a malformed body. Audio is capped at
1.9 MB (~40 s); past that the stream stops forwarding `A` frames but still ends
with `E`. Model and voice are `REALTIME_MODEL` / `REALTIME_VOICE`, same as
`/tts engine:"realtime"`.

```bash
curl -s --no-buffer -X POST "$BASE/live" \
  -H "X-Device-Token: $TOKEN" -H "X-Live: capture" -H "X-Lang: ja" \
  -H "X-Jpeg-Length: $(stat -f%z test.jpg)" \
  --data-binary @test.jpg -D - -o live.bin
# live.bin: "TOI1" then T/A frames as they arrive, then one E frame

# voice question: JPEG followed by the recorded WAV in one body
cat test.jpg question.wav > ask.bin
curl -s --no-buffer -X POST "$BASE/live" \
  -H "X-Device-Token: $TOKEN" -H "X-Live: ask" \
  -H "X-Jpeg-Length: $(stat -f%z test.jpg)" \
  --data-binary @ask.bin -o live-ask.bin
```

## On-device voice (sanoTTS) and `/kana`

With the device's Voice setting on **sanoTTS**, speech is synthesized on the
ESP32-S3 itself (`firmware/stopwatch/lib/sanotts`, Japanese only) and no TTS
key is used. The device still needs the text spelled out as a *kana
intermediate representation* — hiragana plus pitch-accent marks, e.g.
`きょ][おわよ][いて][んきです°ね` for 今日は良い天気ですね。 — because the
kanji dictionary does not fit in flash. `POST /kana` asks the chat model to do
that (`KANA_MODEL` overrides the model, `KANA_REASONING_EFFORT` defaults to
`none` for ~2 s latency; `low` gives better accents at ~10 s). The Worker
sanitizes the reply down to what the on-device G2P accepts.

When the device is in that voice mode it sends `X-Kana: 1` on `/analyze` and
the kana is bundled into the analyze response (`KANA_BUNDLE`, default `1`),
so no second round trip is needed; `/kana` is then only used for voice
questions and as a fallback. The bundled call runs at
`ANALYZE_KANA_REASONING_EFFORT` (default `none`) — measured on 2026-09-03 it
takes ~4.5 s like a plain `/analyze`, whereas the model's default reasoning
made it ~11 s and separate `/analyze` + `/kana` ~7 s. Set `KANA_BUNDLE=0` to
go back to the two-call flow.

```bash
curl -s -X POST "$BASE/kana" \
  -H "X-Device-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"これは何ですか？"}'
# → {"kana":"こ[れわ[な]んです°か?"}
```

## Attribution

Reverse geocoding by [Nominatim](https://nominatim.org/) — location data
© OpenStreetMap contributors (ODbL). Station lookup by
[HeartRails Express](https://express.heartrails.com/).

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
| `POST /live` | `X-Device-Token` | headers `X-Live: capture\|ask`, `X-Jpeg-Length: N`, `X-Lang`, `X-History-Length` (optional); body = JPEG (N bytes) + WAV (`ask` only) + history JSON (optional) | `application/octet-stream`, chunked — `"TOI1"` then `A`/`T`/`E`/`X` frames, header `X-Voice-Engine: realtime-live`. One GPT-Live-1 session (reasoning delegated to `LIVE_BACKEND_MODEL`) answers with speech while it is still being generated |

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

With the device's fourth Voice option, "GPT Realtime", the firmware uses
`POST /live` (one Realtime session, streamed — see below). `/tts` also accepts
`{"engine":"realtime"}` to have any text read by the Realtime voice; that path
is kept for other clients. For it the Worker opens an outbound WebSocket to the OpenAI
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

## Live (GPT-Live-1 + Responses delegation, streaming)

`POST /live` replaces `/analyze` + `/tts` (and `/ask` + `/tts`) for the device's
"GPT Realtime" voice with a **single** upstream session: the photo — and, for a
voice question, the recorded audio — go up once, and the spoken answer is
streamed back frame by frame as it is generated, so the device can start playing
after the first chunk instead of waiting for a finished WAV.

The upstream is **GPT-Live-1** (`LIVE_API_BASE_URL` + `/live/sessions`, model
`LIVE_MODEL`, default `gpt-live-1`), reusing `TOICAMERA_TTS_API_KEY` as the
bearer token. GPT-Live-1 is a voice layer, not a reasoning model: the session is
opened with a **Responses delegation** to `LIVE_BACKEND_MODEL` (default
`gpt-5.6-terra`; `gpt-5.6-luna` is cheaper, `LIVE_BACKEND_REASONING` sets its
`reasoning.effort`), and the JPEG is queued *for that backend* as a
`response.item.create` image item — so the model that looks at the photo and
answers a factual question is the reasoning one, while `gpt-live-1` only speaks
(voice `LIVE_VOICE`, default `marin`). The live-side instructions tell it to
delegate and wait rather than guess; a short "let me look" while waiting is
allowed.

**Request**

| Header | Value |
|---|---|
| `X-Live` | `capture` (explain the photo) or `ask` (answer the spoken question about it) |
| `X-Jpeg-Length` | byte length `N` of the JPEG that starts the body (1 … 2 MB) |
| `X-Lang` | `ja` (default) / `en` / `zh` — instructions and speech are pinned to it |
| `X-History-Length` | optional byte length of a JSON history section appended **after** the JPEG (+ WAV), see below |

Body = `N` bytes of JPEG (must start `FF D8`), then, for `ask`, a RIFF/WAVE file
(PCM 16-bit mono, any sample rate, 4000 B … 2 MB). The Worker linearly resamples
it to the 24 kHz mono PCM both upstreams accept (the device records 16 kHz).

**History (optional).** With `X-History-Length: B`, the **last `B` bytes** of the
body are UTF-8 JSON `[{"q":"…","a":"…"}, …]` — the most recent question/answer
pairs — and are stripped before the JPEG/WAV are parsed. At most the last 10
pairs are used, each string cut to 500 characters, 32 KB total; anything that is
not such an array is a 400. They are sent as prior `user`/`assistant` messages in
the GPT-Live `session.start` `input` (and prepended to the Realtime driver's
one-shot input), so a follow-up question can refer back to the last answer. The
firmware does not send this section yet.

**Response** — `application/octet-stream`, chunked, `X-Voice-Engine:
realtime-live`, `Cache-Control: no-store`. The body is the 4-byte magic `TOI1`
followed by frames of `type (1 B) + length (uint32 LE) + payload`:

| Type | Payload |
|---|---|
| `A` | PCM16 mono 24 kHz audio bytes — one Realtime `output_audio` delta, verbatim |
| `T` | transcript delta (UTF-8), interleaved with the audio |
| `E` | terminal JSON `{caption, detail, transcript, question, status, pcmBytes, ms}` — `caption` is the first sentence (≤15 chars ja/zh, ≤15 words en), `detail` the rest (empty for one-sentence answers); `question` is the transcribed spoken question (`ask`, best effort, may be empty); `status` is `"completed"`, or `"truncated"` when the Worker stopped forwarding audio (1.9 MB cap, 15 s idle gap or disconnect after audio had started) — the device treats both as a normal end |
| `X` | error JSON `{error}` — only ever sent **before any audio frame**; the device falls back to `/analyze` + `/tts` (or `/ask`), then to chirps |

Exactly one `E` or `X` frame ends the stream. Everything after the upgrade is
reported in-band: an upstream `error`, a disconnect before the answer is over, a
non-`completed` status, a 15 s idle gap or the 90 s hard limit produce `X` if
no audio was sent yet, and `E` with `status:"truncated"` otherwise. Failures
before the WebSocket is up stay plain JSON: 503 when `TOICAMERA_TTS_API_KEY`
is missing, 502 when the upgrade fails, 400/413 for a bad header, body layout,
JPEG or WAV.

**End of the answer.** GPT-Live emits no authoritative turn-completed event, so
the Worker ends the turn when no output delta has arrived for
`LIVE_END_SILENCE_MS` (default 1500) *and* no delegated Responses call is still
running (tracked from the `response.event` lifecycle), then sends `session.close`
and waits up to 2 s for `session.closed` to log its usage before emitting `E`.

**Engine and fallback.** `LIVE_ENGINE` picks the upstream: `gpt-live` (default)
or `realtime` — the latter restores the older one-shot `gpt-realtime` behaviour
using `REALTIME_MODEL` / `REALTIME_VOICE` / `REALTIME_API_BASE_URL`. With
`gpt-live`, a failure **before any audio reached the device** (connect refused,
no `session.started` within 10 s, an `error` event, no audio within 20 s) is
logged as `[toi] live: gpt-live failed before audio (…) — falling back to
realtime` and the Realtime driver takes over **inside the same request**: the
device sees one continuous `TOI1` stream and never hears silence. After audio
has started there is no fallback — the stream ends with `E status:"truncated"`.
Each request logs one summary line: `[toi] live: <engine> <mode> <lang> <status>
<pcmBytes> B pcm, <ms> ms, first audio at <ms>, backend=<model>, usage=<json>`.

| Var | Default | Meaning |
|---|---|---|
| `LIVE_ENGINE` | `gpt-live` | `gpt-live` or `realtime` |
| `LIVE_MODEL` | `gpt-live-1` | GPT-Live voice model |
| `LIVE_BACKEND_MODEL` | `gpt-5.6-terra` | delegated Responses model (must be vision-capable); `gpt-5.6-luna` is cheaper |
| `LIVE_BACKEND_REASONING` | `` | `reasoning.effort` for the backend (`none`/`low`/`medium`/`high`); empty = model default |
| `LIVE_VOICE` | `marin` | GPT-Live output voice |
| `LIVE_API_BASE_URL` | `https://api.openai.com/v1` | base for `/live/sessions` |
| `LIVE_END_SILENCE_MS` | `1500` | output gap that ends the answer |

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

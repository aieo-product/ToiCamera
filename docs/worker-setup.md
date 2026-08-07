# Worker setup — bring your own AI relay

ToiCamera never talks to OpenAI directly: the watch calls a small **Cloudflare
Worker** that holds every API key and answers with strict JSON. This repo ships
the Worker's full source in [`worker/`](https://github.com/aieo-product/ToiCamera/tree/main/worker) — you deploy it under your
own Cloudflare account, point the watch at it, and the whole system is yours.
No shared backend, no third-party server.

```
Watch ──(HTTPS + X-Device-Token)──▶ your Worker ──▶ OpenAI APIs
```

Time budget: ~10 minutes.

## 0. Prerequisites

- A free [Cloudflare account](https://dash.cloudflare.com/sign-up) (Workers free tier is enough)
- An **OpenAI API key** — create one at <https://platform.openai.com/api-keys>
- Node.js 18+ (`npx` is used to run wrangler; no global install needed)

## 1. Deploy the Worker

```bash
cd worker
npm install
npx wrangler deploy        # first run opens a browser to log in to Cloudflare
```

The deploy output prints your Worker URL, e.g.

```
https://toicamera.<your-subdomain>.workers.dev
```

Keep it — the firmware needs it in step 3.

## 2. Set the secrets

The Worker reads four secrets. Set each with `npx wrangler secret put <NAME>`
(it prompts on stdin, so keys never land in your shell history):

| Secret | What it is |
|---|---|
| `OPENAI_FREE_API_KEY` | OpenAI key used for vision / Q&A / digest. Any OpenAI key works — the name comes from the author's use of the free daily-token program |
| `OPENAI_API_KEY` | OpenAI key used for TTS. Usually the **same key** as above |
| `DEVICE_TOKEN` | A shared secret **you make up** (e.g. `openssl rand -hex 16`). The watch sends it as `X-Device-Token`; the Worker rejects requests without it |
| `ANTHROPIC_API_KEY` | Optional — only if you flip `ANALYZE_PROVIDER` to `anthropic` in `wrangler.jsonc` |

```bash
npx wrangler secret put OPENAI_FREE_API_KEY
npx wrangler secret put OPENAI_API_KEY
npx wrangler secret put DEVICE_TOKEN
```

Model, provider and TTS voice defaults live in the `vars` block of
[`worker/wrangler.jsonc`](https://github.com/aieo-product/ToiCamera/blob/main/worker/wrangler.jsonc) — edit and redeploy to change them.

### Customize the model menu

The watch never hardcodes model names: it fetches `GET /config` from your
Worker and shows whatever the `MODELS` var lists (comma-separated) in its
Settings screen. Add or swap models, redeploy, and the watch picks them up on
its next boot. The `TTS_VOICE` var likewise decides which voice the TTS speech
mode uses — the device only chooses *chirps or TTS*, the voice itself is yours
to define here.

### Local LLM (Ollama, LM Studio, …)

Everything the Worker calls goes through the OpenAI-compatible
`OPENAI_BASE_URL` var, so you can serve ToiCamera from a model running on your
own machine:

1. Run a local server with an OpenAI-compatible API, e.g.
   `ollama serve` (endpoint `http://localhost:11434/v1`).
2. Expose it with a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):
   `cloudflared tunnel --url http://localhost:11434` → gives you a public
   `https://…trycloudflare.com` host (or a named tunnel on your own domain).
3. Set the vars and redeploy:
   ```jsonc
   "OPENAI_BASE_URL": "https://<tunnel-host>/v1",
   "MODELS": "gemma3:12b",          // whatever `ollama list` shows
   "ANALYZE_MODEL": "gemma3:12b"    // default when the device sends none
   ```

Caveats: the model must accept OpenAI-style `chat/completions` with an image
part (pick a vision-capable model for /analyze). Voice STT/TTS intentionally
use a separate base (`OPENAI_AUDIO_BASE_URL`, default api.openai.com), so
speech keeps working while chat runs on your chat-only local server.
Structured-output support (`response_format: json_schema`) varies by server;
Ollama ≥0.5 handles it.

## 3. Point the watch at your Worker

Two values connect the firmware to your Worker: the **URL** from step 1 and the
**device token** from step 2.

- **At build time** — put both in `firmware/stopwatch/secrets.ini`
  (copy from `secrets.ini.example`; `gen-secrets.sh` automates it):

  ```ini
  -DWORKER_URL=\"https://toicamera.<your-subdomain>.workers.dev\"
  -DDEVICE_TOKEN=\"<the token you made up>\"
  ```

- **Or at runtime** — the token (not the URL) can also be entered later from the
  watch itself: Settings → WiFi → scan the QR → `http://192.168.4.1` → the
  *device token* field. It is stored in NVS and overrides the build-time value.
  This field expects the `DEVICE_TOKEN` shared secret — **not** an OpenAI key.

## 4. Verify

```bash
curl -s -X POST "https://toicamera.<your-subdomain>.workers.dev/analyze" \
  -H "x-device-token: <your token>" -H "Content-Type: image/jpeg" \
  --data-binary @some-photo.jpg
```

You should get `{"caption":"...","detail":"..."}`. Common answers:

| Response | Meaning |
|---|---|
| `401` | Token mismatch — the header value must equal the `DEVICE_TOKEN` secret |
| `429` + `reset_jst` | Your OpenAI free daily quota is exhausted; the watch shows the reset time |
| `400 empty or truncated image` | The test file is smaller than 128 bytes |

Live logs while testing from the watch: `npx wrangler tail`.

## Security notes

- API keys exist **only** as Worker secrets — never in the firmware, NVS or repo.
- The device↔Worker link is HTTPS, but the firmware uses `setInsecure()` (no CA
  pinning). Fine for a hobby build that only ever sends a photo and a token;
  pin the root CA if you fork this for anything serious.
- Change `TOI_AP_PASS` (watch AP password) before deploying your own — anyone
  who joins the watch AP can reach the setup portal.

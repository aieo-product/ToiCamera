import Anthropic from "@anthropic-ai/sdk";

export interface Env {
  ANTHROPIC_API_KEY: string;
  OPENAI_API_KEY: string;
  /** Free daily-token key (data-sharing program) — used for /analyze while
   *  the Anthropic account has no credit. */
  OPENAI_FREE_API_KEY: string;
  DEVICE_TOKEN: string;
  /** "openai" | "anthropic" — which vision backend /analyze uses */
  ANALYZE_PROVIDER: string;
  /** OpenAI vision model (free-token eligible) */
  ANALYZE_MODEL: string;
  /** Anthropic vision model (used when ANALYZE_PROVIDER=anthropic) */
  MODEL: string;
  TTS_VOICE: string;
}

// 撮影ガジェットのナレーター。detail は TTS で ≤40 秒に収まる長さに制限する。
const SYSTEM_PROMPT = `あなたはカメラ付き小型ガジェット「ToiCamera」のナレーターです。
撮影された写真に写っているものを、親しみやすく少しユーモラスな日本語で解説します。
- caption: 写真の主題を表す短い見出し(15文字以内)
- detail: 2〜3文の解説(150文字以内)。写っているものの説明に、豆知識やちょっとした一言を添える
専門用語は避け、聞いて楽しい語り口にしてください。`;

const RESULT_SCHEMA = {
  type: "object",
  properties: {
    caption: { type: "string", description: "写真の見出し(15文字以内)" },
    detail: { type: "string", description: "2〜3文・150文字以内の日本語解説" },
  },
  required: ["caption", "detail"],
  additionalProperties: false,
} as const;

const MAX_IMAGE_BYTES = 4 * 1024 * 1024; // CamS3 は SVGA〜UXGA JPEG を送る想定 (~100-500KB)

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const CHUNK = 0x8000; // String.fromCharCode の引数上限を避けてチャンク変換
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

const FALLBACK_RESULT = {
  caption: "解説できません",
  detail: "この写真はうまく解説できませんでした。別のものを撮ってみてください。",
};

async function analyzeWithOpenAI(env: Env, imageB64: string, userText: string): Promise<Response> {
  const upstream = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.OPENAI_FREE_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: env.ANALYZE_MODEL,
      max_completion_tokens: 500,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        {
          role: "user",
          content: [
            {
              type: "image_url",
              image_url: { url: `data:image/jpeg;base64,${imageB64}`, detail: "low" },
            },
            { type: "text", text: userText },
          ],
        },
      ],
      response_format: {
        type: "json_schema",
        json_schema: { name: "toi_result", strict: true, schema: RESULT_SCHEMA },
      },
    }),
  });

  if (!upstream.ok) {
    const detail = await upstream.text();
    console.error("OpenAI analyze error", upstream.status, detail);
    return json({ error: "analyze upstream failed", status: upstream.status }, 502);
  }
  const data = (await upstream.json()) as {
    choices?: { message?: { content?: string; refusal?: string } }[];
  };
  const msg = data.choices?.[0]?.message;
  if (!msg?.content || msg.refusal) {
    return json(FALLBACK_RESULT);
  }
  // strict json_schema により content は RESULT_SCHEMA に適合した JSON
  return new Response(msg.content, {
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

// Best-effort reverse geocoding (OSM Nominatim). Coordinates are rounded to
// ~100m and results cached in Cloudflare's edge cache (Nominatim usage policy
// requires caching; it also keeps the hint off the latency-critical path).
async function placeHint(lat: string, lon: string): Promise<string> {
  try {
    const rlat = Number(lat).toFixed(3);
    const rlon = Number(lon).toFixed(3);
    const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${rlat}&lon=${rlon}&zoom=16&accept-language=ja`;
    const cache = caches.default;
    const cacheKey = new Request(url);
    const cached = await cache.match(cacheKey);
    if (cached) return await cached.text();
    const res = await fetch(url, {
      headers: { "user-agent": "ToiCamera/1.0 (contest gadget; take.otani@syn-gr.com)" },
      signal: AbortSignal.timeout(800),
    });
    if (!res.ok) return "";
    const data = (await res.json()) as {
      name?: string;
      address?: Record<string, string>;
    };
    const a = data.address ?? {};
    const parts = [
      a.state,
      a.city ?? a.town ?? a.village,
      a.suburb ?? a.neighbourhood,
      data.name,
    ].filter(Boolean);
    const place = parts.join(" ");
    await cache.put(
      cacheKey,
      new Response(place, { headers: { "cache-control": "max-age=604800" } }),
    );
    return place;
  } catch (err) {
    console.warn("reverse geocode failed", err);
    return "";
  }
}

async function handleAnalyze(request: Request, env: Env): Promise<Response> {
  const image = await request.arrayBuffer();
  if (image.byteLength < 128) {
    return json({ error: "empty or truncated image body" }, 400);
  }
  if (image.byteLength > MAX_IMAGE_BYTES) {
    return json({ error: "image too large" }, 413);
  }

  const { searchParams } = new URL(request.url);
  const lat = searchParams.get("lat");
  const lon = searchParams.get("lon");
  let userText = "この写真を解説してください。";
  if (lat && lon) {
    const place = await placeHint(lat, lon);
    if (place) {
      userText = `撮影場所: ${place} 付近。この写真を解説してください。場所の文脈が内容と合うときは自然に織り込んでください。`;
    }
  }

  if (env.ANALYZE_PROVIDER !== "anthropic") {
    return analyzeWithOpenAI(env, toBase64(image), userText);
  }

  const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
  const response = await client.messages.create({
    model: env.MODEL,
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    output_config: {
      format: { type: "json_schema", schema: RESULT_SCHEMA },
    },
    messages: [
      {
        role: "user",
        content: [
          {
            type: "image",
            source: {
              type: "base64",
              media_type: "image/jpeg",
              data: toBase64(image),
            },
          },
          { type: "text", text: "この写真を解説してください。" },
        ],
      },
    ],
  });

  if (response.stop_reason === "refusal") {
    return json(FALLBACK_RESULT);
  }

  const text = response.content.find((b) => b.type === "text")?.text;
  if (!text) {
    return json({ error: "no text in model response" }, 502);
  }
  // output_config.format により text は RESULT_SCHEMA に適合した JSON
  return new Response(text, {
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

const ANSWER_SCHEMA = {
  type: "object",
  properties: {
    answer: { type: "string", description: "2文以内・120文字以内の日本語回答" },
  },
  required: ["answer"],
  additionalProperties: false,
} as const;

// Voice question about the last shot: WAV body -> STT -> answer using the
// prior explanation (caption/detail passed as query params) as context.
async function handleAsk(request: Request, env: Env): Promise<Response> {
  const audio = await request.arrayBuffer();
  if (audio.byteLength < 4000) return json({ error: "audio too short" }, 400);
  if (audio.byteLength > 2 * 1024 * 1024) return json({ error: "audio too large" }, 413);

  const { searchParams } = new URL(request.url);
  const caption = searchParams.get("caption") ?? "";
  const detail = searchParams.get("detail") ?? "";

  // STT — try the free-token key first, fall back to the paid key + whisper-1
  async function transcribe(key: string, model: string): Promise<string | null> {
    const form = new FormData();
    form.append("file", new File([audio], "q.wav", { type: "audio/wav" }));
    form.append("model", model);
    form.append("language", "ja");
    const res = await fetch("https://api.openai.com/v1/audio/transcriptions", {
      method: "POST",
      headers: { authorization: `Bearer ${key}` },
      body: form,
    });
    if (!res.ok) {
      console.warn("stt failed", model, res.status, await res.text());
      return null;
    }
    const data = (await res.json()) as { text?: string };
    return data.text?.trim() || null;
  }

  const question =
    (await transcribe(env.OPENAI_FREE_API_KEY, "gpt-4o-mini-transcribe")) ??
    (await transcribe(env.OPENAI_API_KEY, "whisper-1"));
  if (!question) return json({ error: "stt failed" }, 502);

  const upstream = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.OPENAI_FREE_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: env.ANALYZE_MODEL,
      max_completion_tokens: 300,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        {
          role: "user",
          content: `さっき撮った写真をあなたはこう解説しました:「${caption}。${detail}」
ユーザーからの質問: ${question}
写真の内容を踏まえて、2文以内の日本語で親しみやすく答えてください。`,
        },
      ],
      response_format: {
        type: "json_schema",
        json_schema: { name: "toi_answer", strict: true, schema: ANSWER_SCHEMA },
      },
    }),
  });
  if (!upstream.ok) {
    console.error("ask upstream error", upstream.status, await upstream.text());
    return json({ error: "ask upstream failed" }, 502);
  }
  const data = (await upstream.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  const content = data.choices?.[0]?.message?.content;
  if (!content) return json(FALLBACK_RESULT);
  const parsed = JSON.parse(content) as { answer: string };
  return json({ question, answer: parsed.answer });
}

async function handleTts(request: Request, env: Env): Promise<Response> {
  const body = (await request.json().catch(() => null)) as { text?: string } | null;
  const text = body?.text?.trim();
  if (!text) {
    return json({ error: "missing text" }, 400);
  }

  const upstream = await fetch("https://api.openai.com/v1/audio/speech", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.OPENAI_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: "gpt-4o-mini-tts",
      voice: env.TTS_VOICE,
      input: text.slice(0, 500),
      response_format: "wav", // ESP32 側は M5Unified Speaker (WAV/RAW のみ) で再生
    }),
  });

  if (!upstream.ok) {
    const detail = await upstream.text();
    console.error("TTS upstream error", upstream.status, detail);
    return json({ error: "tts upstream failed", status: upstream.status }, 502);
  }

  return new Response(upstream.body, {
    headers: { "content-type": "audio/wav" },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, model: env.MODEL });
    }

    if (request.headers.get("x-device-token") !== env.DEVICE_TOKEN) {
      return json({ error: "unauthorized" }, 401);
    }
    if (request.method !== "POST") {
      return json({ error: "method not allowed" }, 405);
    }

    try {
      switch (url.pathname) {
        case "/analyze":
          return await handleAnalyze(request, env);
        case "/ask":
          return await handleAsk(request, env);
        case "/tts":
          return await handleTts(request, env);
        default:
          return json({ error: "not found" }, 404);
      }
    } catch (err) {
      console.error("unhandled error", err);
      return json({ error: "internal error" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;

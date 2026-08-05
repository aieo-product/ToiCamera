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

const DIGEST_SYSTEM_PROMPT =
  "あなたは行動ログの要約係。撮影・質問の見出しリストから、その人が今日なにをしているかを日本語 30 字以内の 1 文で要約する。体言止めか『〜中』で軽快に";

const DIGEST_SCHEMA = {
  type: "object",
  properties: {
    summary: { type: "string" },
  },
  required: ["summary"],
  additionalProperties: false,
} as const;

const MAX_IMAGE_BYTES = 4 * 1024 * 1024; // CamS3 は SVGA〜UXGA JPEG を送る想定 (~100-500KB)
const ALLOWED_MODELS = new Set([
  "gpt-5.6-terra",
  "gpt-5.6-luna",
]);

function pickModel(request: Request, env: Env): string {
  const requestedModel = request.headers.get("x-model");
  return requestedModel && ALLOWED_MODELS.has(requestedModel)
    ? requestedModel
    : env.ANALYZE_MODEL;
}

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

// Chat completion against OpenAI, free data-sharing key only (no paid
// fallback by owner's decision — the device surfaces quota exhaustion).
async function openaiChat(env: Env, payload: unknown): Promise<Response> {
  return fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.OPENAI_FREE_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

// The free training-token quota resets daily at midnight Pacific Time.
// Returns that instant as HH:MM in JST for the device to display.
function nextFreeResetJst(): string {
  try {
    const now = new Date();
    const la = new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Los_Angeles",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(now); // YYYY-MM-DD
    const offsetName = new Intl.DateTimeFormat("en", {
      timeZone: "America/Los_Angeles",
      timeZoneName: "shortOffset",
    })
      .formatToParts(now)
      .find((p) => p.type === "timeZoneName")?.value; // e.g. "GMT-7"
    const offset = Number(offsetName?.replace("GMT", "") || -7);
    const [y, m, d] = la.split("-").map(Number);
    const nextMidnightUtc = Date.UTC(y, m - 1, d + 1, -offset, 0, 0);
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(nextMidnightUtc));
  } catch {
    return "16:00"; // PDT fallback
  }
}

function quotaResponse(): Response {
  return json({ error: "quota", reset_jst: nextFreeResetJst() }, 429);
}

function pickDetail(request: Request): "low" | "high" {
  return request.headers.get("x-detail") === "high" ? "high" : "low";
}

async function analyzeWithOpenAI(
  env: Env,
  imageB64: string,
  userText: string,
  model: string,
  detailLevel: "low" | "high",
): Promise<Response> {
  const upstream = await openaiChat(env, {
    model,
    max_completion_tokens: 500,
    messages: [
      { role: "system", content: SYSTEM_PROMPT },
      {
        role: "user",
        content: [
          {
            type: "image_url",
            image_url: {
              url: `data:image/jpeg;base64,${imageB64}`,
              detail: detailLevel,
            },
          },
          { type: "text", text: userText },
        ],
      },
    ],
    response_format: {
      type: "json_schema",
      json_schema: { name: "toi_result", strict: true, schema: RESULT_SCHEMA },
    },
  });

  if (!upstream.ok) {
    const detail = await upstream.text();
    console.error("OpenAI analyze error", upstream.status, detail);
    if (upstream.status === 429) return quotaResponse();
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
interface PlaceHint {
  place: string;
  postcode: string;
  /** Compact dashboard label, e.g. "〒154-0017 世田谷区" — no AI involved. */
  short: string;
}

const NO_PLACE: PlaceHint = { place: "", postcode: "", short: "" };

async function placeHint(
  lat: string,
  lon: string,
  ctx: ExecutionContext,
): Promise<PlaceHint> {
  try {
    const rlat = Number(lat).toFixed(3);
    const rlon = Number(lon).toFixed(3);
    const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${rlat}&lon=${rlon}&zoom=16&accept-language=ja`;
    const cache = caches.default;
    // &fmt=v3 keys the cache format (v3: short = prefecture+locality)
    const cacheKey = new Request(url + "&fmt=v3");
    const cached = await cache.match(cacheKey);
    if (cached) {
      const data = (await cached.json().catch(() => null)) as PlaceHint | null;
      if (data && typeof data.place === "string") return data;
    }
    const res = await fetch(url, {
      headers: { "user-agent": "ToiCamera/1.0 (contest gadget; take.otani@syn-gr.com)" },
      signal: AbortSignal.timeout(800),
    });
    if (!res.ok) return NO_PLACE;
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
    const postcode = a.postcode ?? "";
    // Compact label like 東京都千代田区 (owner preference: no postcode).
    const prefecture = a.state ?? a.province ?? a.region ?? "";
    const locality = a.city ?? a.town ?? a.village ?? a.county ?? "";
    const hint: PlaceHint = {
      place: parts.join(" "),
      postcode,
      short: prefecture + locality || parts[0] || "",
    };
    ctx.waitUntil(
      cache.put(
        cacheKey,
        new Response(JSON.stringify(hint), {
          headers: {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "max-age=604800",
          },
        }),
      ),
    );
    return hint;
  } catch (err) {
    console.warn("reverse geocode failed", err);
    return NO_PLACE;
  }
}

interface StationHint {
  station: string;
  distance_m: number;
}

const NO_STATION: StationHint = { station: "", distance_m: 0 };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function distanceMeters(value: unknown): number {
  if (typeof value !== "string") return 0;
  const match = value.trim().match(/^([0-9]+(?:\.[0-9]+)?)\s*(m|km)$/i);
  if (!match) return 0;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return 0;
  return Math.round(match[2].toLowerCase() === "km" ? amount * 1000 : amount);
}

function parseHeartRailsStation(data: unknown): StationHint {
  if (!isRecord(data) || !isRecord(data.response)) return NO_STATION;
  const stations = data.response.station;
  if (!Array.isArray(stations) || !isRecord(stations[0])) return NO_STATION;
  const name = stations[0].name;
  if (typeof name !== "string" || !name) return NO_STATION;
  return {
    station: name,
    distance_m: distanceMeters(stations[0].distance),
  };
}

function parseCachedStation(data: unknown): StationHint | null {
  if (
    !isRecord(data) ||
    typeof data.station !== "string" ||
    typeof data.distance_m !== "number"
  ) {
    return null;
  }
  return {
    station: data.station,
    distance_m: Number.isFinite(data.distance_m) ? Math.max(0, data.distance_m) : 0,
  };
}

async function nearestStation(
  lat: string,
  lon: string,
  ctx: ExecutionContext,
): Promise<StationHint> {
  try {
    const rlat = Number(lat).toFixed(3);
    const rlon = Number(lon).toFixed(3);
    const url =
      `http://express.heartrails.com/api/json?method=getStations&x=${rlon}&y=${rlat}`;
    const cache = caches.default;
    const cacheKey = new Request(url);
    const cached = await cache.match(cacheKey);
    if (cached) {
      const station = parseCachedStation(await cached.json());
      if (station) return station;
    }

    const res = await fetch(url, { signal: AbortSignal.timeout(1500) });
    if (!res.ok) return NO_STATION;
    const station = parseHeartRailsStation(await res.json());
    ctx.waitUntil(
      cache.put(
        cacheKey,
        new Response(JSON.stringify(station), {
          headers: {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "max-age=604800",
          },
        }),
      ),
    );
    return station;
  } catch (err) {
    console.warn("nearest station failed", err);
    return NO_STATION;
  }
}

async function handlePlace(request: Request, ctx: ExecutionContext): Promise<Response> {
  const { searchParams } = new URL(request.url);
  const lat = searchParams.get("lat");
  const lon = searchParams.get("lon");
  // Number("") / Number("  ") coerce to 0 — reject blanks before coercion.
  const latitude = lat === null || lat.trim() === "" ? Number.NaN : Number(lat);
  const longitude = lon === null || lon.trim() === "" ? Number.NaN : Number(lon);
  if (
    lat === null ||
    lon === null ||
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    latitude < -90 ||
    latitude > 90 ||
    longitude < -180 ||
    longitude > 180
  ) {
    return json({ error: "invalid coordinates" }, 400);
  }

  const [hint, station] = await Promise.all([
    placeHint(lat, lon, ctx),
    nearestStation(lat, lon, ctx),
  ]);
  return json({
    place: hint.place,
    postcode: hint.postcode,
    short: hint.short,
    station: station.station,
    distance_m: station.distance_m,
    walk_min: station.distance_m > 0 ? Math.ceil(station.distance_m / 80) : 0,
  });
}

async function handleAnalyze(
  request: Request,
  env: Env,
  ctx: ExecutionContext,
): Promise<Response> {
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
    const hint = await placeHint(lat, lon, ctx);
    if (hint.place) {
      userText = `撮影場所: ${hint.place} 付近。この写真を解説してください。場所の文脈が内容と合うときは自然に織り込んでください。`;
    }
  }

  if (env.ANALYZE_PROVIDER !== "anthropic") {
    return analyzeWithOpenAI(
      env,
      toBase64(image),
      userText,
      pickModel(request, env),
      pickDetail(request),
    );
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

  // STT — free-token key only (paid fallback removed by owner's decision)
  async function transcribe(model: string): Promise<{ text: string | null; status: number }> {
    const form = new FormData();
    form.append("file", new File([audio], "q.wav", { type: "audio/wav" }));
    form.append("model", model);
    form.append("language", "ja");
    const res = await fetch("https://api.openai.com/v1/audio/transcriptions", {
      method: "POST",
      headers: { authorization: `Bearer ${env.OPENAI_FREE_API_KEY}` },
      body: form,
    });
    if (!res.ok) {
      console.warn("stt failed", model, res.status, await res.text());
      return { text: null, status: res.status };
    }
    const data = (await res.json()) as { text?: string };
    return { text: data.text?.trim() || null, status: 200 };
  }

  const stt = await transcribe("gpt-4o-mini-transcribe");
  if (!stt.text) {
    if (stt.status === 429) return quotaResponse();
    return json({ error: "stt failed" }, 502);
  }
  const question = stt.text;
  const model = pickModel(request, env);

  const upstream = await openaiChat(env, {
    model,
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
  });
  if (!upstream.ok) {
    console.error("ask upstream error", upstream.status, await upstream.text());
    if (upstream.status === 429) return quotaResponse();
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

async function handleDigest(request: Request, env: Env): Promise<Response> {
  const body = (await request.json().catch(() => null)) as unknown;
  if (
    !isRecord(body) ||
    !Array.isArray(body.items) ||
    body.items.length === 0 ||
    !body.items.every((item) => typeof item === "string")
  ) {
    return json({ error: "items must be a non-empty string array" }, 400);
  }

  const items = body.items
    .slice(0, 50)
    .map((item) => Array.from(item.trim()).slice(0, 100).join(""))
    .filter(Boolean);
  if (items.length === 0) {
    return json({ error: "items must not be empty" }, 400);
  }
  const model = pickModel(request, env);

  try {
    const upstream = await openaiChat(env, {
      model,
      max_completion_tokens: 100,
      messages: [
        { role: "system", content: DIGEST_SYSTEM_PROMPT },
        {
          role: "user",
          content: items.map((item, index) => `${index + 1}. ${item}`).join("\n"),
        },
      ],
      response_format: {
        type: "json_schema",
        json_schema: { name: "toi_digest", strict: true, schema: DIGEST_SCHEMA },
      },
    });
    if (!upstream.ok) {
      console.error("[toi] digest upstream error", upstream.status, await upstream.text());
      return json({ summary: "" });
    }

    const data = (await upstream.json()) as {
      choices?: { message?: { content?: string; refusal?: string } }[];
    };
    const message = data.choices?.[0]?.message;
    if (!message?.content || message.refusal) {
      return json({ summary: "" });
    }
    const parsed = JSON.parse(message.content) as { summary?: unknown };
    if (typeof parsed.summary !== "string") {
      return json({ summary: "" });
    }
    return json({ summary: Array.from(parsed.summary).slice(0, 30).join("") });
  } catch (err) {
    console.error("[toi] digest failed", err);
    return json({ summary: "" });
  }
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
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, model: env.MODEL });
    }

    if (request.headers.get("x-device-token") !== env.DEVICE_TOKEN) {
      return json({ error: "unauthorized" }, 401);
    }
    const expectedMethod = url.pathname === "/place" ? "GET" : "POST";
    if (request.method !== expectedMethod) {
      return json({ error: "method not allowed" }, 405);
    }

    try {
      switch (url.pathname) {
        case "/analyze":
          return await handleAnalyze(request, env, ctx);
        case "/ask":
          return await handleAsk(request, env);
        case "/place":
          return await handlePlace(request, ctx);
        case "/digest":
          return await handleDigest(request, env);
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

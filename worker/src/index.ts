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
  DB: D1Database;
}

// 撮影ガジェットのナレーター。detail は TTS で ≤40 秒に収まる長さに制限する。
const SYSTEM_PROMPT = `あなたはカメラ付き小型ガジェット「ToiCamera」のナレーターです。
撮影された写真に写っているものを、親しみやすく少しユーモラスな日本語で解説します。
- caption: 写真の主題を表す短い見出し(15文字以内)
- detail: 2〜3文の解説(150文字以内)。写っているものの説明に、豆知識やちょっとした一言を添える
専門用語は避け、聞いて楽しい語り口にしてください。

あわせて、写真が食べ物(料理・飲み物・食材)かどうかを判定してください。
- 食べ物の場合: is_food=true、food_name に日本語の料理名、kcal_est に一人前のおおよその推定カロリー(kcal, 整数)、
  food_category に vegetable / meat / seafood / sweet / grain のうち主となるものを **1つだけ** 選ぶ
  (どれにも当てはまらない食べ物は other)
- 食べ物でない場合: is_food=false、food_name=""、kcal_est=0、food_category="other"`;

const FOOD_CATEGORIES = [
  "vegetable",
  "meat",
  "seafood",
  "sweet",
  "grain",
  "other",
] as const;

type FoodCategory = (typeof FOOD_CATEGORIES)[number];

// OpenAI strict json_schema の制約に合わせ、全プロパティを required に並べ
// additionalProperties:false を維持する(任意項目は作れない)。
const RESULT_SCHEMA = {
  type: "object",
  properties: {
    caption: { type: "string", description: "写真の見出し(15文字以内)" },
    detail: { type: "string", description: "2〜3文・150文字以内の日本語解説" },
    is_food: { type: "boolean", description: "写真が食べ物なら true" },
    food_name: { type: "string", description: "日本語の料理名。食べ物でなければ空文字" },
    kcal_est: { type: "integer", description: "一人前の推定カロリー。食べ物でなければ 0" },
    food_category: {
      type: "string",
      enum: FOOD_CATEGORIES,
      description: "主となる食品カテゴリ。食べ物でなければ other",
    },
  },
  required: ["caption", "detail", "is_food", "food_name", "kcal_est", "food_category"],
  additionalProperties: false,
} as const;

interface AnalyzeResult {
  caption: string;
  detail: string;
  is_food: boolean;
  food_name: string;
  kcal_est: number;
  food_category: FoodCategory;
}

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

const FALLBACK_RESULT: AnalyzeResult = {
  caption: "解説できません",
  detail: "この写真はうまく解説できませんでした。別のものを撮ってみてください。",
  is_food: false,
  food_name: "",
  kcal_est: 0,
  food_category: "other",
};

// スキーマ準拠のはずだが、モデル出力を D1 に入れる前に型を確定させる。
function parseAnalyzeResult(text: string): AnalyzeResult | null {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    console.warn("analyze result parse failed", err);
    return null;
  }
  if (!isRecord(raw)) return null;
  const category = raw.food_category;
  return {
    caption: typeof raw.caption === "string" ? raw.caption : FALLBACK_RESULT.caption,
    detail: typeof raw.detail === "string" ? raw.detail : FALLBACK_RESULT.detail,
    is_food: raw.is_food === true,
    food_name: typeof raw.food_name === "string" ? raw.food_name : "",
    kcal_est:
      typeof raw.kcal_est === "number" && Number.isFinite(raw.kcal_est)
        ? Math.min(10000, Math.max(0, Math.round(raw.kcal_est)))
        : 0,
    food_category: FOOD_CATEGORIES.includes(category as FoodCategory)
      ? (category as FoodCategory)
      : "other",
  };
}

/** 解析成功なら result、上流エラーならそのまま返す Response。 */
type AnalyzeOutcome =
  | { ok: true; result: AnalyzeResult }
  | { ok: false; response: Response };

async function analyzeWithOpenAI(
  env: Env,
  imageB64: string,
  userText: string,
): Promise<AnalyzeOutcome> {
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
    return {
      ok: false,
      response: json({ error: "analyze upstream failed", status: upstream.status }, 502),
    };
  }
  const data = (await upstream.json()) as {
    choices?: {
      finish_reason?: string | null;
      message?: { content?: string; refusal?: string };
    }[];
  };
  const choice = data.choices?.[0];
  const msg = choice?.message;
  if (msg?.refusal) {
    return { ok: true, result: FALLBACK_RESULT };
  }
  if (choice?.finish_reason !== "stop") {
    return {
      ok: false,
      response: json(
        {
          error: "analyze output truncated",
          finish_reason: choice?.finish_reason ?? null,
        },
        502,
      ),
    };
  }
  // strict json_schema により content は RESULT_SCHEMA に適合した JSON
  const result = parseAnalyzeResult(msg?.content ?? "");
  if (!result) {
    return {
      ok: false,
      response: json({ error: "invalid analyze output" }, 502),
    };
  }
  return { ok: true, result };
}

// Best-effort reverse geocoding (OSM Nominatim). Coordinates are rounded to
// ~100m and results cached in Cloudflare's edge cache (Nominatim usage policy
// requires caching; it also keeps the hint off the latency-critical path).
async function placeHint(lat: string, lon: string, ctx: ExecutionContext): Promise<string> {
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
    ctx.waitUntil(
      cache.put(
        cacheKey,
        new Response(place, { headers: { "cache-control": "max-age=604800" } }),
      ),
    );
    return place;
  } catch (err) {
    console.warn("reverse geocode failed", err);
    return "";
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

  const [place, station] = await Promise.all([
    placeHint(lat, lon, ctx),
    nearestStation(lat, lon, ctx),
  ]);
  return json({
    place,
    station: station.station,
    distance_m: station.distance_m,
    walk_min: station.distance_m > 0 ? Math.ceil(station.distance_m / 80) : 0,
  });
}

/** クエリの緯度経度を数値化する(未指定・不正値は null で保存)。 */
function coordOrNull(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

// device_id は Phase A では未対応 (NULL 固定)。端末トークンは保存しない。
function persistMeal(
  env: Env,
  result: AnalyzeResult,
  lat: number | null,
  lon: number | null,
  provider: "openai" | "anthropic",
): Promise<unknown> {
  return env.DB.prepare(
    `INSERT INTO meals
       (device_id, caption, detail, is_food, food_name, kcal_est, food_category, lat, lon, provider)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      null,
      result.caption,
      result.detail,
      result.is_food ? 1 : 0,
      result.food_name,
      result.kcal_est,
      result.food_category,
      lat,
      lon,
      provider,
    )
    .run();
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
    const place = await placeHint(lat, lon, ctx);
    if (place) {
      userText = `撮影場所: ${place} 付近。この写真を解説してください。場所の文脈が内容と合うときは自然に織り込んでください。`;
    }
  }

  const latValue = coordOrNull(lat);
  const lonValue = coordOrNull(lon);

  if (env.ANALYZE_PROVIDER !== "anthropic") {
    const outcome = await analyzeWithOpenAI(env, toBase64(image), userText);
    if (!outcome.ok) return outcome.response;
    ctx.waitUntil(
      persistMeal(env, outcome.result, latValue, lonValue, "openai").catch((e) =>
        console.error("d1 insert failed", e),
      ),
    );
    return json(outcome.result);
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

  if (response.stop_reason === "max_tokens") {
    return json({ error: "analyze output truncated" }, 502);
  }

  let result: AnalyzeResult;
  if (response.stop_reason === "refusal") {
    result = FALLBACK_RESULT;
  } else {
    const text = response.content.find((b) => b.type === "text")?.text;
    if (!text) {
      return json({ error: "no text in model response" }, 502);
    }
    // output_config.format により text は RESULT_SCHEMA に適合した JSON
    const parsed = parseAnalyzeResult(text);
    if (!parsed) {
      return json({ error: "invalid analyze output" }, 502);
    }
    result = parsed;
  }

  ctx.waitUntil(
    persistMeal(env, result, latValue, lonValue, "anthropic").catch((e) =>
      console.error("d1 insert failed", e),
    ),
  );
  return json(result);
}

interface MealRow {
  id: number;
  created_at: string;
  caption: string;
  detail: string;
  is_food: number;
  food_name: string | null;
  kcal_est: number | null;
  food_category: string | null;
}

const HISTORY_DEFAULT_LIMIT = 20;
const HISTORY_MAX_LIMIT = 100;

async function handleHistory(request: Request, env: Env): Promise<Response> {
  const raw = new URL(request.url).searchParams.get("limit");
  // Number("") は 0 になるため、空文字は未指定扱いにしてから数値化する。
  const parsed = raw === null || raw.trim() === "" ? Number.NaN : Number(raw);
  const limit = Number.isFinite(parsed)
    ? Math.min(HISTORY_MAX_LIMIT, Math.max(1, Math.trunc(parsed)))
    : HISTORY_DEFAULT_LIMIT;

  const { results } = await env.DB.prepare(
    `SELECT id, created_at, caption, detail, is_food, food_name, kcal_est, food_category
       FROM meals ORDER BY id DESC LIMIT ?`,
  )
    .bind(limit)
    .all<MealRow>();

  return json({
    limit,
    items: results.map((row) => ({ ...row, is_food: row.is_food !== 0 })),
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

const GET_PATHS = new Set(["/place", "/history"]);

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, model: env.MODEL });
    }

    if (request.headers.get("x-device-token") !== env.DEVICE_TOKEN) {
      return json({ error: "unauthorized" }, 401);
    }
    const expectedMethod = GET_PATHS.has(url.pathname) ? "GET" : "POST";
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
        case "/history":
          return await handleHistory(request, env);
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

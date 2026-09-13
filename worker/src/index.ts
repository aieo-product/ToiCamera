export interface Env {
  TOICAMERA_TTS_API_KEY: string;
  /** API key of the main chat/vision backend (whatever MAIN_API_BASE_URL
   *  points at — OpenAI by default). */
  TOICAMERA_MAIN_API_KEY: string;
  DEVICE_TOKEN: string;
  TTS_VOICE: string;
  /** TTS model at AUDIO_API_BASE_URL (default gpt-4o-mini-tts). */
  TTS_MODEL?: string;
  /** Model for /kana (on-device sanoTTS voice). Defaults to the X-Model /
   *  MODELS pick; set to a small fast model to cut the wait. */
  KANA_MODEL?: string;
  /** reasoning_effort for /kana (default "none"; gpt-5.6 accepts none/low/medium/high/xhigh). */
  KANA_REASONING_EFFORT?: string;
  /** "0" ignores `X-Kana: 1` on /analyze (device then falls back to POST
   *  /kana). Default "1" = bundle kana into the /analyze response. */
  KANA_BUNDLE?: string;
  /** reasoning_effort for /analyze when kana is bundled (unset = model
   *  default). Lower values shorten the response at some analysis cost. */
  ANALYZE_KANA_REASONING_EFFORT?: string;
  /** Comma-separated model ids offered to the device (GET /config). */
  MODELS?: string;
  /** OpenAI-compatible API base (default https://api.openai.com/v1).
   *  Point it at a Cloudflare Tunnel to use a local LLM (Ollama etc). */
  MAIN_API_BASE_URL?: string;
  /** Separate base for STT/TTS (default https://api.openai.com/v1) so voice
   *  keeps working when MAIN_API_BASE_URL points at a chat-only local LLM. */
  AUDIO_API_BASE_URL?: string;
  /** OpenAI Realtime API model for the device's "GPT Realtime" voice mode
   *  (default gpt-realtime). Realtime is OpenAI-only; TOICAMERA_TTS_API_KEY
   *  is reused as its bearer token. */
  REALTIME_MODEL?: string;
  /** Realtime output voice (marin/cedar/alloy/...). Empty = reuse TTS_VOICE. */
  REALTIME_VOICE?: string;
  /** Base for the Realtime WebSocket endpoint (default
   *  https://api.openai.com/v1) — kept separate from AUDIO_API_BASE_URL
   *  since most OpenAI-compatible bridges do not offer Realtime. */
  REALTIME_API_BASE_URL?: string;
  /** Upstream for POST /live: "gpt-live" (default, GPT-Live-1 + Responses
   *  delegation to a reasoning model) or "realtime" (the older gpt-realtime
   *  one-shot, kept as the in-request fallback). */
  LIVE_ENGINE?: string;
  /** GPT-Live voice model (default gpt-live-1). */
  LIVE_MODEL?: string;
  /** Reasoning model the GPT-Live session delegates to via Responses
   *  (default gpt-5.6-terra; gpt-5.6-luna is the cheaper option). */
  LIVE_BACKEND_MODEL?: string;
  /** reasoning.effort for that backend (unset = the model's default). */
  LIVE_BACKEND_REASONING?: string;
  /** GPT-Live output voice (default marin). */
  LIVE_VOICE?: string;
  /** Base for the GPT-Live WebSocket endpoint (default
   *  https://api.openai.com/v1). */
  LIVE_API_BASE_URL?: string;
  /** Output gap that ends a GPT-Live answer, in ms (default 1500) - the API
   *  emits no authoritative turn-completed event. */
  LIVE_END_SILENCE_MS?: string;
  /** Cap on /analyze reply tokens (default 500). */
  ANALYZE_MAX_TOKENS?: string;
  /** Style lines appended to the analyze system prompt depending on the
   *  device's AI-detail toggle (X-Detail: low|high). Retune output depth and
   *  length here — no firmware update needed. */
  ANALYZE_STYLE_LOW?: string;
  ANALYZE_STYLE_HIGH?: string;
}

type Lang = "ja" | "en" | "zh";

// Keep detail short enough to fit within about 40 seconds of speech.
const SYSTEM_PROMPT: Record<Lang, string> = {
  ja: `あなたはカメラ付き小型ガジェット「ToiCamera」のナレーターです。
撮影された写真に写っているものを、親しみやすく少しユーモラスな日本語で解説します。
- caption: 写真の主題を表す短い見出し(15文字以内)
- detail: 2〜3文の解説(150文字以内)。写っているものの説明に、豆知識やちょっとした一言を添える
専門用語は避け、聞いて楽しい語り口にしてください。JSON の文字列値はすべて日本語で出力してください。`,
  en: `You are the narrator for ToiCamera, a small camera gadget.
Explain what appears in the photo in friendly, slightly humorous English.
- caption: a short headline describing the main subject, at most 15 words
- detail: 2 to 3 sentences, about 200 characters or fewer; describe the subject and add a fun fact or playful observation
Avoid jargon and keep the narration easy and enjoyable to hear. Output all JSON string values in English.`,
  zh: `你是带摄像头的小型设备“ToiCamera”的解说员。
请用亲切、略带幽默的简体中文解说照片中的内容。
- caption：概括照片主体的短标题，不超过15个汉字
- detail：2至3句话，不超过150个汉字；说明画面内容，并补充一个小知识或有趣点评
避免专业术语，让解说轻松好懂。JSON 中的所有字符串值都必须使用简体中文。`,
};

const RESULT_SCHEMA = {
  type: "object",
  properties: {
    caption: { type: "string", description: "写真の見出し(15文字以内)" },
    detail: { type: "string", description: "2〜3文・150文字以内の日本語解説" },
  },
  required: ["caption", "detail"],
  additionalProperties: false,
} as const;

// Same, plus the kana intermediate representation of caption + detail for
// the on-device sanoTTS voice. Requested with `X-Kana: 1` (ja only) so a
// device in that voice mode skips the extra /kana round trip (~2 s).
const RESULT_SCHEMA_KANA = {
  type: "object",
  properties: {
    caption: RESULT_SCHEMA.properties.caption,
    detail: RESULT_SCHEMA.properties.detail,
    kana: {
      type: "string",
      description: "caption と detail を「。」で繋いだ全文のかな中間表現(ひらがな + アクセント記号)",
    },
  },
  required: ["caption", "detail", "kana"],
  additionalProperties: false,
} as const;

const DIGEST_SYSTEM_PROMPT: Record<Lang, string> = {
  ja: "あなたは行動ログの要約係。撮影・質問の見出しリストから、その人が今日なにをしているかを、親しみやすく少しユーモラスな日本語30字以内の1文で要約する。体言止めか『〜中』で軽快に",
  en: "Summarize what the person is doing today from the list of photo and question headlines. Write one friendly, lightly humorous English sentence of about 10 words.",
  zh: "根据拍摄和提问的标题列表，用简体中文概括这个人今天在做什么。只写一句亲切、略带幽默且不超过30个汉字的轻快短句。",
};

const DIGEST_SCHEMA = {
  type: "object",
  properties: {
    summary: { type: "string" },
  },
  required: ["summary"],
  additionalProperties: false,
} as const;

// --- /kana: text → kana intermediate representation for the on-device
// sanoTTS-jp voice (firmware/stopwatch/lib/sanotts). The device has no kanji
// dictionary (13.7 MB — does not fit next to the app in 16 MB flash), so the
// LLM that wrote the text also spells it out. Notation (sanoTTS-jp
// scripts/kana_g2p.py): hiragana + `[` pitch rise / `]` accent nucleus (fall
// after this mora) / `#` accent-phrase boundary / `_` pause / `?` question
// end / `°` devoiced vowel. Example: 今日は良い天気ですね。 →
// きょ][おわよ][いて][んきです°ね
const KANA_RULES = `規則:
1. ひらがなだけを使う。漢字・カタカナ・英字・数字・記号はすべて読みのひらがなに直す(例: AI→えーあい、3時→さんじ、100%→ひゃくぱーせんと、ToiCamera→といかめら)。
2. 発音どおりに書く: 助詞「は」→「わ」、「へ」→「え」、「を」→「お」。「おう」「えい」などの長音は「おお」「ええ」のように母音を重ねるか「ー」で書く(例: 東京→とおきょお、先生→せんせえ)。「ぢ」「づ」は「じ」「ず」。
3. アクセント(東京式): アクセント句ごとに、ピッチが上がる拍の直前に「[」、アクセント核(下がる直前の拍)の直後に「]」を置く。平板型は「[」だけで「]」を置かない。頭高型は1拍目の直後に「]」を置く(「[」は不要)。
4. 「、」「。」や文の切れ目はポーズ「_」に置き換える。疑問文の文末は「_」の代わりに「?」。
5. 無声化する母音(「です」「ます」の末尾の す、無声子音に挟まれた き・く・し・す・ち・つ・ひ・ふ・ぴ・ぷ など)は、そのかなの直後に「°」を付ける。
6. 出力に上記以外の文字(スペース・改行・句読点・漢字・カタカナ)を含めない。

例:
今日は良い天気ですね。 → きょ][おわよ][いて][んきです°ね
電源を入れてください。 → で][んげんお[いれてくださ]い
橋を渡ります。 → は[しお[わたりま]す°
箸を持ちます。 → は]しお[もちま]す°
バッテリー残量は十五パーセントです。 → ば]ってりーざ[んりょおわ_じゅ]うごぱーせ]んとです°
これは何ですか？ → こ[れわ[な]んです°か?
赤い花が咲いています。写真の中央に見えます。 → あ[かい[はな]が[さいていま]す°_しゃ[しんの[ちゅうおうに[みえま]す°`;

const KANA_SYSTEM_PROMPT = `あなたは日本語音声合成(sanoTTS-jp)の前処理器です。入力の日本語文を「かな中間表現」に変換し、JSON {"kana": "..."} だけを返してください。

${KANA_RULES}`;

// Appended to the ja analyze prompt when the device asks for kana.
const ANALYZE_KANA_ADDENDUM = `

追加で kana フィールドに、caption と detail を「。」で繋いだ全文を音声合成用の「かな中間表現」に変換して入れてください。
${KANA_RULES}`;

const KANA_SCHEMA = {
  type: "object",
  properties: {
    kana: { type: "string" },
  },
  required: ["kana"],
  additionalProperties: false,
} as const;

// Keep only what the device-side G2P accepts: hiragana, `ー`, the marks
// `[ ] # _ ^ $ ? ?! ?. ?~` and `°`. Katakana is folded to hiragana, Japanese
// punctuation becomes a pause, everything else is dropped.
function sanitizeKana(raw: string): string {
  let out = "";
  for (const ch of raw.normalize("NFKC")) {
    const cp = ch.codePointAt(0) ?? 0;
    if (cp >= 0x3041 && cp <= 0x3096) out += ch; // hiragana
    else if (cp >= 0x30a1 && cp <= 0x30f6) out += String.fromCodePoint(cp - 0x60); // katakana → hiragana
    else if (ch === "ー" || ch === "[" || ch === "]" || ch === "#" || ch === "_" || ch === "°" || ch === "?" || ch === "!" || ch === "." || ch === "~") out += ch;
    else if (ch === "、" || ch === "。" || ch === "，" || ch === "．" || ch === ",") out += "_";
    else if (ch === "？") out += "?";
    else if (ch === "゛") out += ""; // stray dakuten from NFKC of odd input
    // whitespace, kanji, latin, digits: dropped (the LLM was asked to spell them)
  }
  return out
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}

const MAX_IMAGE_BYTES = 4 * 1024 * 1024; // CamS3 は SVGA〜UXGA JPEG を送る想定 (~100-500KB)
const DEFAULT_MODELS = "gpt-5.6-terra,gpt-5.6-luna";

// Worker-defined model menu: the device fetches it via GET /config and only
// echoes one entry back in X-Model — adding or swapping models (including a
// local LLM behind MAIN_API_BASE_URL) is a Worker redeploy, never a firmware
// change.
function configuredModels(env: Env): string[] {
  return (env.MODELS || DEFAULT_MODELS)
    .split(",")
    .map((m) => m.trim())
    .filter(Boolean);
}

function openaiBase(env: Env): string {
  return (env.MAIN_API_BASE_URL || "https://api.openai.com/v1").replace(/\/+$/, "");
}

// STT/TTS stay on OpenAI even when chat points at a local LLM — most local
// servers only implement chat/completions.
function audioBase(env: Env): string {
  return (env.AUDIO_API_BASE_URL || "https://api.openai.com/v1").replace(/\/+$/, "");
}

function realtimeBase(env: Env): string {
  return (env.REALTIME_API_BASE_URL || "https://api.openai.com/v1").replace(/\/+$/, "");
}

function realtimeVoice(env: Env): string {
  return env.REALTIME_VOICE || env.TTS_VOICE;
}

// Whether the "GPT Realtime" voice mode can be offered to the device at all
// (same key as Worker TTS — Realtime is OpenAI-only, no separate flag var).
function realtimeAvailable(env: Env): boolean {
  return Boolean(env.TOICAMERA_TTS_API_KEY);
}

function pickModel(request: Request, env: Env): string {
  const requestedModel = request.headers.get("x-model");
  const menu = configuredModels(env);
  return requestedModel && menu.includes(requestedModel)
    ? requestedModel
    : menu[0];
}

function pickLang(request: Request): Lang {
  const requestedLang = request.headers.get("x-lang");
  return requestedLang === "en" || requestedLang === "zh" ? requestedLang : "ja";
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const CHUNK = 0x8000; // String.fromCharCode の引数上限を避けてチャンク変換
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

function toBase64(buf: ArrayBuffer): string {
  return bytesToBase64(new Uint8Array(buf));
}

const FALLBACK_RESULT = {
  caption: "解説できません",
  detail: "この写真はうまく解説できませんでした。別のものを撮ってみてください。",
};

// Chat completion against the configured OpenAI-compatible backend.
async function openaiChat(env: Env, payload: unknown): Promise<Response> {
  return fetch(`${openaiBase(env)}/chat/completions`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.TOICAMERA_MAIN_API_KEY}`,
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

// `X-Kana: 1` — the device is in the on-device sanoTTS voice mode and wants
// the kana intermediate representation bundled into /analyze (ja only).
function pickKana(request: Request, env: Env, lang: Lang): boolean {
  return lang === "ja" && env.KANA_BUNDLE !== "0" && request.headers.get("x-kana") === "1";
}

// The device only ever sends X-Detail low|high; what that MEANS is decided
// here, so the owner can retune output depth without touching firmware.
function analyzeStyle(env: Env, detailLevel: "low" | "high"): string {
  const extra =
    detailLevel === "high" ? env.ANALYZE_STYLE_HIGH : env.ANALYZE_STYLE_LOW;
  return extra && extra.trim() ? "\n" + extra.trim() : "";
}

function analyzeMaxTokens(env: Env): number {
  const n = Number(env.ANALYZE_MAX_TOKENS);
  return Number.isFinite(n) && n >= 100 && n <= 4000 ? Math.floor(n) : 500;
}

async function analyzeWithOpenAI(
  env: Env,
  imageB64: string,
  userText: string,
  model: string,
  detailLevel: "low" | "high",
  lang: Lang,
  withKana = false,
): Promise<Response> {
  const upstream = await openaiChat(env, {
    model,
    // kana roughly doubles the output text — give it room on top of the budget
    max_completion_tokens: analyzeMaxTokens(env) + (withKana ? 800 : 0),
    ...(withKana && env.ANALYZE_KANA_REASONING_EFFORT
      ? { reasoning_effort: env.ANALYZE_KANA_REASONING_EFFORT }
      : {}),
    messages: [
      {
        role: "system",
        content:
          SYSTEM_PROMPT[lang] + analyzeStyle(env, detailLevel) + (withKana ? ANALYZE_KANA_ADDENDUM : ""),
      },
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
      json_schema: {
        name: "toi_result",
        strict: true,
        schema: withKana ? RESULT_SCHEMA_KANA : RESULT_SCHEMA,
      },
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
  if (!withKana) {
    return new Response(msg.content, {
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  }
  // kana: reduce to what the on-device G2P accepts. An empty result just
  // makes the device fall back to POST /kana.
  try {
    const parsed = JSON.parse(msg.content) as { caption: string; detail: string; kana?: unknown };
    return json({
      caption: parsed.caption,
      detail: parsed.detail,
      kana: typeof parsed.kana === "string" ? sanitizeKana(parsed.kana) : "",
    });
  } catch (err) {
    console.error("[toi] analyze kana parse failed", err);
    return json(FALLBACK_RESULT);
  }
}

// Best-effort reverse geocoding (OSM Nominatim). Coordinates are rounded to
// ~100m and results cached in Cloudflare's edge cache (Nominatim usage policy
// requires caching; it also keeps the hint off the latency-critical path).
// ISO3166-2 -> prefecture name. Nominatim often omits address.state for
// Japan (Tokyo wards return only "ISO3166-2-lvl4": "JP-13").
const JP_PREFECTURES: Record<string, string> = {
  "JP-01": "北海道", "JP-02": "青森県", "JP-03": "岩手県", "JP-04": "宮城県",
  "JP-05": "秋田県", "JP-06": "山形県", "JP-07": "福島県", "JP-08": "茨城県",
  "JP-09": "栃木県", "JP-10": "群馬県", "JP-11": "埼玉県", "JP-12": "千葉県",
  "JP-13": "東京都", "JP-14": "神奈川県", "JP-15": "新潟県", "JP-16": "富山県",
  "JP-17": "石川県", "JP-18": "福井県", "JP-19": "山梨県", "JP-20": "長野県",
  "JP-21": "岐阜県", "JP-22": "静岡県", "JP-23": "愛知県", "JP-24": "三重県",
  "JP-25": "滋賀県", "JP-26": "京都府", "JP-27": "大阪府", "JP-28": "兵庫県",
  "JP-29": "奈良県", "JP-30": "和歌山県", "JP-31": "鳥取県", "JP-32": "島根県",
  "JP-33": "岡山県", "JP-34": "広島県", "JP-35": "山口県", "JP-36": "徳島県",
  "JP-37": "香川県", "JP-38": "愛媛県", "JP-39": "高知県", "JP-40": "福岡県",
  "JP-41": "佐賀県", "JP-42": "長崎県", "JP-43": "熊本県", "JP-44": "大分県",
  "JP-45": "宮崎県", "JP-46": "鹿児島県", "JP-47": "沖縄県",
};

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
    // &fmt=v4 keys the cache format (v4: prefecture via ISO3166-2 table)
    const cacheKey = new Request(url + "&fmt=v4");
    const cached = await cache.match(cacheKey);
    if (cached) {
      const data = (await cached.json().catch(() => null)) as PlaceHint | null;
      if (data && typeof data.place === "string") return data;
    }
    const res = await fetch(url, {
      headers: { "user-agent": "ToiCamera/1.0 (+https://github.com/aieo-product/ToiCamera)" },
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
    const prefecture =
      a.state ?? a.province ?? a.region ??
      JP_PREFECTURES[a["ISO3166-2-lvl4"] ?? ""] ?? "";
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
      `https://express.heartrails.com/api/json?method=getStations&x=${rlon}&y=${rlat}`;
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

  const lang = pickLang(request);
  const { searchParams } = new URL(request.url);
  const lat = searchParams.get("lat");
  const lon = searchParams.get("lon");
  let userText: string;
  if (lang === "en") {
    userText = "Please explain this photo.";
  } else if (lang === "zh") {
    userText = "请解说这张照片。";
  } else {
    userText = "この写真を解説してください。";
  }
  if (lat && lon) {
    const hint = await placeHint(lat, lon, ctx);
    if (hint.place) {
      if (lang === "en") {
        userText = `This photo was taken near ${hint.place}. Explain the photo, and naturally use the location context only when it fits the visible content.`;
      } else if (lang === "zh") {
        userText = `这张照片拍摄于${hint.place}附近。请解说照片，并仅在地点信息与画面内容相符时自然融入。`;
      } else {
        userText = `撮影場所: ${hint.place} 付近。この写真を解説してください。場所の文脈が内容と合うときは自然に織り込んでください。`;
      }
    }
  }

  return analyzeWithOpenAI(
    env,
    toBase64(image),
    userText,
    pickModel(request, env),
    pickDetail(request),
    lang,
    pickKana(request, env, lang),
  );
}

const ANSWER_SCHEMA = {
  type: "object",
  properties: {
    answer: { type: "string", description: "2文以内・120文字以内の日本語回答" },
  },
  required: ["answer"],
  additionalProperties: false,
} as const;

async function handleAsk(request: Request, env: Env): Promise<Response> {
  const audio = await request.arrayBuffer();
  if (audio.byteLength < 4000) return json({ error: "audio too short" }, 400);
  if (audio.byteLength > 2 * 1024 * 1024) return json({ error: "audio too large" }, 413);

  const { searchParams } = new URL(request.url);
  const caption = searchParams.get("caption") ?? "";
  const detail = searchParams.get("detail") ?? "";
  const lang = pickLang(request);

  // STT — free-token key only (paid fallback removed by owner's decision)
  async function transcribe(model: string): Promise<{ text: string | null; status: number }> {
    const form = new FormData();
    form.append("file", new File([audio], "q.wav", { type: "audio/wav" }));
    form.append("model", model);
    form.append("language", lang);
    const res = await fetch(`${audioBase(env)}/audio/transcriptions`, {
      method: "POST",
      headers: { authorization: `Bearer ${env.TOICAMERA_MAIN_API_KEY}` },
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
      { role: "system", content: SYSTEM_PROMPT[lang] },
      {
        role: "user",
        content:
          lang === "en"
            ? `You previously described the photo as: "${caption}. ${detail}"
The user's question: ${question}
Answer in friendly, lightly humorous English based on the photo context. Use at most 2 sentences and about 200 characters.`
            : lang === "zh"
              ? `你之前这样解说了这张照片：“${caption}。${detail}”
用户的问题：${question}
请结合照片内容，用亲切、略带幽默的简体中文回答，不超过2句话和120个汉字。`
              : `さっき撮った写真をあなたはこう解説しました:「${caption}。${detail}」
ユーザーからの質問: ${question}
写真の内容を踏まえて、親しみやすく少しユーモラスな日本語で、2文・120文字以内で答えてください。`,
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
  const lang = pickLang(request);

  try {
    const upstream = await openaiChat(env, {
      model,
      max_completion_tokens: 100,
      messages: [
        { role: "system", content: DIGEST_SYSTEM_PROMPT[lang] },
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
    const summary = parsed.summary.trim();
    return json({
      summary:
        lang === "en"
          ? summary.split(/\s+/).slice(0, 10).join(" ")
          : Array.from(summary).slice(0, 30).join(""),
    });
  } catch (err) {
    console.error("[toi] digest failed", err);
    return json({ summary: "" });
  }
}

async function handleKana(request: Request, env: Env): Promise<Response> {
  const body = (await request.json().catch(() => null)) as { text?: unknown } | null;
  const text =
    body && typeof body.text === "string" ? Array.from(body.text.trim()).slice(0, 500).join("") : "";
  if (!text) {
    return json({ error: "missing text" }, 400);
  }
  // Spelling out kana is transcription, not reasoning: KANA_MODEL (optional)
  // can point at a cheaper/faster model, and reasoning effort is "none" so
  // the device is not kept waiting (default-effort gpt-5.6 took 10–25 s).
  const model = env.KANA_MODEL || pickModel(request, env);

  try {
    const upstream = await openaiChat(env, {
      model,
      reasoning_effort: env.KANA_REASONING_EFFORT || "none",
      max_completion_tokens: 4000,
      messages: [
        { role: "system", content: KANA_SYSTEM_PROMPT },
        { role: "user", content: text },
      ],
      response_format: {
        type: "json_schema",
        json_schema: { name: "toi_kana", strict: true, schema: KANA_SCHEMA },
      },
    });
    if (!upstream.ok) {
      const detail = await upstream.text();
      console.error("[toi] kana upstream error", upstream.status, detail);
      return json({ error: "kana upstream failed", status: upstream.status }, 502);
    }
    const data = (await upstream.json()) as {
      choices?: { finish_reason?: string; message?: { content?: string; refusal?: string } }[];
    };
    const choice = data.choices?.[0];
    const message = choice?.message;
    if (!message?.content || message.refusal) {
      console.error("[toi] kana empty content", choice?.finish_reason, message?.refusal);
      return json({ error: "kana empty" }, 502);
    }
    const parsed = JSON.parse(message.content) as { kana?: unknown };
    const kana = typeof parsed.kana === "string" ? sanitizeKana(parsed.kana) : "";
    if (!kana) {
      console.error("[toi] kana sanitized to empty", message.content.slice(0, 200));
      return json({ error: "kana empty" }, 502);
    }
    return json({ kana });
  } catch (err) {
    console.error("[toi] kana failed", err);
    return json({ error: "kana failed" }, 502);
  }
}

// PCM16 mono → RIFF/WAVE, matching the header shape the device's WAV parser
// expects (same layout /audio/speech already produces after patching).
function pcm16ToWav(pcm: Uint8Array, sampleRate: number): Uint8Array {
  const dataLen = pcm.length - (pcm.length % 2); // whole samples only
  const buf = new Uint8Array(44 + dataLen);
  const dv = new DataView(buf.buffer);
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) dv.setUint8(offset + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  dv.setUint32(4, 36 + dataLen, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  dv.setUint32(16, 16, true); // fmt chunk size
  dv.setUint16(20, 1, true); // PCM
  dv.setUint16(22, 1, true); // mono
  dv.setUint32(24, sampleRate, true);
  dv.setUint32(28, sampleRate * 2, true); // byte rate (16-bit mono)
  dv.setUint16(32, 2, true); // block align
  dv.setUint16(34, 16, true); // bits per sample
  writeStr(36, "data");
  dv.setUint32(40, dataLen, true);
  buf.set(pcm.subarray(0, dataLen), 44);
  return buf;
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

// Budget: the device waits 30 s for /tts in total (main.cpp ttsHttp timeout,
// raised to 45 s for engine=realtime), and a failed Realtime attempt is
// followed by a full /audio/speech render (~3-5 s) — so Realtime gets 15 s.
const REALTIME_TIMEOUT_MS = 15_000;
// The Realtime model is an LLM, not a TTS engine: pin it to verbatim reading
// so captions in ja/en/zh come out unchanged.
const REALTIME_READ_ALOUD_INSTRUCTIONS =
  "You are a text-to-speech engine. Read the user's message aloud verbatim, in its original language (Japanese, English or Chinese), with natural, friendly intonation. Do not add, omit, translate, paraphrase or comment on anything. Output speech only.";
// ~40 s of 24 kHz mono PCM16; the WAV (+44 B) stays under the device's 2 MB
// kMaxTtsWav (2,097,152 B). A "high" detail answer runs ~25-30 s of speech,
// so the cap is only a runaway guard.
const REALTIME_MAX_PCM_BYTES = 1_900_000;

// text → WAV via the OpenAI Realtime API (WebSocket only — no REST). Returns
// null on any failure so callers fall back to the regular /audio/speech TTS;
// never throws.
async function realtimeSpeech(text: string, env: Env): Promise<Uint8Array | null> {
  if (!env.TOICAMERA_TTS_API_KEY) return null;
  const model = env.REALTIME_MODEL || "gpt-realtime";
  // Workers open outbound WebSockets with an https URL + `Upgrade: websocket`
  // (a wss:// URL is rejected by the Workers fetch()).
  const url = `${realtimeBase(env)}/realtime?model=${encodeURIComponent(model)}`;
  const startedAt = Date.now();

  try {
    const upstream = await fetch(url, {
      headers: {
        Upgrade: "websocket",
        Authorization: `Bearer ${env.TOICAMERA_TTS_API_KEY}`,
      },
    });
    const ws = upstream.webSocket;
    if (!ws) {
      console.error("[toi] realtime: no websocket in upstream response", upstream.status);
      await upstream.body?.cancel().catch(() => undefined);
      return null;
    }
    ws.accept();

    return await new Promise<Uint8Array | null>((resolve) => {
      const chunks: Uint8Array[] = [];
      let pcmBytes = 0;
      let settled = false;
      const finish = (result: Uint8Array | null) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        try {
          ws.close();
        } catch {
          // already closing/closed
        }
        resolve(result);
      };
      const timer = setTimeout(() => {
        console.error("[toi] realtime: timed out waiting for audio");
        finish(null);
      }, REALTIME_TIMEOUT_MS);

      ws.addEventListener("message", (event: MessageEvent) => {
        if (typeof event.data !== "string") return;
        let msg: Record<string, unknown>;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        const type = msg.type;
        if (type === "session.created") {
          ws.send(
            JSON.stringify({
              type: "session.update",
              session: {
                type: "realtime",
                output_modalities: ["audio"],
                audio: {
                  output: { voice: realtimeVoice(env), format: { type: "audio/pcm", rate: 24000 } },
                },
              },
            }),
          );
          ws.send(
            JSON.stringify({
              type: "response.create",
              response: {
                conversation: "none",
                output_modalities: ["audio"],
                instructions: REALTIME_READ_ALOUD_INSTRUCTIONS,
                input: [
                  {
                    type: "message",
                    role: "user",
                    content: [{ type: "input_text", text }],
                  },
                ],
              },
            }),
          );
        } else if (type === "response.output_audio.delta" || type === "response.audio.delta") {
          const delta = msg.delta;
          if (typeof delta === "string") {
            let bytes: Uint8Array;
            try {
              bytes = base64ToBytes(delta);
            } catch (err) {
              // Malformed/oversized delta — never leave the promise pending.
              console.error("[toi] realtime: bad audio delta", err);
              finish(null);
              return;
            }
            pcmBytes += bytes.length;
            chunks.push(bytes);
            if (pcmBytes >= REALTIME_MAX_PCM_BYTES) {
              // Deliberate cut-off: what we have is complete, playable speech.
              console.warn("[toi] realtime: hit max PCM size, cutting off");
              finish(concatBytes(chunks));
            }
          }
        } else if (type === "response.done") {
          // Only a completed response counts. Anything else (failed,
          // incomplete, cancelled) is discarded so the caller re-renders the
          // whole line with the regular TTS instead of playing a fragment.
          const status = (msg.response as { status?: unknown } | undefined)?.status;
          if (status !== "completed" || !chunks.length) {
            console.warn("[toi] realtime: response.done status", status, JSON.stringify(msg).slice(0, 300));
            finish(null);
            return;
          }
          console.log(
            `[toi] realtime: ${pcmBytes} B pcm, ${Date.now() - startedAt} ms, model=${model} voice=${realtimeVoice(env)}`,
          );
          finish(concatBytes(chunks));
        } else if (type === "error" || type === "response.error") {
          console.error("[toi] realtime: error event", JSON.stringify(msg).slice(0, 300));
          finish(null);
        }
      });
      // Disconnect or socket error before response.done: partial audio is
      // not returned (same rule as the timeout) — the TTS fallback re-renders.
      ws.addEventListener("close", () => {
        if (!settled) console.error("[toi] realtime: socket closed before response.done");
        finish(null);
      });
      ws.addEventListener("error", (event: ErrorEvent) => {
        if (settled) return; // our own close() after finish() also surfaces here
        console.error("[toi] realtime: socket error", event.message || event);
        finish(null);
      });
    });
  } catch (err) {
    console.error("[toi] realtime: connect failed", err);
    return null;
  }
}

function concatBytes(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

async function ttsUpstream(text: string, env: Env): Promise<{ buf: Uint8Array } | { status: number }> {
  const upstream = await fetch(`${audioBase(env)}/audio/speech`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.TOICAMERA_TTS_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: env.TTS_MODEL || "gpt-4o-mini-tts",
      voice: env.TTS_VOICE,
      input: text.slice(0, 500),
      response_format: "wav", // ESP32 側は M5Unified Speaker (WAV/RAW のみ) で再生
    }),
  });

  if (!upstream.ok) {
    const detail = await upstream.text();
    console.error("TTS upstream error", upstream.status, detail);
    return { status: upstream.status };
  }

  // Buffer the stream: the device needs Content-Length, and OpenAI streams
  // WAV with 0xFFFFFFFF placeholder sizes in the RIFF header — patch in the
  // real ones so the device-side WAV parser sees a well-formed file.
  const buf = new Uint8Array(await upstream.arrayBuffer());
  if (buf.length >= 44) {
    const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    dv.setUint32(4, buf.length - 8, true);
    if (buf[36] === 0x64 && buf[37] === 0x61 && buf[38] === 0x74 && buf[39] === 0x61) {
      dv.setUint32(40, buf.length - 44, true);
    }
  }
  return { buf };
}

async function handleTts(request: Request, env: Env): Promise<Response> {
  const body = (await request.json().catch(() => null)) as { text?: string; engine?: string } | null;
  const text = body?.text?.trim();
  if (!text) {
    return json({ error: "missing text" }, 400);
  }

  let buf: Uint8Array | null = null;
  let engineUsed: "realtime" | "tts" = "tts";
  if (body?.engine === "realtime") {
    const pcm = await realtimeSpeech(text.slice(0, 500), env);
    if (pcm && pcm.length > 0) {
      buf = pcm16ToWav(pcm, 24000);
      engineUsed = "realtime";
    } else {
      console.warn("[toi] tts: realtime failed, falling back to tts");
    }
  }

  let fallbackStatus: number | undefined;
  if (!buf) {
    const result = await ttsUpstream(text, env);
    if ("buf" in result) {
      buf = result.buf;
    } else {
      fallbackStatus = result.status;
    }
    engineUsed = "tts";
  }
  if (!buf) {
    return json({ error: "tts upstream failed", status: fallbackStatus }, 502);
  }

  return new Response(buf, {
    headers: {
      "content-type": "audio/wav",
      "content-length": String(buf.length),
      "x-voice-engine": engineUsed,
    },
  });
}

// --- POST /live: one Realtime session (photo [+ question audio] → streamed
// speech + transcript). The device plays the audio while it arrives instead
// of waiting for a finished WAV (/analyze + /tts took ~10 s to first sound).
//
// Wire format (application/octet-stream, chunked): the 4-byte magic "TOI1",
// then frames of `type(1 B) + len(uint32 LE) + payload`:
//   A  PCM16 mono 24 kHz audio bytes (a Realtime output_audio delta, verbatim)
//   T  transcript delta (UTF-8)
//   E  terminal JSON {caption, detail, transcript, question, status, pcmBytes, ms}
//      status is "completed", or "truncated" when the Worker stopped forwarding
//      audio (size cap, idle timeout or disconnect after audio had started) —
//      the device treats both as a normal end and keeps what it played.
//   X  error JSON {error} — only ever sent BEFORE any audio frame; the device
//      falls back to /analyze + /tts (or /ask) on it.
const LIVE_MAGIC = "TOI1";
// Idle guard: reset on every upstream event. Realtime normally starts
// speaking in ~1 s and streams continuously, so a 15 s gap means it hung.
const LIVE_IDLE_TIMEOUT_MS = 15_000;
// Absolute guard on top of the idle one — a runaway session, not a budget.
const LIVE_MAX_TOTAL_MS = 90_000;
// ~40 s of 24 kHz mono PCM16 (same guard as /tts).
const LIVE_MAX_PCM_BYTES = 1_900_000;
const LIVE_MAX_JPEG_BYTES = 2 * 1024 * 1024;
const LIVE_MAX_WAV_BYTES = 2 * 1024 * 1024;
const LIVE_MIN_WAV_BYTES = 4000;
const LIVE_RATE = 24000;

type LiveMode = "capture" | "ask";

function liveFrame(type: "A" | "T" | "E" | "X", payload: Uint8Array): Uint8Array {
  const out = new Uint8Array(5 + payload.length);
  out[0] = type.charCodeAt(0);
  new DataView(out.buffer).setUint32(1, payload.length, true);
  out.set(payload, 5);
  return out;
}

function int16ToLeBytes(pcm: Int16Array): Uint8Array {
  const out = new Uint8Array(pcm.length * 2);
  const dv = new DataView(out.buffer);
  for (let i = 0; i < pcm.length; i++) dv.setInt16(i * 2, pcm[i], true);
  return out;
}

// RIFF/WAVE (PCM16 mono, any sample rate) → PCM16 mono at 24 kHz, the only
// input format the Realtime API documents. The device records 16 kHz, so this
// is usually a 2:3 linear interpolation. Returns null on anything it cannot
// read, so the caller can answer 400 instead of sending garbage upstream.
function wavToPcm24k(bytes: Uint8Array): Int16Array | null {
  if (bytes.length < 44) return null;
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const tag = (o: number): string =>
    String.fromCharCode(bytes[o], bytes[o + 1], bytes[o + 2], bytes[o + 3]);
  if (tag(0) !== "RIFF" || tag(8) !== "WAVE") return null;

  let format = 0;
  let channels = 0;
  let rate = 0;
  let bits = 0;
  let dataOffset = -1;
  let dataLength = 0;
  let offset = 12;
  while (offset + 8 <= bytes.length) {
    const id = tag(offset);
    const size = dv.getUint32(offset + 4, true);
    const body = offset + 8;
    const avail = bytes.length - body;
    if (id === "fmt " && size >= 16 && avail >= 16) {
      format = dv.getUint16(body, true);
      channels = dv.getUint16(body + 2, true);
      rate = dv.getUint32(body + 4, true);
      bits = dv.getUint16(body + 14, true);
    } else if (id === "data") {
      dataOffset = body;
      // Streaming writers leave 0 / 0xFFFFFFFF placeholders: take the rest.
      dataLength = size === 0 || size > avail ? avail : size;
      break;
    }
    if (size === 0 || size > avail) break; // malformed/placeholder size
    offset = body + size + (size % 2); // chunks are word-aligned
  }

  if (format !== 1 || channels !== 1 || bits !== 16) return null;
  if (dataOffset < 0 || dataLength < 2) return null;
  if (rate < 4000 || rate > 192000) return null;

  const count = Math.floor(dataLength / 2);
  const src = new Int16Array(count);
  for (let i = 0; i < count; i++) src[i] = dv.getInt16(dataOffset + i * 2, true);
  if (rate === LIVE_RATE) return src;

  const outCount = Math.floor((count * LIVE_RATE) / rate);
  if (outCount < 1) return null;
  const out = new Int16Array(outCount);
  const step = rate / LIVE_RATE;
  for (let i = 0; i < outCount; i++) {
    const pos = i * step;
    const i0 = Math.floor(pos);
    const i1 = i0 + 1 < count ? i0 + 1 : count - 1;
    const frac = pos - i0;
    out[i] = Math.round(src[i0] * (1 - frac) + src[i1] * frac);
  }
  return out;
}

// Spoken-narrator version of SYSTEM_PROMPT: the Realtime model both writes
// and speaks, so the shape of the answer is asked for in prose instead of a
// JSON schema. The first sentence doubles as the on-screen caption.
const LIVE_INSTRUCTIONS: Record<Lang, { capture: string; ask: string }> = {
  ja: {
    capture: `あなたはカメラ付き小型ガジェット「ToiCamera」のナレーターです。撮影された写真に写っているものを、親しみやすく少しユーモラスな話し言葉で声に出して解説します。
最初の1文は写真の主題を表す短い見出し(15文字以内)にして、そのあとに2〜3文(合計150文字以内)の解説を続けてください。写っているものの説明に、豆知識やちょっとした一言を添えます。
専門用語は避け、聞いて楽しい語り口で。かならず日本語だけで話してください。`,
    ask: `あなたはカメラ付き小型ガジェット「ToiCamera」のナレーターです。ユーザーが撮った写真と、その写真についての音声の質問が届きます。
写真の内容を踏まえて、親しみやすく少しユーモラスな話し言葉で、2文以内で声に出して答えてください。音声が聞き取れないときは、その旨を一言だけ伝えます。
専門用語は避け、かならず日本語だけで話してください。`,
  },
  en: {
    capture: `You are the narrator for ToiCamera, a small camera gadget. Speak aloud about what appears in the photo in friendly, slightly humorous English.
Make the first sentence a short headline of at most 15 words naming the main subject, then continue with 2 to 3 sentences describing it and adding a fun fact or playful observation.
Avoid jargon and keep it enjoyable to hear. Speak only in English.`,
    ask: `You are the narrator for ToiCamera, a small camera gadget. You receive a photo the user took and a spoken question about it.
Answer aloud in friendly, slightly humorous English in at most 2 sentences, based on what the photo shows. If the audio is unintelligible, say so briefly.
Avoid jargon. Speak only in English.`,
  },
  zh: {
    capture: `你是带摄像头的小型设备“ToiCamera”的解说员。请用亲切、略带幽默的口语朗读解说照片中的内容。
第一句是概括照片主体的短标题(不超过15个字)，随后用2至3句话(合计不超过150个字)说明画面内容，并补充一个小知识或有趣点评。
避免专业术语，让解说轻松好懂。请只使用简体中文说话。`,
    ask: `你是带摄像头的小型设备“ToiCamera”的解说员。你会收到用户拍摄的照片和一段关于这张照片的语音提问。
请结合照片内容，用亲切、略带幽默的口语在2句话以内朗读回答。如果听不清语音，就简短说明一下。
避免专业术语，请只使用简体中文说话。`,
  },
};

const LIVE_USER_TEXT: Record<Lang, { capture: string; ask: string }> = {
  ja: { capture: "この写真を解説してください。", ask: "この写真について、いまの音声の質問に答えてください。" },
  en: { capture: "Describe this photo.", ask: "Answer my spoken question about this photo." },
  zh: { capture: "请解说这张照片。", ask: "请回答我刚才关于这张照片的语音提问。" },
};

// The transcript arrives as one spoken paragraph; the device's result screen
// wants a headline + body, so cut at the first sentence terminator.
function splitCaption(transcript: string, lang: Lang): { caption: string; detail: string } {
  const text = transcript.trim();
  if (!text) return { caption: "", detail: "" };
  // English: a terminator only counts at a word boundary, so "Dr." and "3.5"
  // do not end the headline. ja/zh: any full-width terminator.
  const m = lang === "en" ? /[.!?](?=\s|$)/.exec(text) : /[。．.!?！？]/.exec(text);
  const at = m ? m.index : -1;
  const head = (at >= 0 ? text.slice(0, at) : text).trim();
  const rest = at >= 0 ? text.slice(at + 1).trim() : "";
  // en: 15 words, and never more than 80 characters (a reply in the wrong
  // language has no spaces to cut at); ja/zh: 15 characters.
  const truncate = (v: string): string =>
    lang === "en"
      ? Array.from(v.split(/\s+/).filter(Boolean).slice(0, 15).join(" ")).slice(0, 80).join("")
      : Array.from(v).slice(0, 15).join("");
  // One-sentence answers: the whole text is the headline, no body (the device
  // shows the caption alone rather than the same sentence twice). Without any
  // terminator the caption is a cut-off prefix, so keep the full text as body.
  const caption = truncate(head || text);
  const detail = at >= 0 ? rest : caption === text ? "" : text;
  return { caption, detail };
}

// ---------------------------------------------------------------------------
// /live upstream drivers
//
// The device contract (TOI1 + A/T/E/X frames) is owned by handleLive() below;
// everything upstream-specific lives in a LiveDriver so the engine can be
// swapped with a var — and swapped again mid-request when the primary fails
// before a single audio byte reached the device.
// ---------------------------------------------------------------------------

// GPT-Live has no authoritative "turn finished" event ("There is no item ID or
// authoritative turn-completed event" — live-conversations guide), so the end
// of the answer is inferred from a gap in output deltas with no delegated
// Responses call still running.
const LIVE_END_SILENCE_MS = 2500; // gpt-live pauses mid-answer; 1.5 s cut long readings
// When no delegation was ever observed (unexpected on this endpoint), be
// more patient before deciding the voice model is done.
const LIVE_END_SILENCE_NO_DELEGATION_MS = 4000;
// A delegated backend call that never reports completion is assumed done
// after this long (see the watchdog in gptLiveDriver).
const LIVE_DELEGATION_TIMEOUT_MS = 30_000;
// After the backend result arrives, how long to wait for the voice model to
// start speaking it before giving up on the rest of the answer.
const LIVE_POST_DELEGATION_WAIT_MS = 12_000;
// Full-duplex output never stops: between sentences and after the answer the
// server keeps streaming near-silent PCM. Chunks whose peak sample is below
// this are "silence" — forwarded only inside short pauses, never counted as
// output activity for the end-of-answer rule.
const LIVE_SPEECH_PEAK = 400; // ≈ -38 dBFS on PCM16
const LIVE_PAUSE_KEEP_MS = 500;

function pcm16Peak(bytes: Uint8Array): number {
  let peak = 0;
  const n = bytes.length - (bytes.length % 2);
  for (let i = 0; i < n; i += 2) {
    let v = bytes[i] | (bytes[i + 1] << 8);
    if (v & 0x8000) v -= 0x10000;
    if (v < 0) v = -v;
    if (v > peak) peak = v;
  }
  return peak;
}
// session.started must arrive quickly — it is the first server event after
// session.start and gates everything else. Missing it = fall back to Realtime.
const LIVE_SESSION_START_TIMEOUT_MS = 10_000;
// The backend may reason for a while before the voice model speaks. This is
// the guard for "the session is alive (response.event deltas keep the idle
// timer fed) but no audio is ever produced".
const LIVE_FIRST_AUDIO_TIMEOUT_MS = 20_000;
// session.close → session.closed carries the usage we log; never block the
// device's terminal frame on it for longer than this.
const LIVE_CLOSE_WAIT_MS = 2_000;
// 100 ms of PCM16 mono @24 kHz, the documented append granularity.
const LIVE_AUDIO_CHUNK_BYTES = 4800;
// Push-to-talk has no VAD commit event, so the recording is followed by
// silence to let the server's turn detection close the user turn.
const LIVE_TAIL_SILENCE_MS = 800;
const LIVE_MAX_HISTORY_PAIRS = 10;
const LIVE_MAX_HISTORY_CHARS = 500;
const LIVE_MAX_HISTORY_BYTES = 32 * 1024;

function liveEngine(env: Env): "gpt-live" | "realtime" {
  return env.LIVE_ENGINE === "realtime" ? "realtime" : "gpt-live";
}

function liveBase(env: Env): string {
  return (env.LIVE_API_BASE_URL || "https://api.openai.com/v1").replace(/\/+$/, "");
}

function liveModel(env: Env): string {
  return env.LIVE_MODEL || "gpt-live-1";
}

function liveBackendModel(env: Env): string {
  return env.LIVE_BACKEND_MODEL || "gpt-5.6-terra";
}

function liveVoice(env: Env): string {
  return env.LIVE_VOICE || "marin";
}

function liveEndSilenceMs(env: Env): number {
  const v = Number(env.LIVE_END_SILENCE_MS);
  return Number.isFinite(v) && v >= 200 && v <= 10_000 ? v : LIVE_END_SILENCE_MS;
}

// Recent Q&A the device may append to the body (X-History-Length). Kept as a
// plain pair list so both drivers can shape it their own way.
type LiveHistoryPair = { q: string; a: string };

function parseLiveHistory(raw: string): LiveHistoryPair[] | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!Array.isArray(data)) return null;
  const out: LiveHistoryPair[] = [];
  const clip = (v: unknown): string =>
    typeof v === "string" ? Array.from(v).slice(0, LIVE_MAX_HISTORY_CHARS).join("") : "";
  for (const entry of data.slice(-LIVE_MAX_HISTORY_PAIRS)) {
    if (!isRecord(entry)) return null;
    const q = clip(entry.q);
    const a = clip(entry.a);
    if (!q && !a) continue;
    out.push({ q, a });
  }
  return out;
}

// Responses-style prior turns: what GPT-Live's session.input wants, and what
// the Realtime driver prepends to its one-shot response.create input.
function liveHistoryItems(history: LiveHistoryPair[]): unknown[] {
  const items: unknown[] = [];
  for (const { q, a } of history) {
    if (q) items.push({ type: "message", role: "user", content: [{ type: "input_text", text: q }] });
    if (a) items.push({ type: "message", role: "assistant", content: [{ type: "output_text", text: a }] });
  }
  return items;
}

// The live (voice) model only speaks; the photo and every factual question go
// to the delegated Responses backend. Keep these short — the live prompt
// controls speaking behaviour, the procedure lives in the backend prompt.
const GPT_LIVE_VOICE_INSTRUCTIONS: Record<Lang, string> = {
  ja: `あなたはカメラ付き小型ガジェット「ToiCamera」のナレーターです。親しみやすく少しユーモラスな話し言葉で、かならず日本語だけで話してください。
写真の説明や、事実・知識が必要な質問は、かならずバックエンドに委任し、その結果が返ってくるまで答えを推測しないでください。待っている間は「ちょっと見てみますね」程度の短い相づちを入れてもかまいません。
バックエンドの結果が届いたら、それをもとに2〜4文で話します。専門用語は避け、聞いて楽しい語り口にしてください。`,
  en: `You are the narrator for ToiCamera, a small camera gadget. Speak in friendly, slightly humorous English, and speak only in English.
Always delegate describing the photo and any factual or knowledge question to the backend, and wait for its result before answering — never guess it. A short acknowledgement such as "let me take a look" is fine while you wait.
Once the backend result arrives, speak it back in 2 to 4 sentences. Avoid jargon and keep it enjoyable to hear.`,
  zh: `你是带摄像头的小型设备“ToiCamera”的解说员。请用亲切、略带幽默的口语说话，并且只使用简体中文。
解说照片以及任何需要事实或知识的问题，都必须委托给后端，并在结果返回之前不要猜测答案。等待时可以说一句“我看看”之类的简短应答。
收到后端结果后，用2至4句话讲出来。避免专业术语，让解说轻松好懂。`,
};

// The delegated Responses model is the one that actually looks at the photo.
const GPT_LIVE_BACKEND_INSTRUCTIONS: Record<Lang, string> = {
  ja: `あなたはカメラ付き小型ガジェット「ToiCamera」の解説エンジンです。ユーザーが撮った写真を見て答えます。
写真の解説を求められたときは、まず主題を表す1文の見出し(15文字以内)を書き、続けて2〜3文(合計150文字以内)で内容を説明し、豆知識やちょっとした一言を添えてください。
質問されたときは、写真を文脈として使いつつ一般知識でも補い、4文以内で質問に直接答えてください。
出力は音声で読み上げられます。箇条書きや記号は使わず、かならず日本語で答えてください。`,
  en: `You are the description engine for ToiCamera, a small camera gadget. You look at the photo the user took and answer from it.
When asked to describe the photo, start with a one-sentence headline (at most 15 words) naming the main subject, then 2 to 3 sentences describing it with a fun fact or playful observation.
When asked a question, answer it directly in at most 4 sentences, using the photo as context and filling in with general knowledge.
Your output is read aloud: no bullet points or markup, and always reply in English.`,
  zh: `你是带摄像头的小型设备“ToiCamera”的解说引擎。请观察用户拍摄的照片并据此回答。
被要求解说照片时，先写一句概括主体的短标题(不超过15个字)，随后用2至3句话(合计不超过150个字)说明画面内容，并补充一个小知识或有趣点评。
被提问时，请以照片为背景并结合一般知识，用不超过4句话直接回答问题。
输出会被朗读出来：不要使用项目符号或标记，并且必须用简体中文回答。`,
};

// The text half of the response.item.create the backend receives with the photo.
const GPT_LIVE_BACKEND_TEXT: Record<Lang, { capture: string; ask: string }> = {
  ja: {
    capture: "この写真を解説してください。",
    ask: "ユーザーはこれからこの写真について音声で質問します。その質問に、この写真を文脈として答えてください。",
  },
  en: {
    capture: "Describe this photo.",
    ask: "The user will now ask a spoken question about this photo. Answer it, using the photo as context.",
  },
  zh: {
    capture: "请解说这张照片。",
    ask: "用户接下来会用语音询问这张照片。请以这张照片为背景回答那个问题。",
  },
};

// Everything a driver is allowed to do to the device-facing stream. The shell
// owns framing, timeouts, the size cap and the terminal frame; a driver only
// reports what the upstream said.
interface LiveCtx {
  readonly mode: LiveMode;
  readonly lang: Lang;
  /** JPEG as a data: URL, ready to drop into an image content part. */
  readonly imageUrl: string;
  /** Files API id of the photo (gpt-live), "" when the upload was skipped or failed. */
  readonly imageFileId: string;
  /** ask: the recorded question as base64 PCM16 mono 24 kHz (one blob). */
  readonly audioB64: string;
  /** ask: the same audio as samples, for drivers that stream it in chunks. */
  readonly pcm: Int16Array | null;
  readonly history: LiveHistoryPair[];
  pushAudio(bytes: Uint8Array): void;
  pushTranscript(text: string): void;
  setQuestion(text: string): void;
  /** Text the delegated backend produced (gpt-live). Preferred over the
   *  spoken transcript for the on-screen caption/detail, because the voice
   *  model may open with a filler ("let me take a look") that would
   *  otherwise become the headline. */
  appendBackendText(text: string): void;
  finishCompleted(): void;
  /** retryable: a setup failure (e.g. the photo item was rejected) — worth
   *  re-running the request on the fallback driver even if a few seconds of
   *  filler speech already reached the device. */
  fail(message: string, opts?: { retryable?: boolean }): void;
  armIdle(): void;
  /** Has any audio reached the device yet? (gates fallback vs. truncated) */
  hasAudio(): boolean;
  /** Extra key=value for the one-line completion log (e.g. upstream usage). */
  note(text: string): void;
}

interface LiveDriver {
  readonly name: string;
  /** Opens the upstream socket. null = could not connect (already logged). */
  connect(): Promise<WebSocket | null>;
  /** Called right after the socket is accepted. */
  onOpen(ws: WebSocket, ctx: LiveCtx): void;
  onMessage(ws: WebSocket, msg: Record<string, unknown>, ctx: LiveCtx): void;
  /** Upstream hung up before the shell finished. */
  onSocketClose?(ctx: LiveCtx): void;
  /** Drop any driver-owned timers (the shell is done with this driver). */
  stop?(): void;
}

// Workers open outbound WebSockets with an https URL + `Upgrade: websocket`
// (a wss:// URL is rejected by the Workers fetch()).
async function liveConnect(url: string, env: Env, label: string): Promise<WebSocket | null> {
  try {
    const upstream = await fetch(url, {
      headers: { Upgrade: "websocket", Authorization: `Bearer ${env.TOICAMERA_TTS_API_KEY}` },
    });
    const socket = upstream.webSocket;
    if (!socket) {
      console.error(`[toi] live: ${label} no websocket in upstream response`, upstream.status);
      await upstream.body?.cancel().catch(() => undefined);
      return null;
    }
    socket.accept();
    return socket;
  } catch (err) {
    console.error(`[toi] live: ${label} connect failed`, err);
    return null;
  }
}

// --- Realtime (gpt-realtime) — the #69 implementation, now a fallback ------
function realtimeLiveDriver(env: Env): LiveDriver {
  const model = env.REALTIME_MODEL || "gpt-realtime";
  return {
    name: "realtime",
    connect() {
      return liveConnect(
        `${realtimeBase(env)}/realtime?model=${encodeURIComponent(model)}`,
        env,
        "realtime",
      );
    },
    onOpen() {
      // Realtime speaks first: everything is sent on session.created.
    },
    onMessage(ws, msg, ctx) {
      const type = msg.type;
      if (type === "session.created") {
        ws.send(
          JSON.stringify({
            type: "session.update",
            session: {
              type: "realtime",
              output_modalities: ["audio"],
              instructions: LIVE_INSTRUCTIONS[ctx.lang][ctx.mode],
              audio: {
                // turn_detection: null — one shot, the Worker decides when
                // the turn ends (the audio is sent complete, in the request).
                input: {
                  format: { type: "audio/pcm", rate: LIVE_RATE },
                  turn_detection: null,
                  // ask only: transcribe the spoken question so the device
                  // can log "Q: …" (best effort; may not arrive for
                  // out-of-band input — then `question` stays empty). Kept
                  // off the capture path so an API rejection of this field
                  // could never take photo narration down with it.
                  ...(ctx.mode === "ask"
                    ? { transcription: { model: "gpt-4o-mini-transcribe" } }
                    : {}),
                },
                output: { voice: realtimeVoice(env), format: { type: "audio/pcm", rate: LIVE_RATE } },
              },
            },
          }),
        );
        const content: unknown[] = [{ type: "input_image", image_url: ctx.imageUrl }];
        if (ctx.audioB64) content.push({ type: "input_audio", audio: ctx.audioB64 });
        content.push({ type: "input_text", text: LIVE_USER_TEXT[ctx.lang][ctx.mode] });
        ws.send(
          JSON.stringify({
            type: "response.create",
            response: {
              conversation: "none",
              output_modalities: ["audio"],
              // Prior Q&A first, then this turn's photo (+ audio).
              input: [
                ...liveHistoryItems(ctx.history),
                { type: "message", role: "user", content },
              ],
            },
          }),
        );
      } else if (type === "response.output_audio.delta" || type === "response.audio.delta") {
        const delta = msg.delta;
        if (typeof delta !== "string" || !delta) return;
        let bytes: Uint8Array;
        try {
          bytes = base64ToBytes(delta);
        } catch (err) {
          console.error("[toi] live: bad audio delta", err);
          ctx.fail("realtime bad audio delta");
          return;
        }
        ctx.pushAudio(bytes);
      } else if (
        type === "response.output_audio_transcript.delta" ||
        type === "response.audio_transcript.delta"
      ) {
        const delta = msg.delta;
        if (typeof delta !== "string" || !delta) return;
        ctx.pushTranscript(delta);
      } else if (type === "conversation.item.input_audio_transcription.completed") {
        const t = msg.transcript;
        if (typeof t === "string" && t.trim()) ctx.setQuestion(t.trim());
      } else if (type === "response.done") {
        const status = (msg.response as { status?: unknown } | undefined)?.status;
        if (status !== "completed") {
          console.warn("[toi] live: response.done status", status, JSON.stringify(msg).slice(0, 300));
          ctx.fail(`realtime ${String(status)}`);
          return;
        }
        ctx.finishCompleted();
      } else if (type === "error" || type === "response.error") {
        console.error("[toi] live: error event", JSON.stringify(msg).slice(0, 300));
        ctx.fail("realtime error");
      }
    },
    onSocketClose(ctx) {
      console.error("[toi] live: socket closed before response.done");
      ctx.fail("realtime disconnected");
    },
  };
}

// --- GPT-Live-1 (voice) + Responses delegation (reasoning) -----------------
// GPT-Live's backend input history is capped at 32 KB per session, so the
// photo cannot travel as a data URL (a VGA JPEG is ~110 KB of base64). It is
// uploaded to the Files API instead and referenced by id — a few dozen bytes.
const LIVE_FILE_UPLOAD_TIMEOUT_MS = 8000;

async function uploadVisionFile(env: Env, jpeg: Uint8Array): Promise<string | null> {
  const t0 = Date.now();
  try {
    const form = new FormData();
    form.append("purpose", "vision");
    form.append("file", new File([jpeg], "photo.jpg", { type: "image/jpeg" }));
    const res = await fetch(`${liveBase(env)}/files`, {
      method: "POST",
      headers: { authorization: `Bearer ${env.TOICAMERA_TTS_API_KEY}` },
      body: form,
      signal: AbortSignal.timeout(LIVE_FILE_UPLOAD_TIMEOUT_MS),
    });
    if (!res.ok) {
      console.error("[toi] live: file upload failed", res.status, (await res.text()).slice(0, 300));
      return null;
    }
    const data = (await res.json()) as { id?: unknown };
    if (typeof data.id !== "string" || !data.id) {
      console.error("[toi] live: file upload returned no id");
      return null;
    }
    console.log(`[toi] live: photo uploaded as ${data.id} (${jpeg.length} B, ${Date.now() - t0} ms)`);
    return data.id;
  } catch (err) {
    console.error("[toi] live: file upload error", err);
    return null;
  }
}

async function deleteVisionFile(env: Env, id: string): Promise<void> {
  try {
    const res = await fetch(`${liveBase(env)}/files/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: { authorization: `Bearer ${env.TOICAMERA_TTS_API_KEY}` },
      signal: AbortSignal.timeout(LIVE_FILE_UPLOAD_TIMEOUT_MS),
    });
    console.log(`[toi] live: file ${id} ${res.ok ? "deleted" : `delete failed ${res.status}`}`);
  } catch (err) {
    console.warn("[toi] live: file delete error", err);
  }
}

function gptLiveDriver(env: Env): LiveDriver {
  const model = liveModel(env);
  const backend = liveBackendModel(env);
  const silenceMs = liveEndSilenceMs(env);
  let startTimer: ReturnType<typeof setTimeout> | undefined;
  let audioTimer: ReturnType<typeof setTimeout> | undefined;
  let endTimer: ReturnType<typeof setInterval> | undefined;
  let closeTimer: ReturnType<typeof setTimeout> | undefined;
  let started = false;
  let closing = false;
  // Delegations seen / completed so far. The answer cannot be over while the
  // backend is still thinking, and the voice model may pause for more than
  // the silence window between its acknowledgement and the real answer.
  let delegationsSeen = 0;
  let delegationsDone = 0;
  // When the last delegation finished: the voice model then needs time to
  // start reading the result, so silence right after completion must not end
  // the answer (that is exactly how "let me take a look…" got cut off).
  let lastDelegationDoneAt = 0;
  // Watchdog for a delegation that never reports completion: after this long
  // it is treated as finished and the normal silence rule takes over (the
  // 90 s hard limit would otherwise be the only way out).
  let delegationTimer: ReturnType<typeof setTimeout> | undefined;
  // Full-duplex: the server expects a live microphone. Once the recording (if
  // any) has been sent, keep feeding 100 ms of silence every 100 ms so the
  // user's turn ends and the voice model takes the floor for the real answer
  // (with the input simply stopping it only ever produced fillers).
  let silenceTimer: ReturnType<typeof setInterval> | undefined;
  const silenceB64 = bytesToBase64(new Uint8Array(LIVE_AUDIO_CHUNK_BYTES));
  let lastSpeechAt = 0;   // last output chunk that actually contained speech
  let droppedSilence = 0; // bytes of idle silence not forwarded to the device
  let lastOutputAt = 0;
  // Delegated Responses calls still running — the answer is not over while
  // the backend is still thinking, however quiet the voice channel is.
  const inflight = new Set<string>();
  const loggedTypes = new Set<string>();
  let questionBuf = "";

  const clearTimers = () => {
    if (startTimer) clearTimeout(startTimer);
    if (audioTimer) clearTimeout(audioTimer);
    if (endTimer) clearInterval(endTimer);
    if (closeTimer) clearTimeout(closeTimer);
    if (delegationTimer) clearTimeout(delegationTimer);
    if (silenceTimer) clearInterval(silenceTimer);
    startTimer = audioTimer = closeTimer = delegationTimer = undefined;
    endTimer = silenceTimer = undefined;
  };
  const startSilenceFeed = (ws: WebSocket) => {
    if (silenceTimer) return;
    silenceTimer = setInterval(() => {
      try {
        ws.send(JSON.stringify({ type: "session.input_audio.append", audio: silenceB64 }));
      } catch {
        // socket gone — the close/error handlers finish the request
      }
    }, 100);
  };
  const armDelegationWatchdog = () => {
    if (delegationTimer) clearTimeout(delegationTimer);
    delegationTimer = setTimeout(() => {
      delegationTimer = undefined;
      if (!inflight.size) return;
      console.warn(`[toi] live: gpt-live delegation watchdog — ${inflight.size} still open after ${LIVE_DELEGATION_TIMEOUT_MS} ms`);
      delegationsDone += inflight.size;
      inflight.clear();
      lastDelegationDoneAt = Date.now();
    }, LIVE_DELEGATION_TIMEOUT_MS);
  };

  // Graceful end: ask for session.close, log the usage it answers with, then
  // hand the terminal frame to the shell (never waiting on it for long).
  const beginClose = (ws: WebSocket, ctx: LiveCtx) => {
    if (closing) return;
    closing = true;
    if (droppedSilence) ctx.note(`silence_dropped=${droppedSilence}`);
    if (startTimer) clearTimeout(startTimer);
    if (audioTimer) clearTimeout(audioTimer);
    if (endTimer) clearInterval(endTimer);
    if (silenceTimer) clearInterval(silenceTimer);
    startTimer = audioTimer = undefined;
    endTimer = silenceTimer = undefined;
    try {
      ws.send(JSON.stringify({ type: "session.close" }));
    } catch {
      // socket already gone — the terminal frame still goes out below
    }
    closeTimer = setTimeout(() => {
      console.warn("[toi] live: gpt-live no session.closed within", LIVE_CLOSE_WAIT_MS, "ms");
      ctx.finishCompleted();
    }, LIVE_CLOSE_WAIT_MS);
  };

  const maybeEnd = (ws: WebSocket, ctx: LiveCtx) => {
    // Never end while a delegation is in flight (the watchdog bounds that).
    if (closing || !ctx.hasAudio() || inflight.size > 0) return;
    // If no delegation was ever observed, wait a longer window so an
    // acknowledgement followed by a delegated answer is not cut in two.
    const window = delegationsSeen > 0 ? silenceMs : Math.max(silenceMs, LIVE_END_SILENCE_NO_DELEGATION_MS);
    const now = Date.now();
    if (lastDelegationDoneAt && lastOutputAt < lastDelegationDoneAt) {
      // The backend answered but the voice has not started reading it yet:
      // keep waiting (bounded) instead of closing on the pre-answer silence.
      if (now - lastDelegationDoneAt < LIVE_POST_DELEGATION_WAIT_MS) return;
      console.warn("[toi] live: gpt-live no speech after delegation result — ending");
    }
    if (now - lastOutputAt < window) return;
    beginClose(ws, ctx);
  };

  const markOutput = (ws: WebSocket, ctx: LiveCtx) => {
    lastOutputAt = Date.now();
    if (!endTimer) endTimer = setInterval(() => maybeEnd(ws, ctx), 250);
  };

  // The photo (and what to do with it) goes to the delegated backend, not to
  // the voice model: gpt-live-1 does not look at images itself.
  const sendPhoto = (ws: WebSocket, ctx: LiveCtx) => {
    const item = {
      type: "message",
      role: "user",
      content: [
        ctx.imageFileId
          ? { type: "input_image", file_id: ctx.imageFileId }
          : { type: "input_image", image_url: ctx.imageUrl }, // mock/dev only: >32 KB is rejected upstream
        { type: "input_text", text: GPT_LIVE_BACKEND_TEXT[ctx.lang][ctx.mode] },
      ],
    };
    ws.send(JSON.stringify({ type: "response.item.create", event_id: "toi_photo", item }));
  };

  // Push-to-talk: the whole recording, then silence so the server's turn
  // detection sees the end of the user's turn.
  const sendAudio = (ws: WebSocket, ctx: LiveCtx) => {
    if (!ctx.pcm) return;
    const bytes = int16ToLeBytes(ctx.pcm);
    let sent = 0;
    for (let off = 0; off < bytes.length; off += LIVE_AUDIO_CHUNK_BYTES) {
      const chunk = bytes.subarray(off, Math.min(off + LIVE_AUDIO_CHUNK_BYTES, bytes.length));
      ws.send(JSON.stringify({ type: "session.input_audio.append", audio: bytesToBase64(chunk) }));
      sent += chunk.length;
    }
    const silence = new Uint8Array(LIVE_AUDIO_CHUNK_BYTES); // zeros = PCM16 silence
    const silenceChunks = Math.round((LIVE_TAIL_SILENCE_MS * LIVE_RATE * 2) / 1000 / LIVE_AUDIO_CHUNK_BYTES);
    const silenceB64 = bytesToBase64(silence);
    for (let i = 0; i < silenceChunks; i++) {
      ws.send(JSON.stringify({ type: "session.input_audio.append", audio: silenceB64 }));
    }
    console.log(
      `[toi] live: gpt-live sent ${sent} B pcm + ${silenceChunks * LIVE_AUDIO_CHUNK_BYTES} B silence`,
    );
  };

  return {
    name: "gpt-live",
    connect() {
      return liveConnect(`${liveBase(env)}/live/sessions`, env, "gpt-live");
    },
    onOpen(ws, ctx) {
      const session: Record<string, unknown> = {
        model,
        instructions: GPT_LIVE_VOICE_INSTRUCTIONS[ctx.lang],
        audio: {
          format: { type: "audio/pcm", rate: LIVE_RATE },
          output: { voice: liveVoice(env) },
        },
        delegation: {
          type: "responses",
          responses: {
            model: backend,
            instructions: GPT_LIVE_BACKEND_INSTRUCTIONS[ctx.lang],
            // Reasoning tokens count against max_output_tokens on gpt-5.6, so
            // keep the effort low by default and the budget generous.
            // "off" omits the field for backends without reasoning support.
            ...(env.LIVE_BACKEND_REASONING === "off"
              ? {}
              : { reasoning: { effort: env.LIVE_BACKEND_REASONING || "low" } }),
            max_output_tokens: 2000,
          },
        },
      };
      const history = liveHistoryItems(ctx.history);
      if (history.length) session.input = history;
      ws.send(JSON.stringify({ type: "session.start", event_id: "toi_start", session }));
      startTimer = setTimeout(() => {
        ctx.fail("gpt-live no session.started");
      }, LIVE_SESSION_START_TIMEOUT_MS);
    },
    onMessage(ws, msg, ctx) {
      const type = typeof msg.type === "string" ? msg.type : "";
      if (type === "session.started") {
        if (started) return;
        started = true;
        if (startTimer) clearTimeout(startTimer);
        startTimer = undefined;
        console.log("[toi] live: gpt-live session.started", JSON.stringify(msg).slice(0, 300));
        sendPhoto(ws, ctx);
        if (ctx.mode === "ask") sendAudio(ws, ctx);
        startSilenceFeed(ws);
        audioTimer = setTimeout(() => {
          ctx.fail("gpt-live no audio");
        }, LIVE_FIRST_AUDIO_TIMEOUT_MS);
      } else if (type === "session.output_audio.delta") {
        const delta = msg.delta;
        if (typeof delta !== "string" || !delta) return;
        let bytes: Uint8Array;
        try {
          bytes = base64ToBytes(delta);
        } catch (err) {
          console.error("[toi] live: gpt-live bad audio delta", err);
          ctx.fail("gpt-live bad audio delta");
          return;
        }
        const now = Date.now();
        const speech = pcm16Peak(bytes) >= LIVE_SPEECH_PEAK;
        if (speech) {
          lastSpeechAt = now;
        } else if (now - lastSpeechAt > LIVE_PAUSE_KEEP_MS) {
          droppedSilence += bytes.length; // idle silence: not audio, not activity
          return;
        }
        if (audioTimer) {
          clearTimeout(audioTimer);
          audioTimer = undefined;
        }
        ctx.pushAudio(bytes);
        if (speech) markOutput(ws, ctx);
      } else if (type === "session.output_transcript.delta") {
        const delta = msg.delta;
        if (typeof delta !== "string" || !delta) return;
        ctx.pushTranscript(delta);
        markOutput(ws, ctx);
      } else if (type === "session.input_transcript.delta") {
        const delta = msg.delta;
        if (typeof delta === "string") questionBuf += delta;
      } else if (type === "session.input_transcript.done") {
        const t = typeof msg.transcript === "string" ? msg.transcript : questionBuf;
        if (t.trim()) ctx.setQuestion(t.trim());
      } else if (type === "session.output_transcript.done" || type === "session.output_audio.done") {
        // Undocumented as of 2026-09-13, and if they exist they are probably
        // per-utterance — so they only count as output activity, never as
        // "the answer is over" (silence + delegation state decide that).
        markOutput(ws, ctx);
      } else if (type === "session.delegation.created") {
        // Documented start of a delegated backend call — mark it in flight
        // right away (the Responses lifecycle events follow under the same id).
        const d = isRecord(msg.delegation) ? msg.delegation : undefined;
        const id = typeof d?.id === "string" ? d.id : "delegation";
        if (!inflight.has(id)) {
          delegationsSeen++;
          inflight.add(id);
          armDelegationWatchdog();
        }
        console.log("[toi] live: gpt-live delegation created", id);
      } else if (type === "response.event") {
        // Delegated Responses stream. Only the lifecycle matters here: the
        // text itself comes back to the device as spoken audio.
        const inner = isRecord(msg.event) ? msg.event : undefined;
        const innerType = typeof inner?.type === "string" ? inner.type : "";
        const id = typeof msg.delegation_id === "string" ? msg.delegation_id : "delegation";
        if (innerType === "response.output_text.delta" && typeof inner?.delta === "string") {
          ctx.appendBackendText(inner.delta);
        }
        if (innerType === "response.created" || innerType === "response.in_progress") {
          if (!inflight.has(id)) {
            delegationsSeen++;
            inflight.add(id);
            armDelegationWatchdog();
          }
        } else if (
          innerType === "response.completed" ||
          innerType === "response.done" ||
          innerType === "response.failed" ||
          innerType === "response.incomplete"
        ) {
          if (inflight.delete(id)) {
            delegationsDone++;
            lastDelegationDoneAt = Date.now();
          }
          if (!inflight.size && delegationTimer) {
            clearTimeout(delegationTimer);
            delegationTimer = undefined;
          }
          if (innerType === "response.incomplete" || innerType === "response.failed") {
            console.warn("[toi] live: gpt-live backend", innerType, JSON.stringify(inner).slice(0, 300));
          }
        }
        if (!loggedTypes.has(`response.event:${innerType}`)) {
          loggedTypes.add(`response.event:${innerType}`);
          console.log("[toi] live: gpt-live response.event", innerType, `backend=${backend}`);
        }
      } else if (type === "session.usage.updated") {
        if (msg.usage !== undefined) ctx.note(`usage=${JSON.stringify(msg.usage)}`);
      } else if (type === "session.closed") {
        if (msg.usage !== undefined) ctx.note(`usage=${JSON.stringify(msg.usage)}`);
        console.log("[toi] live: gpt-live session.closed", JSON.stringify(msg).slice(0, 300));
        clearTimers();
        if (closing || ctx.hasAudio()) ctx.finishCompleted();
        else ctx.fail("gpt-live closed before audio");
      } else if (type === "error") {
        const clientEvent = typeof msg.client_event_id === "string" ? msg.client_event_id : "";
        console.error(
          `[toi] live: gpt-live error event${clientEvent ? ` (rejected ${clientEvent})` : ""}`,
          JSON.stringify(msg).slice(0, 400),
        );
        // A rejected photo/session is a setup failure: the answer never
        // started, so the Realtime driver should take over even after a
        // filler ("let me take a look") was already spoken.
        ctx.fail(clientEvent ? `gpt-live rejected ${clientEvent}` : "gpt-live error", {
          retryable: clientEvent === "toi_photo" || clientEvent === "toi_start",
        });
      } else if (type === "session.updated" || type === "session.input_audio.committed") {
        // Acknowledgements — nothing to do, the idle timer was already fed.
      } else if (!loggedTypes.has(type)) {
        // The API is days old: never drop an unknown event silently.
        loggedTypes.add(type);
        console.log("[toi] gpt-live event", type);
      }
    },
    onSocketClose(ctx) {
      clearTimers();
      if (closing || ctx.hasAudio()) {
        // We asked for the close, or we already have playable speech.
        if (closing) console.log("[toi] live: gpt-live socket closed after session.close");
        ctx.finishCompleted();
        return;
      }
      console.error("[toi] live: gpt-live socket closed before audio");
      ctx.fail("gpt-live disconnected");
    },
    stop: clearTimers,
  };
}

async function handleLive(request: Request, env: Env, exec: ExecutionContext): Promise<Response> {
  const mode = request.headers.get("x-live") as LiveMode | null;
  if (mode !== "capture" && mode !== "ask") {
    return json({ error: "X-Live must be capture or ask" }, 400);
  }
  const rawLength = request.headers.get("x-jpeg-length");
  const jpegLength = Number(rawLength);
  if (!rawLength || !Number.isInteger(jpegLength) || jpegLength < 1 || jpegLength > LIVE_MAX_JPEG_BYTES) {
    return json({ error: "X-Jpeg-Length missing or out of range" }, 400);
  }
  // Optional third body section: recent Q&A pairs as JSON, appended after the
  // JPEG (+ WAV) so the device never has to buffer a multipart request.
  const rawHistoryLength = request.headers.get("x-history-length");
  let historyLength = 0;
  if (rawHistoryLength !== null) {
    historyLength = Number(rawHistoryLength);
    if (
      !Number.isInteger(historyLength) ||
      historyLength < 0 ||
      historyLength > LIVE_MAX_HISTORY_BYTES
    ) {
      return json({ error: "X-History-Length out of range" }, 400);
    }
  }
  if (!env.TOICAMERA_TTS_API_KEY) {
    return json({ error: "realtime unavailable" }, 503);
  }
  // Bound the body before reading it (X-Jpeg-Length only bounds the JPEG).
  const maxBody = LIVE_MAX_JPEG_BYTES + LIVE_MAX_WAV_BYTES + LIVE_MAX_HISTORY_BYTES;
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > maxBody) {
    return json({ error: "body too large" }, 413);
  }
  const raw = new Uint8Array(await request.arrayBuffer());
  if (raw.length > maxBody) {
    return json({ error: "body too large" }, 413);
  }
  if (raw.length < historyLength) {
    return json({ error: "body shorter than X-History-Length" }, 400);
  }
  let history: LiveHistoryPair[] = [];
  if (historyLength > 0) {
    const parsed = parseLiveHistory(
      new TextDecoder().decode(raw.subarray(raw.length - historyLength)),
    );
    if (!parsed) return json({ error: "X-History-Length section is not [{q,a}] JSON" }, 400);
    history = parsed;
  }
  const body = raw.subarray(0, raw.length - historyLength);
  if (body.length < jpegLength) {
    return json({ error: "body shorter than X-Jpeg-Length" }, 400);
  }
  if (mode === "capture" && body.length !== jpegLength) {
    return json({ error: "capture body must be exactly the JPEG" }, 400); // framing slipped
  }
  const jpeg = body.subarray(0, jpegLength);
  if (jpeg[0] !== 0xff || jpeg[1] !== 0xd8) {
    return json({ error: "not a JPEG" }, 400);
  }

  let audioB64 = "";
  let pcm: Int16Array | null = null;
  if (mode === "ask") {
    const wav = body.subarray(jpegLength);
    if (wav.length < LIVE_MIN_WAV_BYTES) return json({ error: "audio too short" }, 400);
    if (wav.length > LIVE_MAX_WAV_BYTES) return json({ error: "audio too large" }, 413);
    pcm = wavToPcm24k(wav);
    if (!pcm) return json({ error: "unsupported wav (PCM 16-bit mono expected)" }, 400);
    audioB64 = bytesToBase64(int16ToLeBytes(pcm));
  }

  const lang = pickLang(request);
  const imageUrl = `data:image/jpeg;base64,${bytesToBase64(jpeg)}`;
  // gpt-live: the photo goes to the delegated backend by Files API id.
  // gpt-live needs the photo as a Files API id (32 KB history cap). The upload
  // runs in parallel with the WebSocket connect below; if it fails, the
  // request goes straight to the Realtime driver instead of paying for a
  // filler + rejected item + retry on the gpt-live path.
  const wantGptLive = liveEngine(env) !== "realtime" && Boolean(env.TOICAMERA_TTS_API_KEY);
  const mockUpstream = Boolean(env.LIVE_API_BASE_URL) && !liveBase(env).startsWith("https://api.openai.com");
  const uploadPromise: Promise<string | null> = wantGptLive ? uploadVisionFile(env, jpeg) : Promise.resolve(null);
  let imageFileId = "";
  let fileReleased = false;
  const releaseFile = () => {
    if (fileReleased || !imageFileId) return;
    fileReleased = true;
    exec.waitUntil(deleteVisionFile(env, imageFileId));
  };

  // Primary engine, then the Realtime driver as the in-request fallback. With
  // LIVE_ENGINE=realtime there is only ever the one driver (#69 behaviour).
  let drivers: LiveDriver[] = wantGptLive ? [gptLiveDriver(env), realtimeLiveDriver(env)] : [realtimeLiveDriver(env)];

  // Connect before the response starts so a dead upstream is still a plain
  // HTTP error (the device retries its old path), not a TOI1 stream with an X.
  let driverIndex = 0;
  let [socket, uploadedId] = await Promise.all([drivers[0].connect(), uploadPromise]);
  imageFileId = uploadedId ?? "";
  if (wantGptLive && !imageFileId && !mockUpstream) {
    // No file id → the photo item would be rejected upstream. Skip gpt-live.
    console.log("[toi] live: gpt-live skipped (photo upload failed) — using realtime");
    try {
      socket?.close();
    } catch {
      // ignore
    }
    drivers = [realtimeLiveDriver(env)];
    socket = await drivers[0].connect();
  } else if (!socket && drivers.length > 1) {
    console.log(
      `[toi] live: gpt-live failed before audio (connect failed) — falling back to realtime`,
    );
    driverIndex = 1;
    socket = await drivers[1].connect();
  }
  if (!socket) {
    releaseFile();
    return json({ error: `${drivers[driverIndex].name} connect failed` }, 502);
  }

  const encoder = new TextEncoder();
  const startedAt = Date.now();
  let transcript = "";
  let backendText = "";
  let question = ""; // ask: what the user said (upstream input transcription)
  let pcmBytes = 0;
  let firstAudioMs = -1;
  let capped = false;
  let settled = false;
  let notes: string[] = [];
  let generation = 0;
  let ws: WebSocket = socket;
  let driver: LiveDriver = drivers[driverIndex];
  let timer: ReturnType<typeof setTimeout> | undefined;
  let hardTimer: ReturnType<typeof setTimeout> | undefined;

  const readable = new ReadableStream<Uint8Array>({
    start(controller) {
      // The client can disconnect at any time; enqueueing then throws.
      const push = (chunk: Uint8Array) => {
        try {
          controller.enqueue(chunk);
        } catch {
          // stream already closed by the client
        }
      };
      const closeSocket = () => {
        try {
          ws.close();
        } catch {
          // already closing/closed
        }
      };
      const finish = (frame: Uint8Array) => {
        if (settled) return;
        settled = true;
        releaseFile();
        if (timer) clearTimeout(timer);
        if (hardTimer) clearTimeout(hardTimer);
        driver.stop?.();
        push(frame);
        try {
          controller.close();
        } catch {
          // already closed
        }
        closeSocket();
      };
      const endFrame = (status: "completed" | "truncated"): Uint8Array => {
        // Screen text comes from the backend's own answer when there is one;
        // the spoken transcript may start with a filler sentence.
        const { caption, detail } = splitCaption(backendText.trim() || transcript, lang);
        const ms = Date.now() - startedAt;
        const backend = driver.name === "gpt-live" ? liveBackendModel(env) : "-";
        console.log(
          `[toi] live: ${driver.name} ${mode} ${lang} ${status} ${pcmBytes} B pcm, ${ms} ms, first audio at ${firstAudioMs} ms, backend=${backend}, ${notes.join(" ") || "usage=-"}`,
        );
        // Answer quality is judged from the logs on device tests.
        console.log(
          `[toi] live: question=${JSON.stringify(question)} transcript=${JSON.stringify(transcript.slice(0, 120))}`,
        );
        return liveFrame(
          "E",
          encoder.encode(JSON.stringify({ caption, detail, transcript, question, status, pcmBytes, ms })),
        );
      };
      const armIdle = () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
          console.error("[toi] live: idle timeout waiting for upstream");
          ctx.fail(`${driver.name} timeout`);
        }, LIVE_IDLE_TIMEOUT_MS);
      };

      // Swap to the Realtime driver mid-stream. The device is already reading
      // TOI1 and has heard nothing yet, so it sees one continuous response.
      const fallbackToRealtime = async (reason: string) => {
        console.log(`[toi] live: gpt-live failed ${pcmBytes > 0 ? "after filler" : "before audio"} (${reason}) — falling back to realtime`);
        generation++;
        driver.stop?.();
        closeSocket();
        // Nothing was played, but transcript deltas may already be on the
        // wire; the E frame carries the authoritative text either way.
        transcript = "";
        backendText = "";
        question = "";
        notes = [];
        firstAudioMs = -1; // measure the fallback driver's own first speech
        capped = false;
        driverIndex = 1;
        const next = drivers[1];
        const sock = await next.connect();
        if (settled) {
          try {
            sock?.close();
          } catch {
            // already closing/closed
          }
          return;
        }
        if (!sock) {
          finish(liveFrame("X", encoder.encode(JSON.stringify({ error: "realtime connect failed" }))));
          return;
        }
        driver = next;
        ws = sock;
        bind(sock, generation);
        armIdle();
        next.onOpen(sock, ctx);
      };

      const ctx: LiveCtx = {
        mode,
        lang,
        imageUrl,
        imageFileId,
        audioB64,
        pcm,
        history,
        pushAudio(bytes) {
          if (settled || !bytes.length) return;
          if (firstAudioMs < 0) firstAudioMs = Date.now() - startedAt;
          if (pcmBytes + bytes.length > LIVE_MAX_PCM_BYTES) {
            // Keep the session running to the terminal frame, just stop
            // forwarding audio the device has no room for.
            if (!capped) {
              capped = true;
              console.warn("[toi] live: hit max PCM size, dropping further audio");
            }
            return;
          }
          pcmBytes += bytes.length;
          push(liveFrame("A", bytes));
        },
        pushTranscript(text) {
          if (settled || !text) return;
          transcript += text;
          push(liveFrame("T", encoder.encode(text)));
        },
        appendBackendText(text) {
          if (settled || !text) return;
          backendText += text;
        },
        setQuestion(text) {
          if (text) question = text;
        },
        finishCompleted() {
          if (settled) return;
          finish(endFrame(capped ? "truncated" : "completed"));
        },
        // Before any audio: X → the device falls back to the old path (or, for
        // gpt-live, the Realtime driver takes over first). After audio
        // started: E(truncated) → the device keeps what it already played
        // instead of narrating the same photo twice.
        fail(message, opts) {
          if (settled) return;
          const canFallback = driverIndex === 0 && drivers.length > 1;
          if (pcmBytes > 0 && !(opts?.retryable && canFallback)) {
            console.warn("[toi] live: ending as truncated —", message);
            finish(endFrame("truncated"));
            return;
          }
          if (canFallback) {
            if (pcmBytes > 0) console.warn(`[toi] live: retrying on realtime after ${pcmBytes} B of audio (${message})`);
            void fallbackToRealtime(message);
            return;
          }
          finish(liveFrame("X", encoder.encode(JSON.stringify({ error: message }))));
        },
        armIdle,
        hasAudio: () => pcmBytes > 0,
        note(text) {
          notes.push(text);
        },
      };

      const bind = (sock: WebSocket, gen: number) => {
        sock.addEventListener("message", (event: MessageEvent) => {
          if (settled || gen !== generation || typeof event.data !== "string") return;
          armIdle();
          let msg: Record<string, unknown>;
          try {
            msg = JSON.parse(event.data);
          } catch {
            return;
          }
          driver.onMessage(sock, msg, ctx);
        });
        sock.addEventListener("close", () => {
          if (settled || gen !== generation) return;
          if (driver.onSocketClose) driver.onSocketClose(ctx);
          else ctx.fail(`${driver.name} disconnected`);
        });
        sock.addEventListener("error", (event: ErrorEvent) => {
          // our own close() after finish() also lands here
          if (settled || gen !== generation) return;
          console.error("[toi] live: socket error", event.message || event);
          ctx.fail(`${driver.name} socket error`);
        });
      };

      push(encoder.encode(LIVE_MAGIC));
      armIdle();
      hardTimer = setTimeout(() => {
        console.error("[toi] live: hard timeout");
        // Past the point of falling back: whatever we have is the answer.
        if (pcmBytes > 0) finish(endFrame("truncated"));
        else finish(liveFrame("X", encoder.encode(JSON.stringify({ error: "live timeout" }))));
      }, LIVE_MAX_TOTAL_MS);

      bind(ws, generation);
      driver.onOpen(ws, ctx);
    },
    cancel() {
      // Device hung up (fallback path, power off): stop the upstream session.
      settled = true;
      releaseFile();
      if (timer) clearTimeout(timer);
      if (hardTimer) clearTimeout(hardTimer);
      driver.stop?.();
      try {
        ws.close();
      } catch {
        // already closing/closed
      }
    },
  });

  return new Response(readable, {
    headers: {
      "content-type": "application/octet-stream",
      "x-voice-engine": "realtime-live",
      "cache-control": "no-store",
    },
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, model: configuredModels(env)[0] });
    }

    // Refuse to serve until DEVICE_TOKEN is set — an empty/missing secret must
    // not let an empty X-Device-Token header through.
    if (!env.DEVICE_TOKEN) {
      return json({ error: "server not configured" }, 500);
    }
    if (request.headers.get("x-device-token") !== env.DEVICE_TOKEN) {
      return json({ error: "unauthorized" }, 401);
    }
    const expectedMethod =
        url.pathname === "/place" || url.pathname === "/config" ? "GET" : "POST";
    if (request.method !== expectedMethod) {
      return json({ error: "method not allowed" }, 405);
    }

    try {
      switch (url.pathname) {
        case "/config":
          // Device-facing menu: which models this Worker offers and which
          // TTS voice it speaks with. The firmware caches this in NVS.
          return json({
            models: configuredModels(env),
            voice: env.TTS_VOICE,
            tts: true,
            realtime: realtimeAvailable(env),
            realtimeVoice: realtimeAvailable(env) ? realtimeVoice(env) : "",
          });
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
        case "/live":
          return await handleLive(request, env, ctx);
        case "/kana":
          return await handleKana(request, env);
        default:
          return json({ error: "not found" }, 404);
      }
    } catch (err) {
      console.error("unhandled error", err);
      return json({ error: "internal error" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;

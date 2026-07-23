// ToiCamera — Stopwatch host firmware
//
// Yellow button (KEYA/G2): capture -> show photo -> AI explanation (text + TTS)
// Blue button   (KEYB/G1): replay last TTS audio
// Touch drag             : scroll explanation text
//
// State machine: BOOT -> WIFI_CONNECTING -> IDLE -> CAPTURING -> SHOW_PHOTO
//                -> ANALYZING -> SPEAKING/RESULT -> IDLE  (ERROR: KEYA retries)

#include <M5Unified.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

#ifndef WIFI_SSID1
#error "Build with secrets.ini (see secrets.ini.example)"
#endif
#ifndef CAM_BASE
#error "CAM_BASE missing — update secrets.ini from secrets.ini.example"
#endif

enum class AppState {
  Boot,
  WifiConnecting,
  Idle,
  Capturing,
  Analyzing,
  FetchingAudio,
  Result,
  Error,
};

static AppState state = AppState::Boot;

// Buffers live in PSRAM (8MB). Freed on each new capture cycle.
static uint8_t *jpegBuf = nullptr;
static size_t jpegLen = 0;
static uint8_t *wavBuf = nullptr;
static size_t wavLen = 0;

static String caption;
static String detailText;
static String lastError;

static M5Canvas textCanvas(&M5.Display);
static int scrollY = 0;
static int textCanvasHeight = 0;
static uint32_t autoScrollAt = 0;

static constexpr size_t kMaxJpeg = 2 * 1024 * 1024;
static constexpr size_t kMaxWav = 4 * 1024 * 1024;
static constexpr int kTextWidth = 320;  // inscribed square of the 466px round AMOLED

// ---------------------------------------------------------------- UI helpers

static void showStatus(const char *msg, uint32_t color = TFT_WHITE) {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setFont(&fonts::efontJA_16);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(color, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.drawString(msg, M5.Display.width() / 2, M5.Display.height() / 2);
}

static void showIdle() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setFont(&fonts::efontJA_16);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setTextSize(2);
  M5.Display.drawString("AI Camera", M5.Display.width() / 2, 180);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
  M5.Display.drawString("黄ボタンで撮影", M5.Display.width() / 2, 260);
}

static void drawPhoto() {
  if (!jpegBuf) return;
  M5.Display.fillScreen(TFT_BLACK);
  // Scale-to-fit; CamS3 sends SVGA (800x600) by default. Datum keeps it centered.
  M5.Display.drawJpg(jpegBuf, jpegLen, 0, 0, M5.Display.width(),
                     M5.Display.height(), 0, 0, 0.0f, 0.0f,
                     datum_t::middle_center);
}

// Word-wrap UTF-8 text into the canvas, minimal kinsoku (no line-leading 、。」).
static void appendWrapped(M5Canvas &c, const String &utf8, int32_t &y,
                          int lineHeight) {
  String line;
  size_t i = 0;
  while (i < utf8.length()) {
    uint8_t b = utf8[i];
    size_t charLen = (b < 0x80) ? 1 : (b < 0xE0) ? 2 : (b < 0xF0) ? 3 : 4;
    String ch = utf8.substring(i, i + charLen);
    i += charLen;
    if (ch == "\n") {
      c.drawString(line, 0, y);
      y += lineHeight;
      line = "";
      continue;
    }
    if (c.textWidth(line + ch) > kTextWidth &&
        !(ch == "、" || ch == "。" || ch == "」" || ch == ")")) {
      c.drawString(line, 0, y);
      y += lineHeight;
      line = "";
    }
    line += ch;
  }
  if (line.length()) {
    c.drawString(line, 0, y);
    y += lineHeight;
  }
}

static void buildResultCanvas() {
  textCanvas.setColorDepth(8);
  textCanvas.createSprite(kTextWidth, 1400);
  textCanvas.fillSprite(TFT_BLACK);
  textCanvas.setFont(&fonts::efontJA_16);

  int32_t y = 0;
  textCanvas.setTextSize(2);
  textCanvas.setTextColor(TFT_YELLOW, TFT_BLACK);
  appendWrapped(textCanvas, caption, y, 40);
  y += 12;
  textCanvas.setTextSize(2);
  textCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
  appendWrapped(textCanvas, detailText, y, 38);
  textCanvasHeight = y;
  scrollY = 0;
}

static void drawResult() {
  M5.Display.fillScreen(TFT_BLACK);
  const int x = (M5.Display.width() - kTextWidth) / 2;
  const int viewTop = 90;
  const int viewH = M5.Display.height() - viewTop - 60;
  M5.Display.setClipRect(x, viewTop, kTextWidth, viewH);
  textCanvas.pushSprite(x, viewTop - scrollY);
  M5.Display.clearClipRect();
}

// ------------------------------------------------------------- network layer

static bool connectWifi() {
  struct { const char *ssid, *pass; } slots[] = {
      {WIFI_SSID1, WIFI_PASS1}, {WIFI_SSID2, WIFI_PASS2}};
  for (auto &s : slots) {
    if (!strlen(s.ssid)) continue;
    WiFi.begin(s.ssid, s.pass);
    for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; ++i) {
      delay(500);
      M5.update();
    }
    if (WiFi.status() == WL_CONNECTED) return true;
    WiFi.disconnect();
  }
  return false;
}

// Read an HTTP response body into a PSRAM buffer. Returns nullptr on failure.
static uint8_t *readBody(HTTPClient &http, size_t maxLen, size_t &outLen) {
  const int contentLen = http.getSize();
  WiFiClient *stream = http.getStreamPtr();
  size_t cap = (contentLen > 0) ? (size_t)contentLen : (256 * 1024);
  if (cap > maxLen) return nullptr;
  uint8_t *buf = (uint8_t *)ps_malloc(cap);
  if (!buf) return nullptr;

  size_t got = 0;
  uint32_t lastData = millis();
  while (http.connected() && (contentLen < 0 || got < (size_t)contentLen)) {
    size_t avail = stream->available();
    if (avail) {
      if (got + avail > cap) {
        if (contentLen > 0 || cap >= maxLen) break;  // overflow
        size_t newCap = min(cap * 2, maxLen);
        uint8_t *grown = (uint8_t *)ps_realloc(buf, newCap);
        if (!grown) break;
        buf = grown;
        cap = newCap;
      }
      got += stream->readBytes(buf + got, min(avail, cap - got));
      lastData = millis();
    } else if (millis() - lastData > 10000) {
      break;  // stalled
    } else {
      delay(5);
    }
  }
  if (got == 0 || (contentLen > 0 && got != (size_t)contentLen)) {
    free(buf);
    return nullptr;
  }
  outLen = got;
  return buf;
}

// Fire a short GET against the CamS3 REST API; result body is ignored.
static bool camGet(const String &pathAndQuery, uint16_t timeoutMs = 3000) {
  HTTPClient http;
  http.setTimeout(timeoutMs);
  if (!http.begin(String(CAM_BASE) + pathAndQuery)) return false;
  const int code = http.GET();
  http.end();
  return code == HTTP_CODE_OK;
}

// Factory firmware boots with awb/aec/agc all OFF -> near-black images
// (vlogCamera hardware-verification, 2026-06-02). Enable auto exposure and
// pick SVGA/q12 for fast transfer. Best-effort: failures are non-fatal.
static void configureCamera() {
  static const char *kInit[] = {
      "/api/v1/control?var=awb&val=1",  "/api/v1/control?var=awb_gain&val=1",
      "/api/v1/control?var=aec&val=1",  "/api/v1/control?var=agc&val=1",
      "/api/v1/control?var=gainceiling&val=2",
      "/api/v1/control?var=framesize&val=9",  // SVGA 800x600
      "/api/v1/control?var=quality&val=12",
  };
  for (auto p : kInit) camGet(p);
}

static bool captureFromCam() {
  free(jpegBuf);
  jpegBuf = nullptr;
  jpegLen = 0;

  camGet("/api/v1/led_on", 500);
  HTTPClient http;
  http.setTimeout(8000);
  if (!http.begin(String(CAM_BASE) + "/api/v1/capture")) return false;
  const int code = http.GET();
  if (code == HTTP_CODE_OK) {
    jpegBuf = readBody(http, kMaxJpeg, jpegLen);
  } else {
    lastError = "camera HTTP " + String(code);
  }
  http.end();
  camGet("/api/v1/led_off", 500);
  return jpegBuf != nullptr;
}

static bool analyzePhoto() {
  WiFiClientSecure client;
  client.setInsecure();  // own Worker only; documented trade-off in README
  HTTPClient http;
  http.setTimeout(30000);
  if (!http.begin(client, String(WORKER_URL) + "/analyze")) return false;
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  const int code = http.POST(jpegBuf, jpegLen);
  bool ok = false;
  if (code == HTTP_CODE_OK) {
    JsonDocument doc;
    if (deserializeJson(doc, http.getString()) == DeserializationError::Ok) {
      caption = doc["caption"].as<String>();
      detailText = doc["detail"].as<String>();
      ok = caption.length() > 0;
    }
  } else {
    lastError = "analyze HTTP " + String(code);
  }
  http.end();
  return ok;
}

static bool fetchTts() {
  free(wavBuf);
  wavBuf = nullptr;
  wavLen = 0;

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  http.setTimeout(30000);
  if (!http.begin(client, String(WORKER_URL) + "/tts")) return false;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);

  JsonDocument doc;
  doc["text"] = caption + "。" + detailText;
  String body;
  serializeJson(doc, body);

  const int code = http.POST(body);
  if (code == HTTP_CODE_OK) {
    wavBuf = readBody(http, kMaxWav, wavLen);
  } else {
    lastError = "tts HTTP " + String(code);
  }
  http.end();
  return wavBuf != nullptr;
}

// ------------------------------------------------------------------ lifecycle

static void enterError(const String &msg) {
  lastError = msg;
  state = AppState::Error;
  showStatus(("エラー: " + msg).c_str(), TFT_RED);
  M5.Display.setTextSize(1);
  M5.Display.drawString("黄ボタンで再試行", M5.Display.width() / 2, 320);
}

static void runCaptureCycle() {
  state = AppState::Capturing;
  M5.Speaker.tone(2000, 60);  // shutter feedback

  showStatus("撮影中...");
  if (!captureFromCam()) {
    enterError(lastError.length() ? lastError : "カメラに接続できません");
    return;
  }
  drawPhoto();

  state = AppState::Analyzing;
  M5.Display.setFont(&fonts::efontJA_16);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.drawString("AIが考えています...", M5.Display.width() / 2, 420);
  if (!analyzePhoto()) {
    enterError(lastError.length() ? lastError : "解析に失敗しました");
    return;
  }

  buildResultCanvas();
  drawResult();
  state = AppState::FetchingAudio;
  if (fetchTts()) {
    M5.Speaker.playWav(wavBuf, wavLen);
  }
  // Audio failure is non-fatal — text result is already on screen.
  autoScrollAt = millis() + 2500;
  state = AppState::Result;
}

void setup() {
  auto cfg = M5.config();
  cfg.output_power = true;  // Grove 5V out — powers the CamS3
  M5.begin(cfg);
  M5.Power.setExtOutput(true);  // PMIC-gated 5V bus: enable explicitly
  M5.Speaker.setVolume(180);
  M5.Display.setBrightness(200);

  showStatus("WiFi接続中...");
  state = AppState::WifiConnecting;
  if (!connectWifi()) {
    enterError("WiFiに接続できません");
    return;
  }
  configureCamera();  // black-image fix + SVGA; harmless if camera is offline
  showIdle();
  state = AppState::Idle;
}

void loop() {
  M5.update();

  switch (state) {
    case AppState::Idle:
      if (M5.BtnA.wasPressed()) runCaptureCycle();
      break;

    case AppState::Result: {
      if (M5.BtnA.wasPressed()) {
        runCaptureCycle();
        break;
      }
      if (M5.BtnB.wasPressed() && wavBuf) {
        M5.Speaker.playWav(wavBuf, wavLen);
      }
      // Touch drag scroll
      auto t = M5.Touch.getDetail();
      const int viewH = M5.Display.height() - 150;
      const int maxScroll = max(0, textCanvasHeight - viewH);
      if (t.isPressed() && t.deltaY() != 0) {
        scrollY = constrain(scrollY - t.deltaY(), 0, maxScroll);
        drawResult();
        autoScrollAt = 0;  // manual scroll cancels auto-scroll
      } else if (autoScrollAt && millis() > autoScrollAt &&
                 scrollY < maxScroll) {
        scrollY = min(scrollY + 1, maxScroll);
        drawResult();
        autoScrollAt = millis() + 40;
      }
      break;
    }

    case AppState::Error:
      if (M5.BtnA.wasPressed()) {
        if (WiFi.status() != WL_CONNECTED) {
          showStatus("WiFi接続中...");
          if (!connectWifi()) {
            enterError("WiFiに接続できません");
            break;
          }
        }
        runCaptureCycle();
      }
      break;

    default:
      break;
  }
  delay(5);
}

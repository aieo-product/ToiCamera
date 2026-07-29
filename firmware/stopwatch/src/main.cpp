// ToiCamera — Stopwatch host firmware
//
// Yellow button (KEYA/G2): capture -> show photo -> AI explanation
// Blue button   (KEYB/G1): back to the live finder (result/error), re-pair (idle)
// Speech: on-device "animalese" (per-character chirps with intonation) — no TTS
// Touch drag             : scroll explanation text
// Idle screen            : live viewfinder (continuous VGA preview)
//
// Networking: the Stopwatch runs SoftAP + STA simultaneously. The CamS3 joins
// the Stopwatch's own AP (no home router / PC involved on the camera path);
// the STA side reaches the cloud Worker via home WiFi or a phone hotspot.
//
//   CamS3 --(WiFi: SoftAP "ToiCamera")--> Stopwatch --(WiFi: LAN)--> Worker

#include <M5Unified.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <TinyGPSPlus.h>

#ifndef WIFI_SSID1
#error "Build with secrets.ini (see secrets.ini.example)"
#endif
// Closed device-to-device network the camera connects to.
#ifndef TOI_AP_SSID
#define TOI_AP_SSID "ToiCamera"
#endif
#ifndef TOI_AP_PASS
#define TOI_AP_PASS "toi-cam-2026"
#endif

enum class AppState {
  Boot,
  WifiConnecting,
  Idle,
  Capturing,
  Analyzing,
  Result,
  Error,
};

static AppState state = AppState::Boot;

// Buffers live in PSRAM (8MB). Freed on each new capture cycle.
static uint8_t *jpegBuf = nullptr;
static size_t jpegLen = 0;

static String caption;
static String detailText;
static String lastError;
static String camBase;  // e.g. "http://192.168.4.2" — discovered on the SoftAP

static M5Canvas textCanvas(&M5.Display);
static int scrollY = 0;
static int textCanvasHeight = 0;
static uint32_t autoScrollAt = 0;

static TinyGPSPlus gps;
static uint32_t gpsBytes = 0;
static bool gpsPinsSwapped = false;
static uint32_t gpsSwapDeadline = 0;
static uint32_t gpsLastLogAt = 0;

static TaskHandle_t animTask = nullptr;
static volatile bool animStopFlag = false;
static String animText;

static bool gNetOk = false;
static bool gCamOk = false;
static uint32_t lastPreviewAt = 0;
static int previewFails = 0;

static uint8_t *retainBuf = nullptr;   // last complete finder frame (owned)
static size_t retainLen = 0, retainCap = 0;
static uint32_t retainAt = 0;
static constexpr size_t kMaxJpeg = 2 * 1024 * 1024;
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

static void showIdleWithWarnings(bool netOk, bool camOk) {
  showIdle();
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_ORANGE, TFT_BLACK);
  if (!netOk) {
    M5.Display.drawString("ネット未接続(解析不可)", M5.Display.width() / 2, 310);
  }
  if (!camOk) {
    M5.Display.drawString("カメラ未検出 青ボタンで再接続", M5.Display.width() / 2, 340);
  }
}

// Small pill at the top of the round screen showing what we're waiting on.
static void drawBusy(const char *label, uint32_t color) {
  const int w = 200, h = 32, x = (M5.Display.width() - w) / 2, y = 26;
  M5.Display.fillRoundRect(x, y, w, h, 16, TFT_BLACK);
  M5.Display.drawRoundRect(x, y, w, h, 16, color);
  M5.Display.setFont(&fonts::efontJA_16);
  M5.Display.setTextSize(1);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setTextColor(color, TFT_BLACK);
  M5.Display.drawString(label, M5.Display.width() / 2, y + h / 2 + 1);
}

// ------------------------------------------------------------- sound effects

static void sfxShutter() {
  M5.Speaker.tone(1500, 22);
  delay(24);
  M5.Speaker.tone(880, 42);
}

static void sfxCancel() {
  M5.Speaker.tone(620, 36);
  delay(40);
  M5.Speaker.tone(470, 50);
}

static void sfxError() {
  M5.Speaker.tone(300, 120);
}

// --------------------------------------------------- animalese speech engine
// Animal-Crossing-style gibberish: one short chirp per character, pitch driven
// by a per-character hash plus sentence-level intonation (drift down, reset at
// sentence ends, rise on question marks). Runs in its own task so the UI stays
// responsive; text is shown on screen for the actual content.

static void stopAnimalese() {
  if (animTask) {
    animStopFlag = true;
    M5.Speaker.stop();
    for (int i = 0; i < 20 && animTask; ++i) delay(10);
  }
  M5.Speaker.stop();
}

static void animaleseWorker(void *) {
  const String t = animText;
  const float base = 660.0f + (esp_random() % 120);
  float pitch = base;
  size_t i = 0;
  while (i < t.length() && !animStopFlag) {
    const uint8_t b = t[i];
    const size_t cl = (b < 0x80) ? 1 : (b < 0xE0) ? 2 : (b < 0xF0) ? 3 : 4;
    const String ch = t.substring(i, i + cl);
    i += cl;
    if (ch == "。" || ch == "!" || ch == "！" || ch == "\n") {
      pitch = base;
      vTaskDelay(pdMS_TO_TICKS(240));
      continue;
    }
    if (ch == "?" || ch == "？") {
      M5.Speaker.tone(pitch * 1.35f, 110);  // rising question chirp
      vTaskDelay(pdMS_TO_TICKS(300));
      pitch = base;
      continue;
    }
    if (ch == "、" || ch == "," || ch == " " || ch == "　" || ch == "…") {
      vTaskDelay(pdMS_TO_TICKS(130));
      continue;
    }
    uint32_t h = 0;
    for (size_t k = 0; k < ch.length(); ++k) h = h * 131 + (uint8_t)ch[k];
    const float f = pitch * (0.82f + (h % 45) / 100.0f);
    M5.Speaker.tone(f, 46);
    pitch *= 0.994f;  // gentle downdrift across the sentence
    vTaskDelay(pdMS_TO_TICKS(56 + (h % 24)));
  }
  M5.Speaker.stop();
  animTask = nullptr;
  vTaskDelete(nullptr);
}

static void speakAnimalese(const String &text) {
  stopAnimalese();
  animText = text;
  animStopFlag = false;
  xTaskCreatePinnedToCore(animaleseWorker, "animalese", 4096, nullptr, 1,
                          &animTask, 0);
}

static void drawPhoto() {
  if (!jpegBuf) return;
  M5.Display.fillScreen(TFT_BLACK);
  // HVGA 480x320 at 1:1, centered — same framing the finder showed.
  M5.Display.drawJpg(jpegBuf, jpegLen, (M5.Display.width() - 480) / 2,
                     (M5.Display.height() - 320) / 2);
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

static void drawResult(bool full = false) {
  if (full) M5.Display.fillScreen(TFT_BLACK);
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

// Bring up the Stopwatch's own AP for the camera. Stock defaults
// (192.168.4.1/24) keep the built-in DHCP server in its known-good config —
// overriding the subnet after softAP() left DHCP serving the wrong pool.
// No collision with the camera's factory AP: the two networks never exist
// at the same time on this radio (our AP is torn down while pairing).
static void startSoftAp() {
  WiFi.softAP(TOI_AP_SSID, TOI_AP_PASS);
  Serial.printf("[toi] softAP up ip=%s ch=%d\n",
                WiFi.softAPIP().toString().c_str(), WiFi.channel());
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
    } else if (millis() - lastData > 4000) {
      break;  // stalled
    } else {
      delay(1);
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
  if (camBase.isEmpty()) return false;
  HTTPClient http;
  http.setTimeout(timeoutMs);
  if (!http.begin(camBase + pathAndQuery)) return false;
  const int code = http.GET();
  http.end();
  return code == HTTP_CODE_OK;
}

// TCP-level port probe: fast-false = connection refused (host alive, no
// server), slow-false = timeout (no host at that IP).
static void diagCameraNet() {
  const IPAddress ap = WiFi.softAPIP();
  for (int host = 2; host <= 6; ++host) {
    IPAddress ip(ap[0], ap[1], ap[2], host);
    for (uint16_t port : {80, 81}) {
      WiFiClient c;
      const uint32_t t0 = millis();
      const bool r = c.connect(ip, port, 1500);
      Serial.printf("[toi] diag %s:%u -> %s (%lums)\n", ip.toString().c_str(),
                    port, r ? "OPEN" : "closed", millis() - t0);
      c.stop();
    }
  }
}

// Find the camera among the SoftAP DHCP clients (first leases start at .2).
static bool cameraReachable() {
  if (!camBase.isEmpty() && camGet("/api/v1/get_mac", 2000)) return true;
  const IPAddress ap = WiFi.softAPIP();
  const String net = String(ap[0]) + "." + ap[1] + "." + ap[2] + ".";
  for (int host = 2; host <= 12; ++host) {
    camBase = "http://" + net + host;
    if (camGet("/api/v1/get_mac", 1500)) {
      Serial.printf("[toi] camera found at %s (stations=%d)\n", camBase.c_str(),
                    WiFi.softAPgetStationNum());
      return true;
    }
  }
  Serial.printf("[toi] camera not found on %s0/24 (stations=%d)\n", net.c_str(),
                WiFi.softAPgetStationNum());
  if (WiFi.softAPgetStationNum() > 0) diagCameraNet();
  camBase = "";
  return false;
}

// Cut and restore Grove 5V — power-cycles the CamS3 (it has no battery).
static void powerCycleCamera() {
  M5.Power.setExtOutput(false);
  delay(1500);
  M5.Power.setExtOutput(true);
}

// One-time camera provisioning, no PC/phone/router involved: join the camera's
// factory AP (UnitCamS3-WiFi), point it at OUR SoftAP via set_config, then
// power-cycle it so it reboots as a client of the Stopwatch.
static bool pairCamera() {
  showStatus("カメラをペアリング中...");
  Serial.println("[toi] pair: power-cycle camera (watch its LED: should blink off)");
  powerCycleCamera();
  delay(8000);  // let the camera finish booting its AP

  // Drop our AP+STA while we briefly become a client of the camera. Scanning
  // in AP_STA mode is unreliable, so just try to join the factory AP blind.
  WiFi.softAPdisconnect(true);
  WiFi.disconnect(true);
  delay(300);
  WiFi.mode(WIFI_STA);
  bool joined = false;
  for (int attempt = 0; attempt < 3 && !joined; ++attempt) {
    WiFi.begin("UnitCamS3-WiFi");  // open AP
    for (int i = 0; i < 24 && WiFi.status() != WL_CONNECTED; ++i) delay(500);
    joined = WiFi.status() == WL_CONNECTED;
    Serial.printf("[toi] pair: join UnitCamS3-WiFi attempt %d -> %s\n", attempt + 1,
                  joined ? WiFi.localIP().toString().c_str() : "FAIL");
    if (!joined) {
      WiFi.disconnect(true);
      delay(2000);
    }
  }
  bool ok = false;
  {
    if (joined) {
      JsonDocument doc;
      doc["wifiSsid"] = TOI_AP_SSID;  // camera's "home WiFi" = our SoftAP
      doc["wifiPass"] = TOI_AP_PASS;
      doc["startPoster"] = "no";  // custom FW: ssid set + poster off -> STA server
      doc["postInterval"] = 5;
      doc["nickname"] = "ToiCamera";
      doc["timeZone"] = "GMT+9";
      String body;
      serializeJson(doc, body);
      HTTPClient http;
      http.setTimeout(5000);
      if (http.begin("http://192.168.4.1/api/v1/set_config")) {
        http.addHeader("Content-Type", "application/json");
        const int code = http.POST(body);
        ok = code == HTTP_CODE_OK;
        Serial.printf("[toi] pair: set_config -> HTTP %d\n", code);
        http.end();
      }
      // Read back what the camera actually persisted (diagnostic).
      HTTPClient chk;
      chk.setTimeout(4000);
      if (chk.begin("http://192.168.4.1/api/v1/get_config")) {
        if (chk.GET() == HTTP_CODE_OK) {
          Serial.printf("[toi] pair: get_config = %s\n", chk.getString().c_str());
        }
        chk.end();
      }
    }
    WiFi.disconnect(true);
  }

  // Restore our normal radio setup regardless of the outcome.
  WiFi.mode(WIFI_AP_STA);
  showStatus("WiFi再接続中...");
  connectWifi();
  startSoftAp();
  powerCycleCamera();  // camera reboots and should join our SoftAP
  showStatus(ok ? "カメラの接続を待っています..." : "カメラを探しています...");
  if (ok) {
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_ORANGE, TFT_BLACK);
    M5.Display.drawString("LEDが消えなければGroveを抜き差し",
                          M5.Display.width() / 2, 340);
  }
  for (int i = 0; i < 24; ++i) {
    delay(2500);
    if (cameraReachable()) return true;
  }
  Serial.println("[toi] pair: camera never joined our SoftAP");
  return false;
}

// Factory firmware boots with awb/aec/agc all OFF -> near-black images
// (vlogCamera hardware-verification, 2026-06-02). Enable auto exposure and
// pick SVGA/q12 for fast transfer. Best-effort: failures are non-fatal.
static void configureCamera() {
  static const char *kInit[] = {
      "/api/v1/control?var=awb&val=1",  "/api/v1/control?var=awb_gain&val=1",
      "/api/v1/control?var=aec&val=1",  "/api/v1/control?var=agc&val=1",
      "/api/v1/control?var=gainceiling&val=2",
      // This fork's framesize enum: 9=HVGA 480x320, 10=VGA, 11=SVGA.
      // One mode for finder AND stills (the shot IS the last finder frame).
      "/api/v1/control?var=framesize&val=9",
      "/api/v1/control?var=quality&val=15",
  };
  for (auto p : kInit) camGet(p);
}

static bool captureFromCam() {
  free(jpegBuf);
  jpegBuf = nullptr;
  jpegLen = 0;

  if (retainBuf && retainLen && millis() - retainAt < 2000) {
    // The shot IS the last finder frame — instant, and exactly WYSIWYG.
    if (jpegLen < retainLen || !jpegBuf) {
      free(jpegBuf);
      jpegBuf = (uint8_t *)ps_malloc(retainLen);
    }
    if (jpegBuf) {
      memcpy(jpegBuf, retainBuf, retainLen);
      jpegLen = retainLen;
      Serial.printf("[toi] capture: 0ms (finder frame, %u bytes)\n",
                    (unsigned)retainLen);
      return true;
    }
  }
  if (camBase.isEmpty() && !cameraReachable()) {
    lastError = "カメラ未接続";
    return false;
  }
  const uint32_t t0 = millis();
  HTTPClient http;
  http.setTimeout(8000);
  if (!http.begin(camBase + "/api/v1/capture")) return false;
  const int code = http.GET();
  if (code == HTTP_CODE_OK) {
    jpegBuf = readBody(http, kMaxJpeg, jpegLen);
  } else {
    lastError = "camera HTTP " + String(code);
  }
  http.end();
  Serial.printf("[toi] capture: %lums (%u bytes, HTTP %d)\n", millis() - t0,
                (unsigned)jpegLen, code);
  return jpegBuf != nullptr;
}

// TLS client kept alive across shots — saves the handshake round-trips.
static WiFiClientSecure analyzeClient;
static HTTPClient analyzeHttp;
static bool analyzeInit = false;

static bool analyzePhoto() {
  const uint32_t t0 = millis();
  if (!analyzeInit) {
    analyzeClient.setInsecure();  // own Worker only; trade-off in README
    analyzeHttp.setReuse(true);
    analyzeHttp.setConnectTimeout(5000);
    analyzeHttp.setTimeout(30000);
    analyzeInit = true;
  }
  String url = String(WORKER_URL) + "/analyze";
  if (gps.location.isValid() && gps.location.age() < 120000) {
    url += "?lat=" + String(gps.location.lat(), 6) +
           "&lon=" + String(gps.location.lng(), 6);
  }
  bool ok = false;
  int code = -1;
  for (int attempt = 0; attempt < 2 && !ok; ++attempt) {
    if (!analyzeHttp.begin(analyzeClient, url)) continue;
    analyzeHttp.addHeader("Content-Type", "image/jpeg");
    analyzeHttp.addHeader("X-Device-Token", DEVICE_TOKEN);
    code = analyzeHttp.POST(jpegBuf, jpegLen);
    if (code == HTTP_CODE_OK) {
      JsonDocument doc;
      if (deserializeJson(doc, analyzeHttp.getString()) ==
          DeserializationError::Ok) {
        caption = doc["caption"].as<String>();
        detailText = doc["detail"].as<String>();
        ok = caption.length() > 0;
      }
    } else {
      lastError = "analyze HTTP " + String(code);
      analyzeHttp.end();  // drop the (possibly stale) connection, retry fresh
    }
  }
  Serial.printf("[toi] analyze: %lums (HTTP %d, attempt-reuse, gps=%s)\n",
                millis() - t0, code, gps.location.isValid() ? "yes" : "no");
  return ok;
}

// Live viewfinder — subscribes to the camera's MJPEG stream over a single
// persistent connection and consumes it in small per-loop slices, so buttons
// stay responsive and there is no per-frame connection/request overhead.
// Finder mode = HVGA/q20 (small, fluid); capture mode = VGA/q12 (quality).
static WiFiClient streamClient;
static uint8_t *sBuf = nullptr;
static size_t sLen = 0;
static bool sInJpeg = false;
static uint32_t sFrames = 0, sWindowStart = 0, sLastFrameAt = 0;
static constexpr size_t kStreamBufCap = 300 * 1024;

static void streamStop() {
  streamClient.stop();
  sLen = 0;
  sInJpeg = false;
}

static bool streamConnect() {
  const String host = camBase.substring(7);  // strip "http://"
  if (!streamClient.connect(host.c_str(), 80, 1500)) return false;
  streamClient.print("GET /api/v1/stream HTTP/1.1\r\nHost: " + host +
                     "\r\n\r\n");
  sLen = 0;
  sInJpeg = false;
  if (!sBuf) sBuf = (uint8_t *)ps_malloc(kStreamBufCap);
  Serial.println("[toi] finder: stream connected");
  return true;
}

// Transfer-encoding agnostic MJPEG parsing: scan the raw byte stream for JPEG
// SOI (FFD8) / EOI (FFD9) markers. Chunked-encoding noise between frames is
// skipped naturally because we only trust the markers.
static void previewTick() {
  if (!streamClient.connected()) {
    if (!streamConnect()) {
      if (++previewFails >= 5) {
        gCamOk = false;
        previewFails = 0;
        streamStop();
        showIdleWithWarnings(gNetOk, false);
      }
      return;
    }
    previewFails = 0;
    sLastFrameAt = millis();
  }
  if (!sBuf) return;

  int budget = 24 * 1024;  // bytes per tick — bounds time spent per loop pass
  while (budget > 0) {
    const int avail = streamClient.available();
    if (avail <= 0) break;
    const size_t want =
        min((size_t)avail, min((size_t)budget, kStreamBufCap - sLen));
    if (want == 0) {  // buffer full without a frame — resync
      sLen = 0;
      sInJpeg = false;
      break;
    }
    const int n = streamClient.read(sBuf + sLen, want);
    if (n <= 0) break;
    sLen += n;
    budget -= n;

    if (!sInJpeg) {
      // Find SOI, discard everything before it
      for (size_t i = 0; i + 1 < sLen; ++i) {
        if (sBuf[i] == 0xFF && sBuf[i + 1] == 0xD8) {
          memmove(sBuf, sBuf + i, sLen - i);
          sLen -= i;
          sInJpeg = true;
          break;
        }
      }
      if (!sInJpeg && sLen > 2) {  // keep last byte (may be first half of SOI)
        sBuf[0] = sBuf[sLen - 1];
        sLen = 1;
      }
    }
    if (sInJpeg) {
      // Find EOI after the SOI
      for (size_t i = 2; i + 1 < sLen; ++i) {
        if (sBuf[i] == 0xFF && sBuf[i + 1] == 0xD9) {
          const size_t frameLen = i + 2;
          // Retain a copy — the shutter reuses it as the shot (zero latency)
          if (frameLen > retainCap) {
            free(retainBuf);
            retainCap = frameLen + 16384;
            retainBuf = (uint8_t *)ps_malloc(retainCap);
          }
          if (retainBuf) {
            memcpy(retainBuf, sBuf, frameLen);
            retainLen = frameLen;
            retainAt = millis();
          }
          // HVGA 480x320 drawn 1:1, centered/cropped to the panel
          M5.Display.drawJpg(sBuf, frameLen,
                             (M5.Display.width() - 480) / 2,
                             (M5.Display.height() - 320) / 2);
          M5.Display.setFont(&fonts::efontJA_16);
          M5.Display.setTextSize(1);
          M5.Display.setTextDatum(middle_center);
          M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
          M5.Display.drawString(" 黄:撮影 ", M5.Display.width() / 2, 430);
          memmove(sBuf, sBuf + frameLen, sLen - frameLen);
          sLen -= frameLen;
          sInJpeg = false;
          sLastFrameAt = millis();
          if (++sFrames % 20 == 0) {
            Serial.printf("[toi] finder: %.1f fps (%u bytes/frame)\n",
                          20000.0f / (millis() - sWindowStart),
                          (unsigned)frameLen);
            sWindowStart = millis();
          }
          break;
        }
      }
    }
  }
  if (streamClient.connected() && millis() - sLastFrameAt > 6000) {
    Serial.println("[toi] finder: stream stalled, reconnecting");
    streamStop();
  }
}

// ------------------------------------------------------------------ lifecycle

static void enterError(const String &msg) {
  lastError = msg;
  state = AppState::Error;
  showStatus(("エラー: " + msg).c_str(), TFT_RED);
  M5.Display.setTextSize(1);
  M5.Display.drawString("黄:再試行 青:戻る", M5.Display.width() / 2, 320);
}

static void runCaptureCycle() {
  const uint32_t cycleStart = millis();
  state = AppState::Capturing;
  stopAnimalese();
  sfxShutter();

  drawBusy("カメラ通信中", TFT_YELLOW);
  if (!captureFromCam()) {
    sfxError();
    enterError(lastError.length() ? lastError : "カメラに接続できません");
    return;
  }
  {
    const uint32_t t0 = millis();
    drawPhoto();
    Serial.printf("[toi] drawJpg: %lums\n", millis() - t0);
  }

  state = AppState::Analyzing;
  drawBusy("AI解析中...", TFT_CYAN);
  if (!analyzePhoto()) {
    sfxError();
    enterError(lastError.length() ? lastError : "解析に失敗しました");
    return;
  }

  buildResultCanvas();
  drawResult(true);
  autoScrollAt = millis() + 2500;
  state = AppState::Result;  // interactive immediately — speech runs in a task
  speakAnimalese(caption + "。" + detailText);
  Serial.printf("[toi] cycle total: %lums\n", millis() - cycleStart);
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
  Serial.begin(115200);
  // Unit GPS v1.1 (AT6668, 9600bps NMEA) on the Grove port. RX/TX assignment
  // is auto-detected: start with RX=G10, swap to RX=G11 if no NMEA arrives.
  Serial1.begin(9600, SERIAL_8N1, 10 /*RX*/, 11 /*TX*/);
  gpsSwapDeadline = millis() + 10000;
  WiFi.mode(WIFI_AP_STA);
  WiFi.setSleep(false);  // modem sleep adds 100-300ms bursts to every request
  gNetOk = connectWifi();  // internet is only needed for the AI call
  Serial.printf("[toi] STA %s ip=%s ch=%d\n", gNetOk ? "ok" : "FAIL",
                WiFi.localIP().toString().c_str(), WiFi.channel());
  startSoftAp();

  gCamOk = cameraReachable();
  if (!gCamOk) gCamOk = pairCamera();  // auto-provision (one-time, device-only)
  if (gCamOk) configureCamera();       // black-image fix + VGA

  showIdleWithWarnings(gNetOk, gCamOk);  // preview takes over when camera is up
  state = AppState::Idle;
}

void loop() {
  M5.update();

  // GPS: feed NMEA continuously; auto-swap RX pin once if the line is silent
  while (Serial1.available()) {
    gps.encode(Serial1.read());
    ++gpsBytes;
  }
  if (!gpsBytes && !gpsPinsSwapped && millis() > gpsSwapDeadline) {
    gpsPinsSwapped = true;
    Serial1.end();
    Serial1.begin(9600, SERIAL_8N1, 11 /*RX*/, 10 /*TX*/);
    Serial.println("[toi] gps: no data on RX=G10, swapped to RX=G11");
  }
  if (millis() - gpsLastLogAt > 10000) {
    gpsLastLogAt = millis();
    Serial.printf("[toi] gps: bytes=%lu sats=%d fix=%s%s\n",
                  (unsigned long)gpsBytes, gps.satellites.isValid() ? (int)gps.satellites.value() : -1,
                  gps.location.isValid() ? "yes " : "no",
                  gps.location.isValid()
                      ? (String(gps.location.lat(), 4) + "," + String(gps.location.lng(), 4)).c_str()
                      : "");
  }

  switch (state) {
    case AppState::Idle:
      if (M5.BtnA.wasPressed()) {
        runCaptureCycle();
      } else if (M5.BtnB.wasPressed()) {
        // Manual camera re-pairing (e.g. after fixing power/placement).
        showStatus("カメラ探索中...");
        gCamOk = cameraReachable() || pairCamera();
        if (gCamOk) configureCamera();
        showIdleWithWarnings(WiFi.status() == WL_CONNECTED, gCamOk);
      } else if (gCamOk) {
        previewTick();  // live viewfinder (consumes stream in small slices)
      } else if (!gCamOk && WiFi.softAPgetStationNum() > 0 &&
                 millis() - lastPreviewAt > 5000) {
        // A client joined our AP while we thought the camera was gone —
        // re-discover automatically (covers boot-order races).
        lastPreviewAt = millis();
        gCamOk = cameraReachable();
        if (gCamOk) configureCamera();
      }
      break;

    case AppState::Result: {
      if (M5.BtnA.wasPressed()) {
        runCaptureCycle();
        break;
      }
      if (M5.BtnB.wasPressed()) {
        // Cancel: stop speech, back to the finder
        stopAnimalese();
        sfxCancel();
        state = AppState::Idle;
        if (!gCamOk) showIdleWithWarnings(gNetOk, gCamOk);
        break;
      }
      // Touch drag scroll — track absolute Y between frames (deltaY from the
      // touch driver proved unreliable on this panel)
      static int lastTouchY = -1;
      auto t = M5.Touch.getDetail();
      const int viewH = M5.Display.height() - 150;
      const int maxScroll = max(0, textCanvasHeight - viewH);
      if (t.isPressed()) {
        if (lastTouchY >= 0 && t.y != lastTouchY) {
          scrollY = constrain(scrollY - (t.y - lastTouchY), 0, maxScroll);
          drawResult();
          autoScrollAt = 0;  // manual scroll cancels auto-scroll
        }
        lastTouchY = t.y;
      } else {
        lastTouchY = -1;
        if (autoScrollAt && millis() > autoScrollAt && scrollY < maxScroll) {
          scrollY = min(scrollY + 2, maxScroll);
          drawResult();
          autoScrollAt = millis() + 40;
        }
      }
      break;
    }

    case AppState::Error:
      if (M5.BtnB.wasPressed()) {
        sfxCancel();
        state = AppState::Idle;
        if (!gCamOk) showIdleWithWarnings(gNetOk, gCamOk);
        break;
      }
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

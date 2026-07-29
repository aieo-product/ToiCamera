// ToiCamera — Stopwatch host firmware
//
// Yellow button (KEYA/G2): capture -> show photo -> AI explanation
// Blue button   (KEYB/G1): home (finder), sleep (home), back (result/error)
// Blue hold                 : re-pair the camera from the live finder
// Speech: on-device "animalese" (per-character chirps with intonation) — no TTS
// Touch drag             : scroll explanation text
// Home screen            : clock, place, steps; camera stream is stopped
// Idle screen            : live viewfinder (continuous QVGA preview)
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
#include <driver/gpio.h>
#include <esp_sleep.h>
#include <math.h>
#include <sys/time.h>
#include <time.h>

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
  Home,
  Idle,
  Capturing,
  Analyzing,
  Result,
  Error,
  Sleeping,
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
static M5Canvas homeCanvas(&M5.Display);
static bool homeCanvasReady = false;
static bool homeDirty = true;
static int32_t homeLastMinute = -1;

static TinyGPSPlus gps;
static uint32_t gpsBytes = 0;
static bool gpsPinsSwapped = false;
static uint32_t gpsSwapDeadline = 0;
static uint32_t gpsLastLogAt = 0;
static bool homeHadGpsFix = false;
static bool placeLookupPending = true;
static uint32_t lastPlaceAt = 0;
static String homePlace;
static String homeStation;
static int homeDistanceM = 0;
static int homeWalkMin = 0;

static bool ntpSyncPending = false;
static uint32_t lastNtpPollAt = 0;

static bool stepCounterAvailable = false;
static uint32_t stepCount = 0;
static uint32_t lastStepAt = 0;
static int32_t stepDateKey = -1;
static float accelNormAverage = 0.0f;
static bool accelPeakHigh = false;

static TaskHandle_t animTask = nullptr;
static volatile bool animStopFlag = false;
static String animText;

static bool gNetOk = false;
static bool gCamOk = false;
static bool cameraDiscoveryDone = false;
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
    M5.Display.drawString("カメラ未検出 青長押しで再接続", M5.Display.width() / 2, 340);
  }
}

static bool hasFreshGpsFix() {
  return gps.location.isValid() && gps.location.age() < 120000;
}

static bool getLocalClock(struct tm &local) {
  const time_t now = time(nullptr);
  return localtime_r(&now, &local) != nullptr && local.tm_year >= 125;
}

static void drawHome() {
  if (!homeCanvasReady) {
    homeCanvas.setColorDepth(8);
    homeCanvasReady =
        homeCanvas.createSprite(M5.Display.width(), M5.Display.height()) != nullptr;
  }
  if (!homeCanvasReady) {
    showStatus("ホーム画面を表示できません", TFT_RED);
    return;
  }

  homeCanvas.fillSprite(TFT_BLACK);
  homeCanvas.setFont(&fonts::efontJA_16);
  homeCanvas.setTextDatum(middle_center);

  const int battery = M5.Power.getBatteryLevel();
  char batteryText[16];
  if (battery >= 0) {
    snprintf(batteryText, sizeof(batteryText), "%d%%", battery);
  } else {
    snprintf(batteryText, sizeof(batteryText), "--%%");
  }
  homeCanvas.setTextSize(1);
  homeCanvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  // Centered near the top — (360,42) sits on the round panel's clipped edge.
  homeCanvas.drawString(batteryText, M5.Display.width() / 2, 48);

  struct tm local {};
  if (getLocalClock(local)) {
    static constexpr const char *kWeekdays[] = {
        "日", "月", "火", "水", "木", "金", "土"};
    char dateText[40];
    char timeText[8];
    snprintf(dateText, sizeof(dateText), "%04d/%02d/%02d (%s)",
             local.tm_year + 1900, local.tm_mon + 1, local.tm_mday,
             kWeekdays[local.tm_wday]);
    snprintf(timeText, sizeof(timeText), "%02d:%02d", local.tm_hour,
             local.tm_min);
    homeCanvas.setTextSize(1);
    homeCanvas.drawString(dateText, M5.Display.width() / 2, 98);
    homeCanvas.setTextSize(4);
    homeCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
    homeCanvas.drawString(timeText, M5.Display.width() / 2, 165);
  } else {
    homeCanvas.setTextSize(1);
    homeCanvas.drawString("時刻を同期中...", M5.Display.width() / 2, 98);
    homeCanvas.setTextSize(4);
    homeCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
    homeCanvas.drawString("--:--", M5.Display.width() / 2, 165);
  }

  if (stepCounterAvailable) {
    homeCanvas.setTextSize(1);
    homeCanvas.setTextColor(TFT_CYAN, TFT_BLACK);
    // efontJA_16 has no emoji glyphs — keep the step display text-only.
    homeCanvas.drawString(String(stepCount) + " 歩", M5.Display.width() / 2,
                          260);
  }

  if (hasFreshGpsFix()) {
    homeCanvas.setTextSize(1);
    homeCanvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    if (homePlace.length()) {
      homeCanvas.drawString(homePlace, M5.Display.width() / 2, 330);
    }
    if (homeStation.length()) {
      homeCanvas.drawString("最寄り:" + homeStation + " 徒歩" +
                                String(homeWalkMin) + "分",
                            M5.Display.width() / 2, 362);
    }
  }

  homeCanvas.setTextSize(1);
  homeCanvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  homeCanvas.drawString("黄:カメラ 青:スリープ",
                        M5.Display.width() / 2, 438);
  homeCanvas.pushSprite(0, 0);
  homeDirty = false;
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
  // Same framing the finder showed (QVGA scaled to panel width).
  const float sc = M5.Display.width() / 320.0f;
  M5.Display.drawJpg(jpegBuf, jpegLen, 0,
                     (int)((M5.Display.height() - 240 * sc) / 2),
                     M5.Display.width(), (int)(240 * sc), 0, 0, sc, sc);
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

static void restoreSystemClockFromRtc() {
  setenv("TZ", "JST-9", 1);
  tzset();
  m5::rtc_datetime_t rtc;
  if (!M5.Rtc.getDateTime(&rtc) || rtc.date.year < 2025) {
    Serial.println("[toi] rtc: no valid saved time");
    return;
  }

  struct tm local {};
  local.tm_year = rtc.date.year - 1900;
  local.tm_mon = rtc.date.month - 1;
  local.tm_mday = rtc.date.date;
  local.tm_hour = rtc.time.hours;
  local.tm_min = rtc.time.minutes;
  local.tm_sec = rtc.time.seconds;
  local.tm_isdst = -1;
  const time_t epoch = mktime(&local);
  if (epoch > 0) {
    const timeval now = {epoch, 0};
    settimeofday(&now, nullptr);
    Serial.printf("[toi] rtc: restored %04d-%02d-%02d %02d:%02d:%02d\n",
                  rtc.date.year, rtc.date.month, rtc.date.date, rtc.time.hours,
                  rtc.time.minutes, rtc.time.seconds);
  }
}

static void beginNtpSync() {
  setenv("TZ", "JST-9", 1);
  tzset();
  configTzTime("JST-9", "ntp.nict.jp", "pool.ntp.org");
  ntpSyncPending = true;
  lastNtpPollAt = 0;
  Serial.println("[toi] ntp: sync requested");
}

static void pollNtpSync() {
  if (!ntpSyncPending || WiFi.status() != WL_CONNECTED ||
      (lastNtpPollAt && millis() - lastNtpPollAt < 5000)) {
    return;
  }
  lastNtpPollAt = millis();
  struct tm local {};
  if (!getLocalTime(&local, 10) || local.tm_year < 125) return;
  M5.Rtc.setDateTime(&local);
  ntpSyncPending = false;
  homeDirty = true;
  Serial.printf("[toi] ntp: synced, RTC updated %04d-%02d-%02d %02d:%02d:%02d\n",
                local.tm_year + 1900, local.tm_mon + 1, local.tm_mday,
                local.tm_hour, local.tm_min, local.tm_sec);
}

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
    if (WiFi.status() == WL_CONNECTED) {
      beginNtpSync();
      return true;
    }
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
  gNetOk = connectWifi();
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
      // PY260/mega_ccm driver: supported sizes are QVGA/VGA/HD/UXGA/FHD/5MP
      // (+96/128/320 squares); quality is 3-step (0=high,1=default,2=low).
      // Unsupported values return "ok" without touching the sensor!
      "/api/v1/control?var=framesize&val=6",  // QVGA 320x240 finder
      "/api/v1/control?var=quality&val=1",
  };
  for (auto p : kInit) {
    const bool ok = camGet(p);
    Serial.printf("[toi] camcfg %s -> %s\n", p, ok ? "ok" : "FAIL");
  }
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
static WiFiClientSecure placeClient;
static HTTPClient placeHttp;
static bool placeHttpInit = false;

static bool fetchHomePlace() {
  if (!hasFreshGpsFix() || WiFi.status() != WL_CONNECTED) return false;
  if (!placeHttpInit) {
    placeClient.setInsecure();  // same own-Worker TLS trade-off as /analyze
    placeHttp.setReuse(true);
    placeHttp.setConnectTimeout(5000);
    placeHttp.setTimeout(5000);
    placeHttpInit = true;
  }

  const String url = String(WORKER_URL) + "/place?lat=" +
                     String(gps.location.lat(), 6) + "&lon=" +
                     String(gps.location.lng(), 6);
  homePlace = "";
  homeStation = "";
  homeDistanceM = 0;
  homeWalkMin = 0;
  const uint32_t t0 = millis();
  int code = -1;
  bool ok = false;
  if (placeHttp.begin(placeClient, url)) {
    placeHttp.addHeader("X-Device-Token", DEVICE_TOKEN);
    code = placeHttp.GET();
    if (code == HTTP_CODE_OK) {
      JsonDocument doc;
      if (deserializeJson(doc, placeHttp.getString()) ==
          DeserializationError::Ok) {
        homePlace = doc["place"].as<String>();
        homeStation = doc["station"].as<String>();
        homeDistanceM = doc["distance_m"] | 0;
        homeWalkMin = doc["walk_min"] | 0;
        ok = true;
      }
    } else {
      placeHttp.end();  // discard a failed/stale keep-alive connection
    }
  }
  Serial.printf("[toi] place: %lums HTTP %d place=%s station=%s distance=%dm\n",
                millis() - t0, code, homePlace.c_str(), homeStation.c_str(),
                homeDistanceM);
  homeDirty = true;
  return ok;
}

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

// HTTP de-chunking state — AsyncWebServer streams with Transfer-Encoding:
// chunked, and chunk framing bytes MUST NOT reach the JPEG reassembler
// (they corrupt frames with periodic garbage bands).
enum class CkState { Header, Size, Data, CrLf };
static CkState ckState = CkState::Header;
static String ckLine;
static size_t ckRemain = 0;
static bool ckChunked = false;

static void streamStop() {
  streamClient.stop();
  sLen = 0;
  sInJpeg = false;
  ckState = CkState::Header;
  ckLine = "";
  ckRemain = 0;
  ckChunked = false;
}

static bool streamConnect() {
  const String host = camBase.substring(7);  // strip "http://"
  if (!streamClient.connect(host.c_str(), 80, 1500)) return false;
  streamClient.print("GET /api/v1/stream HTTP/1.1\r\nHost: " + host +
                     "\r\n\r\n");
  sLen = 0;
  sInJpeg = false;
  ckState = CkState::Header;
  ckLine = "";
  ckRemain = 0;
  ckChunked = false;
  if (!sBuf) sBuf = (uint8_t *)ps_malloc(kStreamBufCap);
  Serial.println("[toi] finder: stream connected");
  return true;
}

// JPEG reassembly from a clean (de-chunked) byte stream: collect FFD8..FFD9.
static void feedJpeg(const uint8_t *d, size_t n) {
  if (sLen + n > kStreamBufCap) {  // resync
    sLen = 0;
    sInJpeg = false;
  }
  memcpy(sBuf + sLen, d, n);
  sLen += n;

  if (!sInJpeg) {
    for (size_t i = 0; i + 1 < sLen; ++i) {
      if (sBuf[i] == 0xFF && sBuf[i + 1] == 0xD8) {
        memmove(sBuf, sBuf + i, sLen - i);
        sLen -= i;
        sInJpeg = true;
        break;
      }
    }
    if (!sInJpeg && sLen > 1) {
      sBuf[0] = sBuf[sLen - 1];
      sLen = 1;
    }
  }
  if (sInJpeg) {
    for (size_t i = 2; i + 1 < sLen; ++i) {
      if (sBuf[i] == 0xFF && sBuf[i + 1] == 0xD9) {
        const size_t frameLen = i + 2;
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
        if (state == AppState::Idle) {
          // QVGA 320x240 scaled to panel width (full frame visible)
          const float sc = M5.Display.width() / 320.0f;
          M5.Display.drawJpg(sBuf, frameLen, 0,
                             (int)((M5.Display.height() - 240 * sc) / 2),
                             M5.Display.width(), (int)(240 * sc), 0, 0, sc, sc);
          M5.Display.setFont(&fonts::efontJA_16);
          M5.Display.setTextSize(1);
          M5.Display.setTextDatum(middle_center);
          M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
          M5.Display.drawString(" 黄:撮影 ", M5.Display.width() / 2, 430);
        }
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

  uint8_t tmp[1460];
  int budget = 24 * 1024;
  while (budget > 0) {
    const int avail = streamClient.available();
    if (avail <= 0) break;

    if (ckState == CkState::Header || ckState == CkState::Size ||
        ckState == CkState::CrLf) {
      // line-oriented states — read one byte at a time (short lines)
      const char c = (char)streamClient.read();
      --budget;
      if (ckState == CkState::Header) {
        ckLine += c;
        if (ckLine.length() > 800) ckLine = ckLine.substring(400);
        if (ckLine.endsWith("\r\n\r\n")) {
          ckChunked = ckLine.indexOf("chunked") >= 0;
          ckLine = "";
          ckState = ckChunked ? CkState::Size : CkState::Data;
          if (!ckChunked) ckRemain = SIZE_MAX;  // raw until close
        }
      } else if (ckState == CkState::Size) {
        ckLine += c;
        if (ckLine.endsWith("\r\n")) {
          ckRemain = strtoul(ckLine.c_str(), nullptr, 16);
          ckLine = "";
          ckState = ckRemain ? CkState::Data : CkState::Header;  // 0 = end
        }
      } else {  // CrLf after chunk data
        ckLine += c;
        if (ckLine.endsWith("\r\n")) {
          ckLine = "";
          ckState = CkState::Size;
        }
      }
      continue;
    }

    // Data state: bulk-read min(chunk remainder, available, budget, tmp)
    const size_t want = min(min((size_t)avail, (size_t)budget),
                            min(ckRemain, sizeof(tmp)));
    const int n = streamClient.read(tmp, want);
    if (n <= 0) break;
    budget -= n;
    feedJpeg(tmp, n);
    if (ckChunked) {
      ckRemain -= n;
      if (ckRemain == 0) ckState = CkState::CrLf;
    }
  }
  if (streamClient.connected() && millis() - sLastFrameAt > 6000) {
    Serial.println("[toi] finder: stream stalled, reconnecting");
    streamStop();
  }
}

// ------------------------------------------------------- voice question (ask)

static String urlenc(const String &in) {
  String out;
  const char *hex = "0123456789ABCDEF";
  for (size_t i = 0; i < in.length(); ++i) {
    const uint8_t c = in[i];
    if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
      out += (char)c;
    } else {
      out += '%';
      out += hex[c >> 4];
      out += hex[c & 15];
    }
  }
  return out;
}

// Hold-to-talk: record from the built-in mic while KEYA is held, wrap as WAV,
// send to the Worker (/ask) with the current explanation as context, then
// show + speak the answer.
static void voiceQuestionFlow() {
  stopAnimalese();
  M5.Speaker.tone(900, 40);  // "listening" blip before the speaker is released
  delay(60);
  M5.Speaker.end();  // mic and speaker share the codec/I2S
  if (!M5.Mic.begin()) {
    M5.Speaker.begin();
    M5.Speaker.setVolume(255);
    Serial.println("[toi] ask: mic begin FAILED");
    return;
  }

  constexpr uint32_t kRate = 16000;
  constexpr size_t kMaxSamples = kRate * 10;  // up to 10s
  constexpr size_t kChunk = 1024;
  int16_t *pcm = (int16_t *)ps_malloc(kMaxSamples * 2 + 44);
  size_t total = 0;
  drawBusy("録音中(離すと送信)", TFT_RED);
  const uint32_t t0 = millis();
  while (total + kChunk <= kMaxSamples) {
    M5.update();
    if (!M5.BtnA.isPressed() && millis() - t0 > 300) break;
    if (M5.Mic.record(pcm + 22 + total, kChunk, kRate)) {
      while (M5.Mic.isRecording()) delay(1);
      total += kChunk;
    }
  }
  M5.Mic.end();
  M5.Speaker.begin();
  M5.Speaker.setVolume(255);
  Serial.printf("[toi] ask: recorded %u samples (%.1fs)\n", (unsigned)total,
                total / (float)kRate);
  if (!pcm || total < kRate / 2) {  // under 0.5s — treat as accidental
    free(pcm);
    drawResult(true);
    return;
  }

  // WAV header in front of the PCM (44 bytes = 22 int16 slots)
  uint8_t *wav = (uint8_t *)pcm;
  const uint32_t dataLen = total * 2;
  memcpy(wav, "RIFF", 4);
  *(uint32_t *)(wav + 4) = 36 + dataLen;
  memcpy(wav + 8, "WAVEfmt ", 8);
  *(uint32_t *)(wav + 16) = 16;
  *(uint16_t *)(wav + 20) = 1;  // PCM
  *(uint16_t *)(wav + 22) = 1;  // mono
  *(uint32_t *)(wav + 24) = kRate;
  *(uint32_t *)(wav + 28) = kRate * 2;
  *(uint16_t *)(wav + 32) = 2;
  *(uint16_t *)(wav + 34) = 16;
  memcpy(wav + 36, "data", 4);
  *(uint32_t *)(wav + 40) = dataLen;

  drawBusy("考え中...", TFT_CYAN);
  const uint32_t ta = millis();
  bool ok = false;
  {
    if (!analyzeInit) {
      analyzeClient.setInsecure();
      analyzeHttp.setReuse(true);
      analyzeHttp.setConnectTimeout(5000);
      analyzeHttp.setTimeout(30000);
      analyzeInit = true;
    }
    const String url = String(WORKER_URL) + "/ask?caption=" + urlenc(caption) +
                       "&detail=" + urlenc(detailText);
    if (analyzeHttp.begin(analyzeClient, url)) {
      analyzeHttp.addHeader("Content-Type", "audio/wav");
      analyzeHttp.addHeader("X-Device-Token", DEVICE_TOKEN);
      const int code = analyzeHttp.POST(wav, 44 + dataLen);
      if (code == HTTP_CODE_OK) {
        JsonDocument doc;
        if (deserializeJson(doc, analyzeHttp.getString()) ==
            DeserializationError::Ok) {
          const String q = doc["question"].as<String>();
          const String a = doc["answer"].as<String>();
          Serial.printf("[toi] ask: %lums Q=%s A=%s\n", millis() - ta,
                        q.c_str(), a.c_str());
          if (a.length()) {
            caption = "Q: " + q;
            detailText = a;
            buildResultCanvas();
            drawResult(true);
            autoScrollAt = millis() + 2500;
            speakAnimalese(a);
            ok = true;
          }
        }
      } else {
        Serial.printf("[toi] ask: HTTP %d\n", code);
        analyzeHttp.end();
      }
    }
  }
  free(pcm);
  if (!ok) {
    sfxError();
    drawResult(true);  // restore previous explanation view
  }
}

// ------------------------------------------------------------------ lifecycle

static void stepCounterTick() {
  if (!M5.Imu.isEnabled()) return;
  const auto updated = M5.Imu.update();
  if (!(updated & m5::IMU_Class::sensor_mask_accel)) return;

  float ax = 0.0f, ay = 0.0f, az = 0.0f;
  if (!M5.Imu.getAccel(&ax, &ay, &az)) return;
  const float norm = sqrtf(ax * ax + ay * ay + az * az);
  if (!isfinite(norm) || norm < 0.1f || norm > 8.0f) return;

  if (!stepCounterAvailable) {
    stepCounterAvailable = true;
    accelNormAverage = norm;
    homeDirty = true;
    Serial.println("[toi] imu: accelerometer ok, software step counter enabled");
  }

  struct tm local {};
  if (getLocalClock(local)) {
    const int32_t dateKey =
        (local.tm_year + 1900) * 10000 + (local.tm_mon + 1) * 100 + local.tm_mday;
    if (stepDateKey < 0) {
      stepDateKey = dateKey;
    } else if (dateKey != stepDateKey) {
      stepDateKey = dateKey;
      stepCount = 0;
      homeDirty = true;
      Serial.println("[toi] steps: reset for new day");
    }
  }

  accelNormAverage = accelNormAverage * 0.90f + norm * 0.10f;
  const bool high = norm > 1.15f && norm > accelNormAverage + 0.10f;
  if (high && !accelPeakHigh && millis() - lastStepAt >= 300) {
    ++stepCount;
    lastStepAt = millis();
    accelPeakHigh = true;
    homeDirty = true;
    Serial.printf("[toi] steps: %lu\n", (unsigned long)stepCount);
  } else if (norm < 1.10f && norm < accelNormAverage + 0.04f) {
    accelPeakHigh = false;
  }
}

static void enterHome() {
  stopAnimalese();
  streamStop();
  Serial.println("[toi] finder: stream stopped (home)");
  state = AppState::Home;
  homeLastMinute = -1;
  placeLookupPending = true;
  lastPlaceAt = 0;
  homeHadGpsFix = hasFreshGpsFix();
  homeDirty = true;
  drawHome();
}

static void enterIdle() {
  state = AppState::Idle;
  if (!cameraDiscoveryDone) {
    cameraDiscoveryDone = true;
    showStatus("カメラ探索中...");
    gCamOk = cameraReachable();
    if (!gCamOk) gCamOk = pairCamera();
    if (gCamOk) configureCamera();
  }
  showIdleWithWarnings(WiFi.status() == WL_CONNECTED, gCamOk);
}

static void rePairCamera() {
  streamStop();
  showStatus("カメラ探索中...");
  gCamOk = cameraReachable() || pairCamera();
  if (gCamOk) configureCamera();
  showIdleWithWarnings(WiFi.status() == WL_CONNECTED, gCamOk);
}

static void homeTick() {
  pollNtpSync();

  const bool gpsFix = hasFreshGpsFix();
  if (gpsFix != homeHadGpsFix) {
    homeHadGpsFix = gpsFix;
    homeDirty = true;
    if (gpsFix) {
      placeLookupPending = true;
    } else {
      homePlace = "";
      homeStation = "";
      homeDistanceM = 0;
      homeWalkMin = 0;
    }
  }
  if (gpsFix && WiFi.status() == WL_CONNECTED &&
      (placeLookupPending ||
       (lastPlaceAt && millis() - lastPlaceAt >= 5 * 60 * 1000UL))) {
    placeLookupPending = false;
    lastPlaceAt = millis();
    fetchHomePlace();
  }

  struct tm local {};
  if (getLocalClock(local)) {
    const int32_t minuteKey =
        local.tm_yday * 24 * 60 + local.tm_hour * 60 + local.tm_min;
    if (minuteKey != homeLastMinute) {
      homeLastMinute = minuteKey;
      homeDirty = true;
    }
  }
  if (homeDirty) drawHome();
}

static void enterSleeping() {
  state = AppState::Sleeping;
  stopAnimalese();
  streamStop();
  Serial.println("[toi] finder: stream stopped (sleep)");
  M5.Display.sleep();
  M5.Display.setBrightness(0);
  WiFi.mode(WIFI_OFF);

  gpio_wakeup_enable(GPIO_NUM_2, GPIO_INTR_LOW_LEVEL);
  gpio_wakeup_enable(GPIO_NUM_1, GPIO_INTR_LOW_LEVEL);
  esp_sleep_enable_gpio_wakeup();
  // The press that selected sleep must be released before LOW-level wake is
  // armed, otherwise light sleep would return immediately.
  while (gpio_get_level(GPIO_NUM_2) == 0 || gpio_get_level(GPIO_NUM_1) == 0) {
    M5.update();
    delay(10);
  }
}

static void sleepingTick() {
  // USB CDC disconnects during light sleep. Hardware UART logging or a wake
  // marker after resume is more reliable when debugging this path.
  const esp_err_t sleepResult = esp_light_sleep_start();
  M5.Display.wakeup();
  M5.Display.setBrightness(200);
  WiFi.mode(WIFI_AP_STA);
  WiFi.setSleep(false);
  showStatus("WiFi接続中...");
  gNetOk = connectWifi();
  startSoftAp();
  Serial.printf("[toi] wake: light sleep result=%d STA=%s\n", sleepResult,
                gNetOk ? "ok" : "FAIL");
  enterHome();
}

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
  M5.Display.setFont(&fonts::efontJA_16);
  M5.Display.setTextSize(1);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setTextColor(TFT_DARKGREY, TFT_BLACK);
  M5.Display.drawString("黄長押し:質問 黄:撮影 青:戻る", M5.Display.width() / 2, 442);
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
  M5.Speaker.setVolume(255);
  M5.Display.setBrightness(200);
  Serial.begin(115200);
  restoreSystemClockFromRtc();

  showStatus("WiFi接続中...");
  state = AppState::WifiConnecting;
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

  // Camera discovery and pairing are intentionally deferred until the first
  // finder entry, keeping boot-to-home fast and the MJPEG stream stopped.
  gCamOk = false;
  enterHome();
}

static const char kB64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

// Debug: 'd' over USB serial dumps the latest finder frame as base64
static void debugDumpFrame() {
  if (!retainBuf || !retainLen) {
    Serial.println("[toi] dump: no frame retained");
    return;
  }
  Serial.printf("[toi] dump-begin %u\n", (unsigned)retainLen);
  for (size_t i = 0; i < retainLen; i += 3) {
    const uint32_t v = ((uint32_t)retainBuf[i] << 16) |
                       ((i + 1 < retainLen ? retainBuf[i + 1] : 0) << 8) |
                       (i + 2 < retainLen ? retainBuf[i + 2] : 0);
    char q[5] = {kB64[(v >> 18) & 63], kB64[(v >> 12) & 63],
                 (char)(i + 1 < retainLen ? kB64[(v >> 6) & 63] : '='),
                 (char)(i + 2 < retainLen ? kB64[v & 63] : '='), 0};
    Serial.print(q);
    if (i % 57 == 54) Serial.println();
  }
  Serial.println("\n[toi] dump-end");
}

void loop() {
  M5.update();

  if (Serial.available()) {
    const char cmd = Serial.read();
    if (cmd == 'd') debugDumpFrame();
    // Live camera tuning (PY260/mega_ccm: quality 0=high,1=default,2=low;
    // framesize: only QVGA/VGA/HD/UXGA/FHD/5MP + square sizes exist)
    else if (cmd >= '0' && cmd <= '2') {
      const String q = String("/api/v1/control?var=quality&val=") + cmd;
      Serial.printf("[toi] set %s -> %s\n", q.c_str(), camGet(q) ? "ok" : "FAIL");
    } else if (cmd == 'a' || cmd == 'b') {
      const String f = String("/api/v1/control?var=framesize&val=") +
                       (cmd == 'a' ? "6" : "10");  // a=QVGA, b=VGA
      Serial.printf("[toi] set %s -> %s\n", f.c_str(), camGet(f) ? "ok" : "FAIL");
    }
  }

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

  if (state != AppState::Sleeping) stepCounterTick();

  switch (state) {
    case AppState::Home:
      if (M5.BtnA.wasPressed()) {
        enterIdle();
      } else if (M5.BtnB.wasPressed()) {
        enterSleeping();
      } else {
        homeTick();
      }
      break;

    case AppState::Idle:
      if (M5.BtnA.wasPressed()) {
        runCaptureCycle();
      } else if (M5.BtnB.wasHold()) {
        // Manual camera re-pairing (e.g. after fixing power/placement).
        rePairCamera();
      } else if (M5.BtnB.wasClicked()) {
        enterHome();
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
      if (M5.BtnA.wasHold()) {
        voiceQuestionFlow();  // hold-to-talk question about this shot
        break;
      }
      if (M5.BtnA.wasClicked()) {
        runCaptureCycle();
        break;
      }
      if (M5.BtnB.wasPressed()) {
        // Cancel: stop speech, back to the finder
        stopAnimalese();
        sfxCancel();
        enterIdle();
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
        enterIdle();
        break;
      }
      if (M5.BtnA.wasPressed()) {
        if (WiFi.status() != WL_CONNECTED) {
          showStatus("WiFi接続中...");
          gNetOk = connectWifi();
          if (!gNetOk) {
            enterError("WiFiに接続できません");
            break;
          }
        }
        runCaptureCycle();
      }
      break;

    case AppState::Sleeping:
      sleepingTick();
      break;

    default:
      break;
  }
  delay(5);
}

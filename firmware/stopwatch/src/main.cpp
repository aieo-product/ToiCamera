// ToiCamera — Stopwatch host firmware
//
// Yellow button (KEYA/G2): capture -> show photo -> AI explanation
// Blue button   (KEYB/G1): home (finder), sleep (home), back (result/error)
// Blue hold                 : re-pair the camera from the live finder
// Speech: on-device animalese chirps or Worker-generated TTS
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
#include <WebServer.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <TinyGPSPlus.h>
#include <driver/gpio.h>
#include <esp_sleep.h>
#include <esp_sntp.h>
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
  WifiSetup,
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
static int homePage = 0;
static int homeHistoryScrollY = 0;
static int historyDetailIndex = -1;
static int historyDetailScrollY = 0;
static int historyDetailMaxScroll = 0;
static int settingsScrollY = 0;
// Settings item currently held down (-1 = none) — highlighted while pressed,
// the action fires on finger-up inside the same item.
static int settingsPressedRow = -1;

// Maps a viewport touch Y to a settings item in 78px content-space bands.
static int settingsItemForY(int screenY) {
  if (screenY < 128 || screenY >= 432) return -1;
  const int item = (screenY - 128 + settingsScrollY) / 78;
  return constrain(item, 0, 6);
}
static bool homeTouchActive = false;
static bool homeVolumeDragging = false;
static bool homeHistoryScrolled = false;
static bool settingsScrolled = false;
static int homeTouchStartX = 0;
static int homeTouchStartY = 0;
static int homeTouchLastX = 0;
static int homeTouchLastY = 0;
static int homeHistoryScrollStartY = 0;
static int settingsScrollStartY = 0;

static Preferences toiPrefs;
static bool toiPrefsReady = false;
static WebServer wifiPortal(80);
static bool wifiPortalRoutesRegistered = false;
static String wifiOptionsHtml;
static String nvsWifiSsid;
static String nvsWifiPass;
// Device token can be provisioned via the portal; NVS overrides the build-time
// secret. Never print its value.
static String nvsDeviceToken;
static const char *deviceToken() {
  return nvsDeviceToken.length() ? nvsDeviceToken.c_str() : DEVICE_TOKEN;
}
static uint32_t inquiryTotal = 0;
static uint32_t inquiryToday = 0;
static int32_t inquiryDateKey = -1;
static String inquiryHistory;
static String inquiryDigest;
static int32_t inquiryDigestCount = -1;
static constexpr size_t kInquiryHistoryMaxBytes = 16000;
static uint8_t speakerVolume = 255;
static uint8_t savedSpeakerVolume = 255;
static uint8_t paBoostPulses = 0;
// ES8311 DAC digital gain +10dB (reg 0x32: 0xBF=0dB, 0.5dB/step). Confirmed
// on-device 2026-08-04: clearly louder than 0dB and than any AW-PA pulse
// mode, no audible distortion — so it ships enabled.
static bool es8311DacBoost = true;
static uint8_t captureQuality = 0;
static String toiModels[8];
static uint8_t toiModelCount = 0;
static String toiFallbackModels[2] = {"gpt-5.6-terra", "gpt-5.6-luna"};
static uint8_t selectedModel = 0;
static uint8_t selectedLang = 0;
static bool aiDetailHigh = false;  // X-Detail: low|high for /analyze
static uint8_t voiceMode = 0;      // 0=animalese chirps, 1=Worker TTS
static bool toiConfigSettingsRetryDone = false;

static TinyGPSPlus gps;
static uint32_t gpsBytes = 0;
static bool gpsPinsSwapped = false;
static uint32_t gpsSwapDeadline = 0;
static uint32_t gpsLastLogAt = 0;
static bool homeHadGpsFix = false;
static bool placeLookupPending = true;
static uint32_t lastPlaceAt = 0;
static bool digestLookupPending = true;
static uint32_t lastDigestAt = 0;
static String homePlace;
static String homeShort;  // postcode-level label from /place (no AI)
static String homeStation;
static int homeDistanceM = 0;
static int homeWalkMin = 0;

static bool ntpSyncPending = false;
// Set from the SNTP callback — getLocalTime() alone cannot tell a fresh SNTP
// reply from a clock already restored out of the RTC.
static volatile bool sntpSynced = false;

static bool stepCounterAvailable = false;
static uint32_t stepCount = 0;
static uint32_t lastStepAt = 0;
static int32_t stepDateKey = -1;
static float accelNormAverage = 0.0f;
static bool accelPeakHigh = false;

static TaskHandle_t animTask = nullptr;
static volatile bool animStopFlag = false;
static String animText;
static uint8_t *ttsBuf = nullptr;
static size_t ttsLen = 0;

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

static uint8_t activeModelCount() {
  return toiModelCount ? toiModelCount : 2;
}

static String &activeModelAt(uint8_t index) {
  if (toiModelCount) {
    return toiModels[index < toiModelCount ? index : 0];
  }
  return toiFallbackModels[index < 2 ? index : 0];
}

static const char *selectedModelName() {
  return activeModelAt(selectedModel).c_str();
}

static void selectModelByName(const String &name, bool persist = true) {
  selectedModel = 0;
  const uint8_t count = activeModelCount();
  for (uint8_t i = 0; i < count; ++i) {
    if (activeModelAt(i) == name) {
      selectedModel = i;
      break;
    }
  }
  if (persist && toiPrefsReady) {
    toiPrefs.putString("modelName", selectedModelName());
  }
}

static bool loadModelCsv(const String &csv) {
  String parsed[8];
  uint8_t count = 0;
  int start = 0;
  while (start <= static_cast<int>(csv.length()) && count < 8) {
    const int comma = csv.indexOf(',', start);
    const int end = comma >= 0 ? comma : csv.length();
    String model = csv.substring(start, end);
    model.trim();
    if (model.length() > 0 && model.length() <= 48) parsed[count++] = model;
    if (comma < 0) break;
    start = comma + 1;
  }
  if (!count) return false;
  for (uint8_t i = 0; i < count; ++i) toiModels[i] = parsed[i];
  for (uint8_t i = count; i < 8; ++i) toiModels[i] = "";
  toiModelCount = count;
  return true;
}

static void loadModelSettings() {
  if (!toiPrefsReady) return;
  loadModelCsv(toiPrefs.getString("models", ""));

  const String savedName = toiPrefs.getString("modelName", "");
  if (savedName.length()) {
    selectModelByName(savedName);
  } else if (toiPrefs.isKey("model")) {
    const uint8_t legacyIndex = toiPrefs.getUChar("model", 0);
    selectedModel = legacyIndex < activeModelCount() ? legacyIndex : 0;
    toiPrefs.putString("modelName", selectedModelName());
    toiPrefs.remove("model");
    Serial.printf("[toi] model: migrated to %s\n", selectedModelName());
  } else {
    selectModelByName("");
  }
}

static const char *selectedLangCode() {
  static constexpr const char *kLangs[] = {"ja", "en", "zh"};
  return kLangs[selectedLang < 3 ? selectedLang : 0];
}

static const char *tr(const char *ja, const char *en, const char *zh) {
  return selectedLang == 1 ? en : selectedLang == 2 ? zh : ja;
}

static const lgfx::IFont *contentFont() {
  return selectedLang == 2 ? &fonts::efontCN_16 : &fonts::efontJA_16;
}

// On-screen banner + a long 3-note melody, so speaker A/B tests can be
// followed by eye and ear. Blocks the loop ~1s (debug-only path).
static void volumeTestFeedback(const String &label) {
  M5.Display.fillRoundRect(83, 183, 300, 100, 16, TFT_BLACK);
  M5.Display.drawRoundRect(83, 183, 300, 100, 16, TFT_YELLOW);
  M5.Display.setFont(contentFont());
  M5.Display.setTextDatum(middle_center);
  M5.Display.setTextSize(3);
  M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
  M5.Display.drawString(label, M5.Display.width() / 2, 233);
  M5.Speaker.tone(660, 250);
  delay(280);
  M5.Speaker.tone(880, 250);
  delay(280);
  M5.Speaker.tone(1100, 350);
  delay(400);
  homeDirty = true;  // Home repaints over the banner on the next tick
}

static void applyPaBoost() {
  for (uint8_t pulse = 0; pulse < paBoostPulses; ++pulse) {
    m5::In_I2C.bitOff(0x4F, 0x06, 0b10, 400000);
    m5::In_I2C.bitOn(0x4F, 0x06, 0b10, 400000);
  }
  m5::In_I2C.writeRegister8(0x18, 0x32,
                            es8311DacBoost ? 0xD3 : 0xBF, 400000);
  Serial.printf("[toi] pa: boost pulses=%u applied\n",
                (unsigned)paBoostPulses);
}

// ---------------------------------------------------------------- UI helpers

static void showStatus(const char *msg, uint32_t color = TFT_WHITE) {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setFont(contentFont());
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(color, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  const String text = msg ? msg : "";
  int lineCount = 1;
  for (int newline = text.indexOf('\n'); newline >= 0;
       newline = text.indexOf('\n', newline + 1)) {
    ++lineCount;
  }
  constexpr int kLineSpacing = 44;
  const int firstLineY =
      M5.Display.height() / 2 - ((lineCount - 1) * kLineSpacing) / 2;
  int lineStart = 0;
  for (int line = 0; line < lineCount; ++line) {
    const int lineEnd = text.indexOf('\n', lineStart);
    M5.Display.drawString(
        text.substring(lineStart, lineEnd >= 0 ? lineEnd : text.length()),
        M5.Display.width() / 2, firstLineY + line * kLineSpacing);
    lineStart = lineEnd >= 0 ? lineEnd + 1 : text.length();
  }
}

static void showIdle() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setFont(contentFont());
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setTextSize(2);
  M5.Display.drawString("AI Camera", M5.Display.width() / 2, 180);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
  M5.Display.drawString(
      tr("黄ボタンで撮影", "Yellow button: shoot", "黄键拍摄"),
      M5.Display.width() / 2, 260);
}

static void showIdleWithWarnings(bool netOk, bool camOk) {
  showIdle();
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_ORANGE, TFT_BLACK);
  if (!netOk) {
    M5.Display.drawString(
        tr("ネット未接続(解析不可)", "No internet (no AI)",
           "网络未连接(无法解析)"),
        M5.Display.width() / 2, 310);
  }
  if (!camOk) {
    M5.Display.drawString(
        tr("カメラ未検出 青長押しで再接続",
           "No camera: hold blue to reconnect", "未检测到相机 长按蓝键重连"),
        M5.Display.width() / 2, 340);
  }
}

static bool hasFreshGpsFix() {
  return gps.location.isValid() && gps.location.age() < 120000;
}

static bool getLocalClock(struct tm &local) {
  const time_t now = time(nullptr);
  return localtime_r(&now, &local) != nullptr && local.tm_year >= 125;
}

static int32_t localDateKey() {
  struct tm local {};
  if (!getLocalClock(local)) return -1;
  return (local.tm_year + 1900) * 10000 + (local.tm_mon + 1) * 100 +
         local.tm_mday;
}

static String sanitizeHistoryField(const String &value) {
  String sanitized = value;
  sanitized.replace("\r", " ");
  sanitized.replace("\n", " ");
  sanitized.replace("|", " ");
  return sanitized;
}

static void saveInquiryHistory(const String &previousHistory) {
  if (!toiPrefsReady || inquiryHistory == previousHistory) return;
  if (inquiryHistory.length()) {
    toiPrefs.putBytes("histb", inquiryHistory.c_str(), inquiryHistory.length());
  } else if (toiPrefs.getBytesLength("histb") > 0) {
    toiPrefs.remove("histb");
  }
}

static void recordInquiry(const String &inquiryCaption,
                          const String &inquiryDetail) {
  const uint32_t previousTotal = inquiryTotal;
  const uint32_t previousToday = inquiryToday;
  const int32_t previousDateKey = inquiryDateKey;
  const String previousHistory = inquiryHistory;
  const String previousDigest = inquiryDigest;
  const int32_t previousDigestCount = inquiryDigestCount;

  struct tm local {};
  const bool clockKnown = getLocalClock(local);
  const int32_t dateKey =
      clockKnown ? (local.tm_year + 1900) * 10000 + (local.tm_mon + 1) * 100 +
                       local.tm_mday
                 : -1;
  if (dateKey >= 0 && dateKey != inquiryDateKey) {
    inquiryDateKey = dateKey;
    inquiryToday = 0;
    inquiryHistory = "";
    inquiryDigest = "";
    inquiryDigestCount = -1;
  }

  ++inquiryTotal;
  ++inquiryToday;
  if (inquiryCaption.length()) {
    char timeText[6] = "--:--";
    if (clockKnown) {
      snprintf(timeText, sizeof(timeText), "%02d:%02d", local.tm_hour,
               local.tm_min);
    }
    const String storedCaption = sanitizeHistoryField(inquiryCaption);
    const String storedDetail = sanitizeHistoryField(inquiryDetail);
    if (inquiryHistory.length()) inquiryHistory += "\n";
    inquiryHistory +=
        String(timeText) + "|" + storedCaption + "|" + storedDetail;
    while (inquiryHistory.length() > kInquiryHistoryMaxBytes) {
      const int lineEnd = inquiryHistory.indexOf('\n');
      if (lineEnd < 0) {
        inquiryHistory = "";
        break;
      }
      inquiryHistory.remove(0, lineEnd + 1);
    }
  }

  if (toiPrefsReady) {
    if (inquiryTotal != previousTotal) toiPrefs.putUInt("total", inquiryTotal);
    if (inquiryToday != previousToday) toiPrefs.putUInt("today", inquiryToday);
    if (inquiryDateKey != previousDateKey) {
      toiPrefs.putInt("dkey", inquiryDateKey);
    }
    saveInquiryHistory(previousHistory);
    if (inquiryDigest != previousDigest) {
      toiPrefs.putString("digest", inquiryDigest);
    }
    if (inquiryDigestCount != previousDigestCount) {
      toiPrefs.putInt("digN", inquiryDigestCount);
    }
  }
  digestLookupPending = true;
  homeDirty = true;
  Serial.printf("[toi] inquiries: today=%lu total=%lu hist=%u bytes\n",
                (unsigned long)inquiryToday, (unsigned long)inquiryTotal,
                (unsigned)inquiryHistory.length());
}

static void drawHomeDigest(const String &text) {
  const String wrappedText = String(tr("今日:", "Today: ", "今日:")) + text;
  String line;
  size_t i = 0;
  int lineNumber = 0;
  while (i < wrappedText.length() && lineNumber < 2) {
    const uint8_t b = wrappedText[i];
    const size_t charLen =
        (b < 0x80) ? 1 : (b < 0xE0) ? 2 : (b < 0xF0) ? 3 : 4;
    const String ch = wrappedText.substring(i, i + charLen);
    i += charLen;
    if (ch == "\n") {
      if (line.length()) {
        homeCanvas.drawString(line, M5.Display.width() / 2,
                              340 + lineNumber * 20);
        ++lineNumber;
        line = "";
      }
      continue;
    }
    if (line.length() && homeCanvas.textWidth(line + ch) > 320 &&
        !(ch == "、" || ch == "。" || ch == "」" || ch == ")")) {
      homeCanvas.drawString(line, M5.Display.width() / 2,
                            340 + lineNumber * 20);
      ++lineNumber;
      line = "";
      if (lineNumber >= 2) break;
    }
    line += ch;
  }
  if (line.length() && lineNumber < 2) {
    homeCanvas.drawString(line, M5.Display.width() / 2,
                          340 + lineNumber * 20);
  }
}

static int inquiryHistoryLineCount() {
  if (!inquiryHistory.length()) return 0;
  int count = 1;
  for (int pos = inquiryHistory.indexOf('\n'); pos >= 0;
       pos = inquiryHistory.indexOf('\n', pos + 1)) {
    ++count;
  }
  return count;
}

static bool getHistoryEntry(int newestIndex, String &timeText,
                            String &captionText, String &detailValue) {
  if (newestIndex < 0) return false;
  int lineEnd = inquiryHistory.length();
  int index = 0;
  while (lineEnd > 0) {
    const int separator = inquiryHistory.lastIndexOf('\n', lineEnd - 1);
    if (index == newestIndex) {
      const String line = inquiryHistory.substring(separator + 1, lineEnd);
      const int timeEnd = line.indexOf('|');
      const int captionEnd =
          timeEnd >= 0 ? line.indexOf('|', timeEnd + 1) : -1;
      timeText = timeEnd >= 0 ? line.substring(0, timeEnd) : String("--:--");
      captionText =
          timeEnd >= 0
              ? line.substring(timeEnd + 1,
                               captionEnd >= 0 ? captionEnd : line.length())
              : line;
      detailValue = captionEnd >= 0 ? line.substring(captionEnd + 1) : "";
      return true;
    }
    ++index;
    if (separator < 0) break;
    lineEnd = separator;
  }
  return false;
}

static int maxHomeHistoryScrollY() {
  return max(0, inquiryHistoryLineCount() * 56 - 280);
}

static String fitHomeText(const String &text, int maxWidth) {
  if (homeCanvas.textWidth(text) <= maxWidth) return text;
  const String ellipsis = "…";
  String fitted;
  size_t i = 0;
  while (i < text.length()) {
    const uint8_t b = text[i];
    const size_t charLen =
        (b < 0x80) ? 1 : (b < 0xE0) ? 2 : (b < 0xF0) ? 3 : 4;
    const String candidate = fitted + text.substring(i, i + charLen);
    if (homeCanvas.textWidth(candidate + ellipsis) > maxWidth) break;
    fitted = candidate;
    i += charLen;
  }
  return fitted + ellipsis;
}

static void appendHomeWrapped(const String &utf8, int32_t x, int32_t &y,
                              int lineHeight, int maxWidth) {
  String line;
  size_t i = 0;
  while (i < utf8.length()) {
    const uint8_t b = utf8[i];
    const size_t charLen =
        (b < 0x80) ? 1 : (b < 0xE0) ? 2 : (b < 0xF0) ? 3 : 4;
    const String ch = utf8.substring(i, i + charLen);
    i += charLen;
    if (ch == "\n") {
      homeCanvas.drawString(line, x, y);
      y += lineHeight;
      line = "";
      continue;
    }
    if (homeCanvas.textWidth(line + ch) > maxWidth &&
        !(ch == "、" || ch == "。" || ch == "」" || ch == ")")) {
      homeCanvas.drawString(line, x, y);
      y += lineHeight;
      line = "";
    }
    line += ch;
  }
  if (line.length()) {
    homeCanvas.drawString(line, x, y);
    y += lineHeight;
  }
}

static void drawPageDashboard() {
  const int battery = M5.Power.getBatteryLevel();
  const int batteryLevel = battery >= 0 ? constrain(battery, 0, 100) : 0;
  static constexpr int kBatterySegments = 40;
  const int litSegments =
      (batteryLevel * kBatterySegments + 50) / 100;
  for (int i = 0; i < kBatterySegments; ++i) {
    const float segmentStart = -210.0f + i * 6.0f;
    const uint32_t color =
        i < litSegments ? (batteryLevel < 20 ? TFT_RED : TFT_YELLOW)
                        : 0x39E7;
    homeCanvas.fillArc(233, 233, 228, 216, segmentStart,
                       segmentStart + 4.0f, color);
  }

  char batteryText[8];
  if (battery >= 0) {
    snprintf(batteryText, sizeof(batteryText), "%d%%", battery);
  } else {
    snprintf(batteryText, sizeof(batteryText), "--%%");
  }
  homeCanvas.setTextSize(1);
  homeCanvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  homeCanvas.drawString(batteryText, M5.Display.width() / 2, 64);

  struct tm local {};
  if (getLocalClock(local)) {
    static constexpr const char *kWeekdaysJa[] = {
        "日", "月", "火", "水", "木", "金", "土"};
    static constexpr const char *kWeekdaysEn[] = {
        "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
    static constexpr const char *kMonthsEn[] = {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
    static constexpr const char *kWeekdaysZh[] = {
        "日", "一", "二", "三", "四", "五", "六"};
    char dateText[40];
    char timeText[8];
    if (selectedLang == 1) {
      snprintf(dateText, sizeof(dateText), "%s, %s %d",
               kWeekdaysEn[local.tm_wday], kMonthsEn[local.tm_mon],
               local.tm_mday);
    } else if (selectedLang == 2) {
      snprintf(dateText, sizeof(dateText), "%d月%d日 星期%s", local.tm_mon + 1,
               local.tm_mday, kWeekdaysZh[local.tm_wday]);
    } else {
      snprintf(dateText, sizeof(dateText), "%d月%d日 %s曜日", local.tm_mon + 1,
               local.tm_mday, kWeekdaysJa[local.tm_wday]);
    }
    snprintf(timeText, sizeof(timeText), "%02d:%02d", local.tm_hour,
             local.tm_min);
    homeCanvas.setTextSize(4);
    homeCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
    homeCanvas.drawString(timeText, M5.Display.width() / 2, 140);
    homeCanvas.setTextSize(1);
    homeCanvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    homeCanvas.drawString(dateText, M5.Display.width() / 2, 190);
  } else {
    homeCanvas.setTextSize(4);
    homeCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
    homeCanvas.drawString("--:--", M5.Display.width() / 2, 140);
    homeCanvas.setTextSize(1);
    homeCanvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    homeCanvas.drawString(
        tr("時刻を同期中...", "Syncing time...", "正在同步时间..."),
        M5.Display.width() / 2, 190);
  }

  const auto drawStatTile = [&](int centerX, const char *label,
                                const String &value, uint32_t valueColor) {
    const int tileW = 118;
    const int tileH = 88;
    const int tileY = 262 - tileH / 2;
    homeCanvas.drawRoundRect(centerX - tileW / 2, tileY, tileW, tileH, 12,
                             valueColor);
    homeCanvas.setTextSize(1);
    homeCanvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    homeCanvas.drawString(label, centerX, 242);
    homeCanvas.setTextSize(value.length() >= 5 ? 2 : 3);
    homeCanvas.setTextColor(valueColor, TFT_BLACK);
    homeCanvas.drawString(value, centerX, 278);
  };
  drawStatTile(112, tr("今日の問い", "Today's Qs", "今日提问"),
               String(inquiryToday), TFT_YELLOW);
  drawStatTile(233, tr("歩数", "Steps", "步数"),
               stepCounterAvailable ? String(stepCount) : String("--"), TFT_CYAN);
  drawStatTile(354, tr("累計", "Total", "累计"), String(inquiryTotal),
               TFT_WHITE);

  if (inquiryDigest.length()) {
    homeCanvas.setFont(contentFont());
    homeCanvas.setTextSize(1);
    homeCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
    drawHomeDigest(inquiryDigest);
  }

  // GPS status is always visible; with a fix the label is the postcode-level
  // reverse-geocode result (plain OSM lookup — no AI inference involved).
  homeCanvas.setFont(contentFont());
  homeCanvas.setTextSize(1);
  const bool gpsLive = hasFreshGpsFix();
  String locationText = homeShort.length() ? homeShort : homePlace;
  if (homeStation.length()) {
    const String stationText =
        String(tr("最寄り:", "Near: ", "最近:")) + homeStation +
        tr(" 徒歩", ", ", " 步行") + String(homeWalkMin) +
        tr("分", " min walk", "分钟");
    const String combined =
        locationText.length() ? locationText + " / " + stationText
                              : stationText;
    locationText = homeCanvas.textWidth(combined) > 380 && locationText.length()
                       ? locationText
                       : combined;
  }
  if (locationText.length()) {
    // Last-known location survives fix loss (indoors) — just dimmed.
    homeCanvas.setTextColor(gpsLive ? TFT_LIGHTGREY : TFT_DARKGREY, TFT_BLACK);
    homeCanvas.drawString(fitHomeText(locationText, 380),
                          M5.Display.width() / 2, 384);
  } else {
    homeCanvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
    String gpsText;
    if (gpsBytes == 0) {
      gpsText = tr("GPS 未接続", "No GPS unit", "GPS 未连接");
    } else if (gpsLive) {
      gpsText = tr("GPS 測位OK", "GPS fix OK", "GPS 定位OK");
    } else {
      gpsText = tr("GPS 測位中...", "GPS locating...", "GPS 定位中...");
      if (gps.satellites.isValid()) {
        gpsText += String(tr(" 衛星", " sats ", " 卫星")) +
                   String((int)gps.satellites.value());
      }
    }
    homeCanvas.drawString(gpsText, M5.Display.width() / 2, 384);
  }

  homeCanvas.setTextSize(1);
  homeCanvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  homeCanvas.drawString(tr("黄:カメラ 青:スリープ", "Y: camera  B: sleep",
                           "黄:相机 蓝:休眠"),
                        M5.Display.width() / 2, 420);
}

static void drawPageHistoryDetail() {
  String timeText;
  String captionText;
  String detailValue;
  if (!getHistoryEntry(historyDetailIndex, timeText, captionText,
                       detailValue)) {
    historyDetailIndex = -1;
    return;
  }

  homeCanvas.setClipRect(73, 35, kTextWidth, 370);
  homeCanvas.setTextDatum(top_left);
  homeCanvas.setTextSize(1);
  homeCanvas.setTextColor(TFT_CYAN, TFT_BLACK);
  homeCanvas.drawString(timeText, 73, 44 - historyDetailScrollY);

  int32_t y = 74 - historyDetailScrollY;
  homeCanvas.setFont(contentFont());
  homeCanvas.setTextSize(2);
  homeCanvas.setTextColor(TFT_YELLOW, TFT_BLACK);
  appendHomeWrapped(captionText, 73, y, 36, kTextWidth);
  y += 12;
  homeCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
  appendHomeWrapped(detailValue, 73, y, 38, kTextWidth);
  homeCanvas.clearClipRect();
  // Content bottom in unscrolled space; +20px pad keeps the last line clear
  // of the bottom hint even at max scroll.
  historyDetailMaxScroll =
      max(0, (int)(y + historyDetailScrollY) - (35 + 370) + 20);

  homeCanvas.setFont(contentFont());
  homeCanvas.setTextDatum(middle_center);
  homeCanvas.setTextSize(1);
  homeCanvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  homeCanvas.drawString(tr("タップで戻る", "Tap to go back", "点按返回"),
                        M5.Display.width() / 2, 420);
}

static void drawPageHistory() {
  if (historyDetailIndex >= 0) {
    drawPageHistoryDetail();
    if (historyDetailIndex >= 0) return;
  }

  homeCanvas.fillArc(233, 233, 222, 219, -150.0f, -30.0f, TFT_YELLOW);
  homeCanvas.setTextDatum(middle_center);
  homeCanvas.setTextSize(1);
  homeCanvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  homeCanvas.drawString(
      tr("今日の問い", "Today's questions", "今日提问"),
      M5.Display.width() / 2, 48);

  if (!inquiryHistory.length()) {
    homeCanvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
    homeCanvas.drawString(tr("まだ問いがありません", "No questions yet",
                             "还没有提问"),
                          M5.Display.width() / 2,
                          M5.Display.height() / 2);
    return;
  }

  homeHistoryScrollY =
      constrain(homeHistoryScrollY, 0, maxHomeHistoryScrollY());
  homeCanvas.setClipRect(50, 100, 366, 280);
  int lineEnd = inquiryHistory.length();
  int newestIndex = 0;
  while (lineEnd > 0) {
    const int separator = inquiryHistory.lastIndexOf('\n', lineEnd - 1);
    const int lineStart = separator + 1;
    const int rowY = 100 + newestIndex * 56 - homeHistoryScrollY;
    if (rowY < 380 && rowY + 56 > 100) {
      const String line = inquiryHistory.substring(lineStart, lineEnd);
      const int timeEnd = line.indexOf('|');
      const int captionEnd =
          timeEnd >= 0 ? line.indexOf('|', timeEnd + 1) : -1;
      const String timeText =
          timeEnd >= 0 ? line.substring(0, timeEnd) : String("--:--");
      const String captionText =
          timeEnd >= 0
              ? line.substring(timeEnd + 1,
                               captionEnd >= 0 ? captionEnd : line.length())
              : line;
      homeCanvas.setFont(contentFont());
      homeCanvas.setTextSize(1);
      homeCanvas.setTextDatum(middle_right);
      homeCanvas.setTextColor(TFT_CYAN, TFT_BLACK);
      homeCanvas.drawString(timeText, 90, rowY + 27);
      homeCanvas.setFont(contentFont());
      homeCanvas.setTextSize(2);
      homeCanvas.setTextDatum(middle_left);
      homeCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
      homeCanvas.drawString(fitHomeText(captionText, 300), 110, rowY + 27);
      homeCanvas.drawFastHLine(55, rowY + 55, 356, 0x2124);
    }
    ++newestIndex;
    if (separator < 0) break;
    lineEnd = separator;
  }
  homeCanvas.clearClipRect();
}

// Seven spacious items: model / volume / quality / AI detail / voice / WiFi /
// language.
// Items use 78px content-space bands inside the clipped y=128..431 viewport.
static void drawPageSettings() {
  homeCanvas.setFont(contentFont());
  homeCanvas.fillArc(233, 233, 222, 219, -150.0f, -30.0f, TFT_YELLOW);
  homeCanvas.setTextDatum(middle_center);
  homeCanvas.setTextSize(2);
  homeCanvas.setTextColor(TFT_WHITE, TFT_BLACK);
  homeCanvas.drawString(tr("設定", "Settings", "设置"),
                        M5.Display.width() / 2, 40);

  settingsScrollY = constrain(settingsScrollY, 0, 242);
  homeCanvas.setClipRect(0, 128, 466, 304);
  const auto rowBg = [&](int row) {
    return settingsPressedRow == row ? 0x2945 : (int)TFT_BLACK;
  };

  for (int item = 0; item < 7; ++item) {
    const int itemTop = item * 78;
    const int screenItemTop = 128 + itemTop - settingsScrollY;
    if (screenItemTop >= 432 || screenItemTop + 78 <= 128) continue;

    if (settingsPressedRow == item) {
      homeCanvas.fillRect(36, screenItemTop, 394, 78, 0x2945);
    }

    homeCanvas.setTextDatum(middle_left);
    homeCanvas.setTextSize(2);
    homeCanvas.setTextColor(TFT_WHITE, rowBg(item));
    switch (item) {
      case 0:
        homeCanvas.drawString(tr("モデル", "Model", "模型"), 90,
                              screenItemTop + 18);
        homeCanvas.setTextSize(1);
        homeCanvas.setTextColor(TFT_CYAN, rowBg(item));
        homeCanvas.drawString(fitHomeText(String(selectedModelName()), 300), 90,
                              screenItemTop + 46);
        break;
      case 1: {
        homeCanvas.drawString(tr("音量", "Volume", "音量"), 90,
                              screenItemTop + 18);
        homeCanvas.fillRoundRect(190, screenItemTop + 15, 190, 6, 3,
                                 TFT_DARKGREY);
        const int volumeX =
            190 + (static_cast<int>(speakerVolume) * 190 + 127) / 255;
        homeCanvas.fillCircle(volumeX, screenItemTop + 18, 14, TFT_CYAN);
        break;
      }
      case 2:
        homeCanvas.drawString(tr("画質", "Quality", "画质"), 90,
                              screenItemTop + 18);
        homeCanvas.setTextSize(1);
        homeCanvas.setTextColor(TFT_LIGHTGREY, rowBg(item));
        homeCanvas.drawString(captureQuality == 1
                                  ? tr("画質優先(VGA・+約2秒)",
                                       "Quality first (VGA, +2s)",
                                       "画质优先(VGA,+约2秒)")
                                  : tr("速度優先(QVGA)",
                                       "Speed first (QVGA)",
                                       "速度优先(QVGA)"),
                              90, screenItemTop + 46);
        break;
      case 3:
        homeCanvas.drawString(tr("AI精度", "AI detail", "AI精度"), 90,
                              screenItemTop + 18);
        homeCanvas.setTextSize(1);
        homeCanvas.setTextColor(TFT_LIGHTGREY, rowBg(item));
        homeCanvas.drawString(aiDetailHigh
                                  ? tr("高(詳細に見る・消費大)",
                                       "High (detailed, more tokens)",
                                       "高(更详细,消耗大)")
                                  : tr("低(速い・省トークン)",
                                       "Low (fast, fewer tokens)",
                                       "低(快速,省token)"),
                              90, screenItemTop + 46);
        break;
      case 4:
        homeCanvas.drawString(tr("ボイス", "Voice", "语音"), 90,
                              screenItemTop + 18);
        homeCanvas.setTextSize(1);
        homeCanvas.setTextColor(TFT_LIGHTGREY, rowBg(item));
        homeCanvas.drawString(
            voiceMode == 0
                ? tr("ピコピコ(高速)", "Chirps (fast)", "哔哔声(快速)")
                : tr("TTS(Workerの声)", "TTS (Worker voice)",
                     "TTS(Worker语音)"),
            90, screenItemTop + 46);
        break;
      case 5: {
        homeCanvas.drawString("WiFi", 90, screenItemTop + 18);
        homeCanvas.setTextSize(1);
        homeCanvas.setTextColor(TFT_CYAN, rowBg(item));
        const String currentWifi =
            WiFi.status() == WL_CONNECTED
                ? WiFi.SSID()
                : String(tr("未接続", "Not connected", "未连接"));
        homeCanvas.drawString(fitHomeText(currentWifi, 300), 90,
                              screenItemTop + 46);
        break;
      }
      case 6: {
        homeCanvas.drawString(tr("言語", "Language", "语言"), 90,
                              screenItemTop + 18);
        homeCanvas.setTextSize(1);
        homeCanvas.setTextColor(TFT_CYAN, rowBg(item));
        static constexpr const char *kLangLabels[] = {"日本語", "English",
                                                       "中文"};
        homeCanvas.drawString(
            kLangLabels[selectedLang < 3 ? selectedLang : 0], 90,
            screenItemTop + 46);
        break;
      }
    }
    homeCanvas.drawFastHLine(60, screenItemTop + 72, 346, 0x2124);
  }
  homeCanvas.clearClipRect();
}

static void drawHomePageDots() {
  for (int page = 0; page < 3; ++page) {
    const uint32_t color = page == homePage ? TFT_YELLOW : TFT_DARKGREY;
    homeCanvas.fillCircle(209 + page * 24, 446, 5, color);
  }
}

static void drawHome() {
  if (!homeCanvasReady) {
    homeCanvas.setColorDepth(8);
    homeCanvasReady =
        homeCanvas.createSprite(M5.Display.width(), M5.Display.height()) != nullptr;
  }
  if (!homeCanvasReady) {
    showStatus(tr("ホーム画面を表示できません", "Cannot show home screen",
                  "无法显示主屏幕"),
               TFT_RED);
    return;
  }

  homeCanvas.fillSprite(TFT_BLACK);
  homeCanvas.setFont(contentFont());
  homeCanvas.setTextDatum(middle_center);
  switch (homePage) {
    case 1:
      drawPageHistory();
      break;
    case 2:
      drawPageSettings();
      break;
    default:
      drawPageDashboard();
      break;
  }
  if (historyDetailIndex < 0) drawHomePageDots();
  homeCanvas.pushSprite(0, 0);
  homeDirty = false;
}

// Small pill at the top of the round screen showing what we're waiting on.
static void drawBusy(const char *label, uint32_t color) {
  const int w = 200, h = 32, x = (M5.Display.width() - w) / 2, y = 26;
  M5.Display.fillRoundRect(x, y, w, h, 16, TFT_BLACK);
  M5.Display.drawRoundRect(x, y, w, h, 16, color);
  M5.Display.setFont(contentFont());
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

static void stopSpeech() {
  stopAnimalese();
  M5.Speaker.stop();
  if (ttsBuf) {
    free(ttsBuf);
    ttsBuf = nullptr;
    ttsLen = 0;
  }
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
  stopSpeech();
  animText = text;
  animStopFlag = false;
  xTaskCreatePinnedToCore(animaleseWorker, "animalese", 4096, nullptr, 1,
                          &animTask, 0);
}

static void drawPhoto() {
  if (!jpegBuf) return;
  M5.Display.fillScreen(TFT_BLACK);
  const int sourceWidth = captureQuality == 1 ? 640 : 320;
  const int sourceHeight = captureQuality == 1 ? 480 : 240;
  const float sc = M5.Display.width() / static_cast<float>(sourceWidth);
  if (captureQuality == 1) {
    // drawJpg's fractional downscale renders a cropped view for VGA frames;
    // decode 1:1 into a PSRAM sprite, then zoom-blit to fill the panel width.
    M5Canvas photo(&M5.Display);
    photo.setPsram(true);
    photo.setColorDepth(16);
    if (photo.createSprite(sourceWidth, sourceHeight)) {
      photo.drawJpg(jpegBuf, jpegLen, 0, 0);
      photo.pushRotateZoom(M5.Display.width() / 2.0f,
                           M5.Display.height() / 2.0f, 0.0f, sc, sc);
      photo.deleteSprite();
      return;
    }
    // sprite allocation failed — fall back to the direct path below
  }
  M5.Display.drawJpg(jpegBuf, jpegLen, 0,
                     (int)((M5.Display.height() - sourceHeight * sc) / 2),
                     M5.Display.width(), (int)(sourceHeight * sc), 0, 0, sc,
                     sc);
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
  textCanvas.setFont(contentFont());

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
  if (full) {
    M5.Display.fillScreen(TFT_BLACK);
    // Bottom hint lives here so every full redraw (including the post-Q&A
    // restore) brings it back. y=424: the round display's chord there is
    // ±133px — the widest (EN) hint at ±120px still fits; y=442 clipped it.
    M5.Display.setFont(contentFont());
    M5.Display.setTextSize(1);
    M5.Display.setTextDatum(middle_center);
    M5.Display.setTextColor(TFT_DARKGREY, TFT_BLACK);
    M5.Display.drawString(
        tr("黄長押し:質問 黄:撮影 青:戻る",
           "Hold Y: ask  Y: shoot  B: back", "长按黄:提问 黄:拍摄 蓝:返回"),
        M5.Display.width() / 2, 424);
  }
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

static void onSntpSynced(struct timeval *) { sntpSynced = true; }

static void beginNtpSync() {
  setenv("TZ", "JST-9", 1);
  tzset();
  sntpSynced = false;
  sntp_set_time_sync_notification_cb(onSntpSynced);
  configTzTime("JST-9", "ntp.nict.jp", "pool.ntp.org");
  ntpSyncPending = true;
  Serial.println("[toi] ntp: sync requested");
}

static void pollNtpSync() {
  if (!ntpSyncPending || !sntpSynced) return;
  struct tm local {};
  if (!getLocalClock(local)) return;
  M5.Rtc.setDateTime(&local);
  ntpSyncPending = false;
  homeDirty = true;
  Serial.printf("[toi] ntp: synced, RTC updated %04d-%02d-%02d %02d:%02d:%02d\n",
                local.tm_year + 1900, local.tm_mon + 1, local.tm_mday,
                local.tm_hour, local.tm_min, local.tm_sec);
}

static bool connectWifi() {
  struct { const char *ssid, *pass; } slots[] = {
      {nvsWifiSsid.c_str(), nvsWifiPass.c_str()},
      {WIFI_SSID1, WIFI_PASS1},
      {WIFI_SSID2, WIFI_PASS2}};
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
  showStatus(tr("カメラをペアリング中...", "Pairing camera...",
                "正在配对相机..."));
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
  showStatus(tr("WiFi再接続中...", "WiFi reconnecting...",
                "正在重连WiFi..."));
  gNetOk = connectWifi();
  startSoftAp();
  powerCycleCamera();  // camera reboots and should join our SoftAP
  showStatus(ok ? tr("カメラの接続を待っています...",
                     "Waiting for camera...", "等待相机连接...")
                : tr("カメラを探しています...", "Searching for camera...",
                     "正在寻找相机..."));
  if (ok) {
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_ORANGE, TFT_BLACK);
    M5.Display.drawString(tr("LEDが消えなければGroveを抜き差し",
                             "LED stuck on? Re-plug Grove",
                             "LED不灭请重插Grove"),
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

static bool captureFromCam(bool useRetained) {
  free(jpegBuf);
  jpegBuf = nullptr;
  jpegLen = 0;

  if (useRetained && retainBuf && retainLen && millis() - retainAt < 2000) {
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
    lastError = tr("カメラ未接続", "Camera not connected", "相机未连接");
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
static WiFiClientSecure configClient;
static HTTPClient configHttp;
static bool configHttpInit = false;
static WiFiClientSecure ttsClient;
static HTTPClient ttsHttp;
static bool ttsHttpInit = false;
static WiFiClientSecure placeClient;
static HTTPClient placeHttp;
static bool placeHttpInit = false;
static WiFiClientSecure digestClient;
static HTTPClient digestHttp;
static bool digestHttpInit = false;

static bool fetchWorkerConfig() {
  if (WiFi.status() != WL_CONNECTED) return false;
  if (!configHttpInit) {
    configClient.setInsecure();  // same own-Worker TLS trade-off as /analyze
    configHttp.setReuse(true);
    configHttp.setConnectTimeout(5000);
    configHttp.setTimeout(5000);
    configHttpInit = true;
  }

  const String preferredName =
      toiPrefsReady ? toiPrefs.getString("modelName", selectedModelName())
                    : String(selectedModelName());
  int code = -1;
  if (!configHttp.begin(configClient, String(WORKER_URL) + "/config")) {
    Serial.println("[toi] config: begin failed");
    return false;
  }
  configHttp.addHeader("X-Device-Token", deviceToken());
  code = configHttp.GET();
  if (code != HTTP_CODE_OK) {
    configHttp.end();
    Serial.printf("[toi] config: HTTP %d\n", code);
    return false;
  }

  JsonDocument doc;
  if (deserializeJson(doc, configHttp.getString()) !=
      DeserializationError::Ok) {
    configHttp.end();
    Serial.println("[toi] config: invalid JSON");
    return false;
  }

  String nextModels[8];
  uint8_t nextCount = 0;
  for (JsonVariantConst value : doc["models"].as<JsonArrayConst>()) {
    if (nextCount >= 8) break;
    if (!value.is<const char *>()) continue;
    const String model = value.as<String>();
    if (model.length() == 0 || model.length() > 48 || model.indexOf(',') >= 0) {
      continue;
    }
    nextModels[nextCount++] = model;
  }
  if (!nextCount) {
    configHttp.end();
    Serial.println("[toi] config: no valid models");
    return false;
  }

  String rawModels;
  for (uint8_t i = 0; i < nextCount; ++i) {
    toiModels[i] = nextModels[i];
    if (i) rawModels += ',';
    rawModels += nextModels[i];
  }
  for (uint8_t i = nextCount; i < 8; ++i) toiModels[i] = "";
  toiModelCount = nextCount;
  if (toiPrefsReady) toiPrefs.putString("models", rawModels);
  selectModelByName(preferredName);
  homeDirty = true;
  Serial.printf("[toi] config: loaded %u models, selected=%s\n",
                (unsigned)toiModelCount, selectedModelName());
  return true;
}

static void retryWorkerConfigOnSettingsEntry() {
  if (toiModelCount || toiConfigSettingsRetryDone ||
      WiFi.status() != WL_CONNECTED) {
    return;
  }
  toiConfigSettingsRetryDone = true;
  fetchWorkerConfig();
}

static void speakViaTts(const String &text) {
  stopSpeech();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[toi] tts: WiFi unavailable, using chirps");
    speakAnimalese(text);
    return;
  }
  if (!ttsHttpInit) {
    ttsClient.setInsecure();  // same own-Worker TLS trade-off as /analyze
    ttsHttp.setReuse(true);
    ttsHttp.setConnectTimeout(5000);
    ttsHttp.setTimeout(30000);
    ttsHttpInit = true;
  }

  JsonDocument requestDoc;
  requestDoc["text"] = text;
  String body;
  serializeJson(requestDoc, body);

  int code = -1;
  if (ttsHttp.begin(ttsClient, String(WORKER_URL) + "/tts")) {
    ttsHttp.addHeader("Content-Type", "application/json");
    ttsHttp.addHeader("X-Device-Token", deviceToken());
    code = ttsHttp.POST(body);
    if (code == HTTP_CODE_OK) {
      constexpr size_t kMaxTtsWav = 2 * 1024 * 1024;
      const int contentLen = ttsHttp.getSize();
      if (contentLen > 0 && static_cast<size_t>(contentLen) <= kMaxTtsWav) {
        ttsBuf = readBody(ttsHttp, kMaxTtsWav, ttsLen);
        if (ttsBuf && ttsLen == static_cast<size_t>(contentLen) &&
            M5.Speaker.playWav(ttsBuf, ttsLen)) {
          Serial.printf("[toi] tts: playing %u bytes\n", (unsigned)ttsLen);
          return;  // ttsBuf stays alive until stopSpeech() is called.
        }
      } else {
        Serial.printf("[toi] tts: invalid content length %d\n", contentLen);
      }
    }
  }

  ttsHttp.end();
  stopSpeech();
  Serial.printf("[toi] tts: HTTP %d failed, using chirps\n", code);
  speakAnimalese(text);
}

static void speakText(const String &text) {
  if (voiceMode == 1) {
    speakViaTts(text);
  } else {
    speakAnimalese(text);
  }
}

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
  // Last-known values stay on screen if this request fails.
  const uint32_t t0 = millis();
  int code = -1;
  bool ok = false;
  if (placeHttp.begin(placeClient, url)) {
    placeHttp.addHeader("X-Device-Token", deviceToken());
    code = placeHttp.GET();
    if (code == HTTP_CODE_OK) {
      JsonDocument doc;
      if (deserializeJson(doc, placeHttp.getString()) ==
          DeserializationError::Ok) {
        homePlace = doc["place"].as<String>();
        homeShort = doc["short"].as<String>();
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

static bool fetchDigest() {
  if (WiFi.status() != WL_CONNECTED || !inquiryHistory.length() ||
      inquiryDigestCount == static_cast<int32_t>(inquiryToday)) {
    return false;
  }
  if (!digestHttpInit) {
    digestClient.setInsecure();  // same own-Worker TLS trade-off as /analyze
    digestHttp.setReuse(true);
    digestHttp.setConnectTimeout(8000);
    digestHttp.setTimeout(8000);
    digestHttpInit = true;
  }

  const size_t itemCount = inquiryHistoryLineCount();
  size_t itemsToSkip = itemCount > 50 ? itemCount - 50 : 0;
  JsonDocument requestDoc;
  JsonArray items = requestDoc["items"].to<JsonArray>();
  int start = 0;
  while (start < static_cast<int>(inquiryHistory.length())) {
    const int next = inquiryHistory.indexOf('\n', start);
    const int end = next >= 0 ? next : inquiryHistory.length();
    const String line = inquiryHistory.substring(start, end);
    const int captionStart = line.indexOf('|');
    const int captionEnd =
        captionStart >= 0 ? line.indexOf('|', captionStart + 1) : -1;
    if (itemsToSkip > 0) {
      --itemsToSkip;
    } else if (captionStart >= 0) {
      items.add(line.substring(
          captionStart + 1,
          captionEnd >= 0 ? captionEnd : static_cast<int>(line.length())));
    }
    if (next < 0) break;
    start = next + 1;
  }

  String body;
  serializeJson(requestDoc, body);
  const uint32_t t0 = millis();
  int code = -1;
  bool ok = false;
  if (digestHttp.begin(digestClient, String(WORKER_URL) + "/digest")) {
    digestHttp.addHeader("Content-Type", "application/json");
    digestHttp.addHeader("X-Device-Token", deviceToken());
    digestHttp.addHeader("X-Model", selectedModelName());
    digestHttp.addHeader("X-Lang", selectedLangCode());
    code = digestHttp.POST(body);
    if (code == HTTP_CODE_OK) {
      JsonDocument responseDoc;
      if (deserializeJson(responseDoc, digestHttp.getString()) ==
              DeserializationError::Ok &&
          responseDoc["summary"].is<const char *>()) {
        const String nextDigest = responseDoc["summary"].as<String>();
        const int32_t nextDigestCount = static_cast<int32_t>(inquiryToday);
        if (toiPrefsReady) {
          if (nextDigest != inquiryDigest) {
            toiPrefs.putString("digest", nextDigest);
          }
          if (nextDigestCount != inquiryDigestCount) {
            toiPrefs.putInt("digN", nextDigestCount);
          }
        }
        inquiryDigest = nextDigest;
        inquiryDigestCount = nextDigestCount;
        homeDirty = true;
        ok = true;
      }
    } else {
      digestHttp.end();  // discard a failed/stale keep-alive connection
    }
  }
  Serial.printf("[toi] digest: %lums HTTP %d summary=%u bytes\n", millis() - t0,
                code, (unsigned)inquiryDigest.length());
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
    analyzeHttp.addHeader("X-Device-Token", deviceToken());
    analyzeHttp.addHeader("X-Model", selectedModelName());
    analyzeHttp.addHeader("X-Detail", aiDetailHigh ? "high" : "low");
    analyzeHttp.addHeader("X-Lang", selectedLangCode());
    code = analyzeHttp.POST(jpegBuf, jpegLen);
    if (code == HTTP_CODE_OK) {
      JsonDocument doc;
      if (deserializeJson(doc, analyzeHttp.getString()) ==
          DeserializationError::Ok) {
        caption = doc["caption"].as<String>();
        detailText = doc["detail"].as<String>();
        ok = caption.length() > 0;
      }
    } else if (code == 429) {
      // Free-token quota exhausted — worker sends the JST reset time.
      JsonDocument doc;
      String resetAt;
      if (deserializeJson(doc, analyzeHttp.getString()) ==
          DeserializationError::Ok) {
        resetAt = doc["reset_jst"].as<String>();
      }
      lastError =
          resetAt.length()
              ? String(tr("AI無料枠が上限\n(",
                          "AI free quota exhausted\n(resets ~",
                          "AI免费额度已用完\n(约")) +
                    resetAt + tr("頃リセット)", ")", "重置)")
              : String(tr("AI無料枠が上限です", "AI free quota exhausted",
                          "AI免费额度已用完"));
      analyzeHttp.end();
      break;  // retrying is pointless until the quota resets
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
          M5.Display.setFont(contentFont());
          M5.Display.setTextSize(1);
          M5.Display.setTextDatum(middle_center);
          M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
          M5.Display.drawString(tr(" 黄:撮影 ", " Y: shoot ", " 黄:拍摄 "),
                                M5.Display.width() / 2, 430);
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
  const uint32_t tHold = millis();
  stopSpeech();
  // Users start talking the moment they feel the hold engage — every ms
  // before Mic.begin() is speech lost, so the codec swap happens FIRST and
  // the ready cue is visual (red banner). No pre-beep, no delay.
  M5.Speaker.end();  // mic and speaker share the codec/I2S
  if (!M5.Mic.begin()) {
    M5.Speaker.begin();
    applyPaBoost();
    M5.Speaker.setVolume(speakerVolume);
    Serial.println("[toi] ask: mic begin FAILED");
    return;
  }

  constexpr uint32_t kRate = 16000;
  constexpr size_t kMaxSamples = kRate * 10;  // up to 10s
  constexpr size_t kChunk = 1024;
  int16_t *pcm = (int16_t *)ps_malloc(kMaxSamples * 2 + 44);
  size_t total = 0;
  drawBusy(tr("録音中(離すと送信)", "Recording (release to send)",
              "录音中(松开发送)"),
           TFT_RED);
  Serial.printf("[toi] ask: mic live %lums after hold\n", millis() - tHold);
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
  applyPaBoost();
  M5.Speaker.setVolume(speakerVolume);
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

  drawBusy(tr("考え中...", "Thinking...", "思考中..."), TFT_CYAN);
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
      analyzeHttp.addHeader("X-Device-Token", deviceToken());
      analyzeHttp.addHeader("X-Model", selectedModelName());
      analyzeHttp.addHeader("X-Lang", selectedLangCode());
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
            recordInquiry("Q: " + q, a);
            caption = "Q: " + q;
            detailText = a;
            buildResultCanvas();
            drawResult(true);
            autoScrollAt = millis() + 2500;
            speakText(a);
            ok = true;
          }
        }
      } else {
        Serial.printf("[toi] ask: HTTP %d\n", code);
        if (code == 429) {
          drawBusy(tr("AI無料枠が上限です", "AI free quota exhausted",
                      "AI免费额度已用完"),
                   TFT_RED);
          delay(1800);
        }
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

static void enterHome(int targetPage = 0) {
  stopSpeech();
  streamStop();
  Serial.println("[toi] finder: stream stopped (home)");
  state = AppState::Home;
  homePage = constrain(targetPage, 0, 2);
  if (homePage == 2) retryWorkerConfigOnSettingsEntry();
  settingsPressedRow = -1;
  homeHistoryScrollY = 0;
  settingsScrollY = 0;
  historyDetailIndex = -1;
  homeTouchActive = false;
  homeVolumeDragging = false;
  homeHistoryScrolled = false;
  settingsScrolled = false;
  homeLastMinute = -1;
  placeLookupPending = true;
  lastPlaceAt = 0;
  digestLookupPending = true;
  lastDigestAt = 0;
  homeHadGpsFix = hasFreshGpsFix();
  homeDirty = true;
  drawHome();
}

static String escapeHtml(const String &value) {
  String escaped;
  escaped.reserve(value.length());
  for (size_t i = 0; i < value.length(); ++i) {
    switch (value[i]) {
      case '&':
        escaped += "&amp;";
        break;
      case '<':
        escaped += "&lt;";
        break;
      case '>':
        escaped += "&gt;";
        break;
      case '"':
        escaped += "&quot;";
        break;
      case '\'':
        escaped += "&#39;";
        break;
      default:
        escaped += value[i];
        break;
    }
  }
  return escaped;
}

static void scanWifiOptions() {
  constexpr int kMaxOptions = 10;
  String ssids[kMaxOptions];
  int32_t rssis[kMaxOptions] = {};
  int optionCount = 0;
  const int networkCount = WiFi.scanNetworks();

  for (int network = 0; network < networkCount; ++network) {
    const String ssid = WiFi.SSID(network);
    if (!ssid.length()) continue;
    const int32_t rssi = WiFi.RSSI(network);

    int existing = -1;
    for (int option = 0; option < optionCount; ++option) {
      if (ssids[option] == ssid) {
        existing = option;
        break;
      }
    }
    if (existing >= 0) {
      if (rssi <= rssis[existing]) continue;
      rssis[existing] = rssi;
      while (existing > 0 && rssis[existing] > rssis[existing - 1]) {
        const String previousSsid = ssids[existing - 1];
        const int32_t previousRssi = rssis[existing - 1];
        ssids[existing - 1] = ssids[existing];
        rssis[existing - 1] = rssis[existing];
        ssids[existing] = previousSsid;
        rssis[existing] = previousRssi;
        --existing;
      }
      continue;
    }

    int insertAt = 0;
    while (insertAt < optionCount && rssis[insertAt] >= rssi) ++insertAt;
    if (insertAt >= kMaxOptions) continue;
    const int last = min(optionCount, kMaxOptions - 1);
    for (int option = last; option > insertAt; --option) {
      ssids[option] = ssids[option - 1];
      rssis[option] = rssis[option - 1];
    }
    ssids[insertAt] = ssid;
    rssis[insertAt] = rssi;
    if (optionCount < kMaxOptions) ++optionCount;
  }

  wifiOptionsHtml = "";
  for (int option = 0; option < optionCount; ++option) {
    const String escapedSsid = escapeHtml(ssids[option]);
    wifiOptionsHtml += "<option value=\"" + escapedSsid + "\">" +
                       escapedSsid + " (" + String(rssis[option]) +
                       " dBm)</option>";
  }
  if (networkCount >= 0) WiFi.scanDelete();
  Serial.printf("[toi] wifi portal: scan=%d unique=%d\n", networkCount,
                optionCount);
}

static void drawWifiSetup() {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setFont(contentFont());
  M5.Display.setTextDatum(middle_center);
  M5.Display.setTextSize(2);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  // Round display: the visible chord at y=48 is only ~±136px, so the title
  // must stay short (size-2 "WiFi設定" = ±64px); longer wording gets clipped.
  M5.Display.drawString(tr("WiFi設定", "WiFi setup", "WiFi设置"),
                        M5.Display.width() / 2, 48);

  static constexpr const char *kWifiQr =
      "WIFI:T:WPA;S:ToiCamera;P:toi-cam-2026;;";
  constexpr int kQrWidth = 170;
  M5.Display.qrcode(kWifiQr, (M5.Display.width() - kQrWidth) / 2, 76,
                    kQrWidth);

  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.drawString(tr("1. スマホのWiFiで ToiCamera に接続",
                           "1. Join 'ToiCamera' WiFi on phone",
                           "1. 手机WiFi连接 ToiCamera"),
                        M5.Display.width() / 2, 266);
  M5.Display.drawString(tr("2. ブラウザで 192.168.4.1 を開く",
                           "2. Open 192.168.4.1 in browser",
                           "2. 浏览器打开 192.168.4.1"),
                        M5.Display.width() / 2, 294);
  const String currentWifi = WiFi.status() == WL_CONNECTED
                                 ? WiFi.SSID()
                                 : String(tr("未接続", "Not connected", "未连接"));
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.drawString(String(tr("現在: ", "Now: ", "当前: ")) + currentWifi,
                        M5.Display.width() / 2, 334);
  M5.Display.setTextColor(TFT_DARKGREY, TFT_BLACK);
  // y=408 keeps the whole hint inside the circle (chord ±154 there).
  M5.Display.drawString(tr("青:戻る", "B: back", "蓝:返回"),
                        M5.Display.width() / 2, 408);
}

static bool saveWifiCredentials(const String &ssid, const String &pass) {
  if (!toiPrefsReady) return false;
  bool saved = true;
  if (ssid != nvsWifiSsid) {
    // putString returns bytes written — compare with the value length so an
    // empty password (open network) still counts as success.
    if (toiPrefs.putString("wifi_ssid", ssid) == ssid.length()) {
      nvsWifiSsid = ssid;
    } else {
      saved = false;
    }
  }
  if (pass != nvsWifiPass) {
    if (toiPrefs.putString("wifi_pass", pass) == pass.length()) {
      nvsWifiPass = pass;
    } else {
      saved = false;
    }
  }
  return saved;
}

static void registerWifiPortalRoutes() {
  if (wifiPortalRoutesRegistered) return;

  wifiPortal.on("/", HTTP_GET, []() {
    String html = R"HTML(<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ToiCamera 設定</title>
<style>
body{margin:0;background:#111;color:#eee;font-family:sans-serif}
main{max-width:34rem;margin:auto;padding:2rem 1.25rem}
h1{color:#41d9ff;font-size:1.6rem}label{display:block;margin-top:1.2rem}
select,input,button{box-sizing:border-box;width:100%;margin-top:.45rem;padding:.8rem;
border:1px solid #555;border-radius:.5rem;background:#222;color:#fff;font-size:1rem}
button{margin-top:1.5rem;background:#087f9c;border-color:#41d9ff;font-weight:bold}
small{display:block;margin-top:.4rem;color:#9aa;line-height:1.5}
small a{color:#41d9ff}
</style></head><body><main><h1>ToiCamera 設定</h1>
<p style="color:#9aa">WiFi とデバイストークンを設定できます。変更したい項目だけ入力してください。</p>
<form method="post" action="/save">
<label for="ssid">周辺のWiFi</label><select id="ssid" name="ssid">
<option value="">選択してください</option>)HTML";
    html += wifiOptionsHtml;
    html += R"HTML(</select>
<label for="other_ssid">その他の SSID</label>
<input id="other_ssid" name="other_ssid" maxlength="32" autocomplete="off">
<label for="pass">パスワード</label>
<input id="pass" name="pass" type="password" maxlength="63" autocomplete="new-password">
<label for="token">デバイストークン(Worker 認証用・未入力なら変更しない)</label>
<input id="token" name="token" type="password" maxlength="128" autocomplete="off">
<small>自分でデプロイした Cloudflare Worker の DEVICE_TOKEN と同じ値を入れます。
OpenAI の API キーではありません(キーは Worker 側にのみ設定)。
詳細: <a href="https://aieo-product.github.io/ToiCamera/worker-setup.html"
target="_blank" rel="noopener">Worker 構築ガイド</a></small>
<button type="submit">保存</button></form></main></body></html>)HTML";
    wifiPortal.sendHeader("Cache-Control", "no-store");
    wifiPortal.send(200, "text/html; charset=utf-8", html);
  });

  wifiPortal.on("/save", HTTP_POST, []() {
    String ssid = wifiPortal.arg("ssid");
    const String otherSsid = wifiPortal.arg("other_ssid");
    if (otherSsid.length()) ssid = otherSsid;
    const String pass = wifiPortal.arg("pass");
    const String token = wifiPortal.arg("token");
    if (!ssid.length() && !token.length()) {
      wifiPortal.send(400, "text/html; charset=utf-8",
                      "<!doctype html><meta charset=\"utf-8\">"
                      "<p>SSID かデバイストークンを入力してください。</p>"
                      "<p><a href=\"/\">戻る</a></p>");
      return;
    }
    if (token.length()) {
      if (toiPrefsReady && token != nvsDeviceToken &&
          toiPrefs.putString("dev_token", token) == token.length()) {
        nvsDeviceToken = token;
        Serial.println("[toi] portal: device token updated");  // value never logged
      }
      if (!ssid.length()) {
        wifiPortal.send(200, "text/html; charset=utf-8",
                        "<!doctype html><meta charset=\"utf-8\">"
                        "<p>トークンを保存しました。ToiCamera を再起動します。</p>");
        showStatus(tr("保存しました\n再起動します...", "Saved\nRestarting...",
                      "已保存\n正在重启..."),
                   TFT_CYAN);
        delay(1500);
        ESP.restart();
        return;
      }
    }
    if (!saveWifiCredentials(ssid, pass)) {
      wifiPortal.send(500, "text/html; charset=utf-8",
                      "<!doctype html><meta charset=\"utf-8\">"
                      "<p>保存に失敗しました。もう一度お試しください。</p>"
                      "<p><a href=\"/\">戻る</a></p>");
      Serial.println("[toi] wifi portal: save failed");
      return;
    }
    wifiPortal.send(200, "text/html; charset=utf-8",
                    "<!doctype html><meta charset=\"utf-8\">"
                    "<p>保存しました。ToiCamera を再起動します。</p>");
    String loggedSsid = ssid;
    loggedSsid.replace("\r", " ");
    loggedSsid.replace("\n", " ");
    Serial.printf("[toi] wifi portal: saved ssid=%s\n", loggedSsid.c_str());
    showStatus(tr("保存しました\n再起動します...", "Saved\nRestarting...",
                  "已保存\n正在重启..."),
               TFT_CYAN);
    delay(1500);
    ESP.restart();
  });

  wifiPortalRoutesRegistered = true;
}

static void enterWifiSetup() {
  state = AppState::WifiSetup;
  streamStop();
  homeDirty = false;  // stale flag must not repaint Home over this screen
  drawWifiSetup();    // QR up first — the scan below blocks for seconds
  scanWifiOptions();
  registerWifiPortalRoutes();
  wifiPortal.begin();
  Serial.println("[toi] wifi portal: started on 192.168.4.1");
}

static void enterIdle() {
  state = AppState::Idle;
  if (!cameraDiscoveryDone) {
    cameraDiscoveryDone = true;
    showStatus(tr("カメラ探索中...", "Searching camera...",
                  "正在寻找相机..."));
    gCamOk = cameraReachable();
    if (!gCamOk) gCamOk = pairCamera();
    if (gCamOk) configureCamera();
  }
  showIdleWithWarnings(WiFi.status() == WL_CONNECTED, gCamOk);
}

static void rePairCamera() {
  streamStop();
  showStatus(tr("カメラ探索中...", "Searching camera...",
                "正在寻找相机..."));
  gCamOk = cameraReachable() || pairCamera();
  if (gCamOk) configureCamera();
  showIdleWithWarnings(WiFi.status() == WL_CONNECTED, gCamOk);
}

static void homeTick() {
  pollNtpSync();

  const bool gpsFix = hasFreshGpsFix();
  if (gpsFix != homeHadGpsFix) {
    homeHadGpsFix = gpsFix;
    homeDirty = true;  // restyle only — the last-known location stays visible
    if (gpsFix) placeLookupPending = true;
  }
  bool requestSent = false;
  if (gpsFix && WiFi.status() == WL_CONNECTED &&
      (placeLookupPending ||
       (lastPlaceAt && millis() - lastPlaceAt >= 5 * 60 * 1000UL))) {
    placeLookupPending = false;
    lastPlaceAt = millis();
    fetchHomePlace();
    requestSent = true;
  }
  if (!requestSent && WiFi.status() == WL_CONNECTED &&
      inquiryHistory.length() &&
      inquiryDigestCount != static_cast<int32_t>(inquiryToday) &&
      (digestLookupPending ||
       (lastDigestAt && millis() - lastDigestAt >= 5 * 60 * 1000UL))) {
    digestLookupPending = false;
    lastDigestAt = millis();
    fetchDigest();
  }

  struct tm local {};
  if (getLocalClock(local)) {
    const int32_t minuteKey =
        local.tm_yday * 24 * 60 + local.tm_hour * 60 + local.tm_min;
    if (minuteKey != homeLastMinute) {
      homeLastMinute = minuteKey;
      homeDirty = true;
      // Midnight rollover: reset the daily stats even with no new inquiry,
      // so "今日の問い" never shows yesterday's count.
      const int32_t dateKey = localDateKey();
      if (dateKey >= 0 && inquiryDateKey >= 0 && dateKey != inquiryDateKey) {
        const int32_t previousDateKey = inquiryDateKey;
        const uint32_t previousToday = inquiryToday;
        const String previousHistory = inquiryHistory;
        const String previousDigest = inquiryDigest;
        const int32_t previousDigestCount = inquiryDigestCount;
        inquiryDateKey = dateKey;
        inquiryToday = 0;
        inquiryHistory = "";
        homeHistoryScrollY = 0;
        historyDetailIndex = -1;
        inquiryDigest = "";
        inquiryDigestCount = -1;
        if (toiPrefsReady) {
          if (inquiryDateKey != previousDateKey) {
            toiPrefs.putInt("dkey", inquiryDateKey);
          }
          if (inquiryToday != previousToday) {
            toiPrefs.putUInt("today", inquiryToday);
          }
          if (inquiryDigest != previousDigest) {
            toiPrefs.putString("digest", inquiryDigest);
          }
          if (inquiryDigestCount != previousDigestCount) {
            toiPrefs.putInt("digN", inquiryDigestCount);
          }
        }
        saveInquiryHistory(previousHistory);
        Serial.println("[toi] inquiries: reset for new day");
      }
    }
  }
  if (homeDirty) drawHome();
}

static void setSpeakerVolumeFromTouch(int touchX) {
  const int sliderX = constrain(touchX, 190, 380);
  const uint8_t nextVolume =
      static_cast<uint8_t>(((sliderX - 190) * 255 + 95) / 190);
  if (nextVolume == speakerVolume) return;
  speakerVolume = nextVolume;
  M5.Speaker.setVolume(speakerVolume);
  homeDirty = true;
}

static void saveSpeakerVolume() {
  if (!toiPrefsReady || speakerVolume == savedSpeakerVolume) return;
  toiPrefs.putUChar("vol", speakerVolume);
  savedSpeakerVolume = speakerVolume;
  Serial.printf("[toi] volume: saved=%u\n", (unsigned)speakerVolume);
}

static void homeTouchTick() {
  const auto t = M5.Touch.getDetail();
  if (t.isPressed()) {
    if (!homeTouchActive) {
      homeTouchActive = true;
      homeTouchStartX = t.x;
      homeTouchStartY = t.y;
      homeTouchLastX = t.x;
      homeTouchLastY = t.y;
      homeHistoryScrollStartY = homeHistoryScrollY;
      homeHistoryScrolled = false;
      settingsScrollStartY = settingsScrollY;
      settingsScrolled = false;
      const int settingsItem =
          homePage == 2 ? settingsItemForY(t.y) : -1;
      // Slider gestures are captured so the full 0-255 range is reachable.
      homeVolumeDragging = settingsItem == 1 && t.x >= 160 && t.x <= 410;
      if (homeVolumeDragging) setSpeakerVolumeFromTouch(t.x);
      if (homePage == 2 && !homeVolumeDragging) {
        settingsPressedRow = settingsItem;
        if (settingsPressedRow >= 0) homeDirty = true;
      }
      return;
    }

    const int previousY = homeTouchLastY;
    homeTouchLastX = t.x;
    homeTouchLastY = t.y;
    if (homeVolumeDragging) {
      setSpeakerVolumeFromTouch(t.x);
      return;
    }

    if (homePage == 1 && historyDetailIndex < 0) {
      const int dx = homeTouchLastX - homeTouchStartX;
      const int dy = homeTouchLastY - homeTouchStartY;
      const int absDx = abs(dx);
      const int absDy = abs(dy);
      if (absDx > 12 && absDx * 2 > absDy * 3) {
        if (homeHistoryScrollY != homeHistoryScrollStartY) {
          homeHistoryScrollY = homeHistoryScrollStartY;
          homeDirty = true;
        }
      } else if (homeTouchLastY != previousY) {
        const int nextScroll = constrain(
            homeHistoryScrollY - (homeTouchLastY - previousY), 0,
            maxHomeHistoryScrollY());
        if (nextScroll != homeHistoryScrollY) {
          homeHistoryScrollY = nextScroll;
          homeHistoryScrolled = true;
          homeDirty = true;
        }
      }
    } else if (homePage == 1 && historyDetailIndex >= 0) {
      if (homeTouchLastY != previousY) {
        const int nextScroll = constrain(
            historyDetailScrollY - (homeTouchLastY - previousY), 0,
            historyDetailMaxScroll);
        if (nextScroll != historyDetailScrollY) {
          historyDetailScrollY = nextScroll;
          homeDirty = true;
        }
      }
    } else if (homePage == 2) {
      const int dx = homeTouchLastX - homeTouchStartX;
      const int dy = homeTouchLastY - homeTouchStartY;
      const int absDx = abs(dx);
      const int absDy = abs(dy);
      if (absDx > 12 && absDx * 2 > absDy * 3) {
        if (settingsScrollY != settingsScrollStartY) {
          settingsScrollY = settingsScrollStartY;
          homeDirty = true;
        }
      } else if (homeTouchLastY != previousY) {
        const int nextScroll =
            constrain(settingsScrollY - (homeTouchLastY - previousY), 0, 242);
        if (nextScroll != settingsScrollY) {
          settingsScrollY = nextScroll;
          settingsScrolled = true;
          homeDirty = true;
        }
      }
    }

    if (settingsPressedRow >= 0 &&
        (settingsScrolled || abs(t.x - homeTouchStartX) > 12 ||
         abs(t.y - homeTouchStartY) > 12 ||
         settingsItemForY(t.y) != settingsPressedRow)) {
      settingsPressedRow = -1;  // drifted or scrolled — cancel pending tap
      homeDirty = true;
    }
    return;
  }

  if (!homeTouchActive) return;
  const int dx = homeTouchLastX - homeTouchStartX;
  const int dy = homeTouchLastY - homeTouchStartY;
  const int absDx = abs(dx);
  const int absDy = abs(dy);
  const bool isSwipe = absDx >= 60 && absDx * 2 > absDy * 3;
  const bool isTap = dx * dx + dy * dy < 12 * 12;
  if (homeVolumeDragging) {
    saveSpeakerVolume();
  } else if (isSwipe) {
    if (homePage == 1) homeHistoryScrollY = homeHistoryScrollStartY;
    if (homePage == 2) settingsScrollY = settingsScrollStartY;
    historyDetailIndex = -1;
    const int nextPage = constrain(homePage + (dx < 0 ? 1 : -1), 0, 2);
    if (nextPage != homePage) {
      homePage = nextPage;
      if (homePage == 2) retryWorkerConfigOnSettingsEntry();
      homeDirty = true;
    }
  } else if (isTap) {
    if (homePage == 1) {
      if (historyDetailIndex >= 0) {
        historyDetailIndex = -1;
        homeDirty = true;
      } else if (!homeHistoryScrolled && homeTouchLastY >= 100 &&
                 homeTouchLastY < 380) {
        const int tappedIndex =
            (homeHistoryScrollY + homeTouchLastY - 100) / 56;
        if (tappedIndex >= 0 && tappedIndex < inquiryHistoryLineCount()) {
          historyDetailIndex = tappedIndex;
          historyDetailScrollY = 0;
          homeDirty = true;
        }
      }
    } else if (homePage == 2 && !settingsScrolled) {
      const int releasedRow = settingsPressedRow;
      settingsPressedRow = -1;
      homeDirty = true;
      if (releasedRow == 0) {
        selectedModel = (selectedModel + 1) % activeModelCount();
        if (toiPrefsReady) {
          toiPrefs.putString("modelName", selectedModelName());
        }
        Serial.printf("[toi] model: %s\n", selectedModelName());
      } else if (releasedRow == 2) {
        captureQuality = captureQuality == 0 ? 1 : 0;
        if (toiPrefsReady) toiPrefs.putUChar("qual", captureQuality);
        Serial.printf("[toi] quality: %s\n",
                      captureQuality == 1 ? "VGA" : "QVGA");
      } else if (releasedRow == 3) {
        aiDetailHigh = !aiDetailHigh;
        if (toiPrefsReady) toiPrefs.putUChar("aidetail", aiDetailHigh ? 1 : 0);
        Serial.printf("[toi] ai detail: %s\n", aiDetailHigh ? "high" : "low");
      } else if (releasedRow == 4) {
        voiceMode = voiceMode == 0 ? 1 : 0;
        if (toiPrefsReady) toiPrefs.putUChar("voice", voiceMode);
        Serial.printf("[toi] voice: %s\n",
                      voiceMode == 0 ? "chirps" : "tts");
      } else if (releasedRow == 5) {
        enterWifiSetup();
      } else if (releasedRow == 6) {
        selectedLang = (selectedLang + 1) % 3;
        if (toiPrefsReady) {
          toiPrefs.putUChar("lang", selectedLang);
          if (inquiryDigestCount != -1) toiPrefs.putInt("digN", -1);
        }
        inquiryDigestCount = -1;
        digestLookupPending = true;
        Serial.printf("[toi] language: %s\n", selectedLangCode());
      }
    }
  }
  if (settingsPressedRow >= 0) {
    settingsPressedRow = -1;  // swipe/drag release — drop the highlight
    homeDirty = true;
  }
  homeTouchActive = false;
  homeVolumeDragging = false;
  homeHistoryScrolled = false;
  settingsScrolled = false;
}

static void enterSleeping() {
  state = AppState::Sleeping;
  stopSpeech();
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
  showStatus(tr("WiFi接続中...", "Connecting WiFi...", "正在连接WiFi..."));
  gNetOk = connectWifi();
  startSoftAp();
  Serial.printf("[toi] wake: light sleep result=%d STA=%s\n", sleepResult,
                gNetOk ? "ok" : "FAIL");
  applyPaBoost();  // codec registers may have reset across light sleep
  enterHome();
}

static void enterError(const String &msg) {
  lastError = msg;
  state = AppState::Error;
  showStatus((String(tr("エラー: ", "Error: ", "错误: ")) + msg).c_str(),
             TFT_RED);
  M5.Display.setTextSize(1);
  M5.Display.drawString(tr("黄:再試行 青:戻る", "Y: retry  B: back",
                           "黄:重试 蓝:返回"),
                        M5.Display.width() / 2, 320);
}

// Blocking flows (capture cycle, state switches) run for seconds without
// M5.update(), so the release of the press that started them is first seen
// by the NEXT state's handler as wasClicked — firing a second action. Wait
// for release here and consume the stale edge.
static void flushButtons() {
  do {
    M5.update();
    delay(10);
  } while (M5.BtnA.isPressed() || M5.BtnB.isPressed());
}

static void runCaptureCycle() {
  const uint32_t cycleStart = millis();
  state = AppState::Capturing;
  stopSpeech();
  sfxShutter();

  drawBusy(tr("カメラ通信中", "Talking to camera", "与相机通信中"),
           TFT_YELLOW);
  bool captureOk = false;
  if (captureQuality == 1) {
    streamStop();
    const bool vgaOk =
        camGet("/api/v1/control?var=framesize&val=10");
    delay(400);
    captureOk = captureFromCam(false);
    const bool qvgaOk =
        camGet("/api/v1/control?var=framesize&val=6");
    Serial.printf("[toi] capture quality: VGA=%s restore-QVGA=%s\n",
                  vgaOk ? "ok" : "FAIL", qvgaOk ? "ok" : "FAIL");
  } else {
    captureOk = captureFromCam(true);
  }
  if (!captureOk) {
    sfxError();
    enterError(lastError.length()
                   ? lastError
                   : String(tr("カメラに接続できません", "Cannot reach camera",
                               "无法连接相机")));
    return;
  }
  {
    const uint32_t t0 = millis();
    drawPhoto();
    Serial.printf("[toi] drawJpg: %lums\n", millis() - t0);
  }

  state = AppState::Analyzing;
  drawBusy(tr("AI解析中...", "AI analyzing...", "AI解析中..."), TFT_CYAN);
  if (!analyzePhoto()) {
    sfxError();
    enterError(lastError.length()
                   ? lastError
                   : String(tr("解析に失敗しました", "Analysis failed",
                               "解析失败")));
    return;
  }

  recordInquiry(caption, detailText);

  buildResultCanvas();
  drawResult(true);
  autoScrollAt = millis() + 2500;
  state = AppState::Result;  // interactive immediately — speech runs in a task
  speakText(caption + "。" + detailText);
  Serial.printf("[toi] cycle total: %lums\n", millis() - cycleStart);
}

void setup() {
  auto cfg = M5.config();
  cfg.output_power = true;  // Grove 5V out — powers the CamS3
  M5.begin(cfg);
  M5.Power.setExtOutput(true);  // PMIC-gated 5V bus: enable explicitly
  M5.Display.setBrightness(200);
  Serial.begin(115200);
  restoreSystemClockFromRtc();
  toiPrefsReady = toiPrefs.begin("toi", false);
  if (toiPrefsReady) {
    inquiryTotal = toiPrefs.getUInt("total", 0);
    inquiryToday = toiPrefs.getUInt("today", 0);
    inquiryDateKey = toiPrefs.getInt("dkey", -1);
    const size_t historyLength = toiPrefs.getBytesLength("histb");
    if (historyLength > 0 && historyLength <= kInquiryHistoryMaxBytes) {
      char *historyData = static_cast<char *>(malloc(historyLength + 1));
      if (historyData) {
        const size_t bytesRead =
            toiPrefs.getBytes("histb", historyData, historyLength);
        historyData[bytesRead] = '\0';
        inquiryHistory = String(historyData);
        free(historyData);
      }
    }
    inquiryDigest = toiPrefs.getString("digest", "");
    inquiryDigestCount = toiPrefs.getInt("digN", -1);
    speakerVolume = toiPrefs.getUChar("vol", 255);
    savedSpeakerVolume = speakerVolume;
    paBoostPulses = toiPrefs.getUChar("paboost", 0);
    if (paBoostPulses > 3) paBoostPulses = 0;
    es8311DacBoost = toiPrefs.getUChar("dacboost", 1) != 0;
    captureQuality = toiPrefs.getUChar("qual", 0);
    if (captureQuality > 1) captureQuality = 0;
    loadModelSettings();
    selectedLang = toiPrefs.getUChar("lang", 0);
    if (selectedLang > 2) selectedLang = 0;
    aiDetailHigh = toiPrefs.getUChar("aidetail", 0) != 0;
    voiceMode = toiPrefs.getUChar("voice", 0);
    if (voiceMode > 1) voiceMode = 0;
    nvsWifiSsid = toiPrefs.getString("wifi_ssid", "");
    nvsWifiPass = toiPrefs.getString("wifi_pass", "");
    nvsDeviceToken = toiPrefs.getString("dev_token", "");
    Serial.printf("[toi] inquiries: loaded today=%lu total=%lu hist=%u bytes\n",
                  (unsigned long)inquiryToday, (unsigned long)inquiryTotal,
                  (unsigned)inquiryHistory.length());
  } else {
    Serial.println("[toi] inquiries: Preferences begin failed");
  }
  M5.Speaker.setVolume(speakerVolume);
  M5.Speaker.begin();
  applyPaBoost();
  // Hold-to-talk engages at 350ms (default 500) — the mic starts sooner
  // relative to speech onset, so first words are less likely to be lost.
  M5.BtnA.setHoldThresh(350);

  showStatus(tr("WiFi接続中...", "Connecting WiFi...", "正在连接WiFi..."));
  state = AppState::WifiConnecting;
  // Unit GPS v1.1 (AT6668) streams NMEA at 115200 — verified by raw dump
  // 2026-08-05 (9600 yielded framing garbage, sats never valid). RX/TX is
  // auto-detected: start with RX=G10, swap to RX=G11 if no NMEA arrives.
  Serial1.begin(115200, SERIAL_8N1, 10 /*RX*/, 11 /*TX*/);
  gpsSwapDeadline = millis() + 10000;
  WiFi.mode(WIFI_AP_STA);
  WiFi.setSleep(false);  // modem sleep adds 100-300ms bursts to every request
  gNetOk = connectWifi();  // internet is only needed for the AI call
  if (gNetOk) fetchWorkerConfig();
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
    else if (cmd == 'v') {
      paBoostPulses = (paBoostPulses + 1) % 4;
      if (toiPrefsReady) toiPrefs.putUChar("paboost", paBoostPulses);
      M5.Speaker.end();
      M5.Speaker.begin();
      applyPaBoost();
      M5.Speaker.setVolume(speakerVolume);
      volumeTestFeedback("PA " + String(paBoostPulses));
    } else if (cmd == 'V') {
      es8311DacBoost = !es8311DacBoost;
      if (toiPrefsReady) toiPrefs.putUChar("dacboost", es8311DacBoost ? 1 : 0);
      const uint8_t dacVolume = es8311DacBoost ? 0xD3 : 0xBF;
      m5::In_I2C.writeRegister8(0x18, 0x32, dacVolume, 400000);
      Serial.printf("[toi] es8311: dacvol=0x%02X\n", dacVolume);
      volumeTestFeedback(es8311DacBoost ? "DAC +10dB" : "DAC 0dB");
    }
    else if (cmd == 'g') {
      // Raw GPS dump — 2s of Serial1 as hex+ascii, to diagnose baud/wiring.
      Serial.println("[toi] gps raw dump (2s):");
      const uint32_t until = millis() + 2000;
      String ascii;
      int n = 0;
      while (millis() < until) {
        while (Serial1.available()) {
          const uint8_t b = Serial1.read();
          ++n;
          Serial.printf("%02X ", b);
          ascii += (b >= 32 && b < 127) ? (char)b : '.';
          if (n % 24 == 0) {
            Serial.printf("  |%s|\n", ascii.c_str());
            ascii = "";
          }
        }
        delay(2);
      }
      if (ascii.length()) Serial.printf("  |%s|\n", ascii.c_str());
      Serial.printf("[toi] gps raw dump end (%d bytes)\n", n);
    } else if (cmd == 'G') {
      // Cycle GPS baud 9600 -> 38400 -> 115200 (persists until reboot).
      static const uint32_t kBauds[] = {115200, 9600, 38400};
      static int baudIdx = 0;
      baudIdx = (baudIdx + 1) % 3;
      Serial1.end();
      Serial1.begin(kBauds[baudIdx], SERIAL_8N1, gpsPinsSwapped ? 11 : 10,
                    gpsPinsSwapped ? 10 : 11);
      Serial.printf("[toi] gps: baud=%lu\n", (unsigned long)kBauds[baudIdx]);
    }
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
    Serial1.begin(115200, SERIAL_8N1, 11 /*RX*/, 10 /*TX*/);
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
    case AppState::Home: {
      if (M5.BtnA.wasPressed()) {
        enterIdle();
        break;
      }
      if (M5.BtnB.wasPressed()) {
        enterSleeping();
        break;
      }
      homeTouchTick();
      // A tap may have transitioned into WifiSetup — homeTick() would
      // repaint the settings page over the QR screen via a stale homeDirty.
      if (state == AppState::Home) homeTick();
      break;
    }

    case AppState::WifiSetup:
      wifiPortal.handleClient();
      if (M5.BtnB.wasPressed()) {
        wifiPortal.stop();
        Serial.println("[toi] wifi portal: stopped");
        enterHome(2);
        flushButtons();
      }
      break;

    case AppState::Idle:
      if (M5.BtnA.wasPressed()) {
        runCaptureCycle();
        flushButtons();  // eat the release edge — else Result re-captures
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
        flushButtons();
        break;
      }
      if (M5.BtnB.wasPressed()) {
        // Cancel: stop speech, back to the finder
        stopSpeech();
        sfxCancel();
        enterIdle();
        flushButtons();  // eat the release — else Idle sees BtnB click -> Home
        break;
      }
      // Touch drag scroll — track absolute Y between frames (deltaY from the
      // touch driver proved unreliable on this panel)
      static int lastTouchY = -1;
      auto t = M5.Touch.getDetail();
      const int viewH = M5.Display.height() - 150;
      // +20px pad so the last line always scrolls clear of the bottom hint.
      const int maxScroll = max(0, textCanvasHeight - viewH + 20);
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
        flushButtons();
        break;
      }
      if (M5.BtnA.wasPressed()) {
        if (WiFi.status() != WL_CONNECTED) {
          showStatus(
              tr("WiFi接続中...", "Connecting WiFi...", "正在连接WiFi..."));
          gNetOk = connectWifi();
          if (!gNetOk) {
            enterError(tr("WiFiに接続できません", "Cannot connect WiFi",
                          "无法连接WiFi"));
            break;
          }
        }
        runCaptureCycle();
        flushButtons();
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

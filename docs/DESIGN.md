# ToiCamera 設計書

M5Stack Global Innovation Contest 2026 応募作品「ToiCamera」の設計文書。
実装の単一の正典はコードとし、本書はアーキテクチャ判断とその理由を記録する。

- 提出締切: **2026-08-07 23:59 PST**(Hackster.io 英語記事 + Google Form、両方必須)
- 審査基準: Creativity / Functionality / Documentation / Impact(4本柱・等配点)

## 1. コンセプト

「黄ボタンを押すだけで、撮ったものを AI が日本語で解説してくれる小さなカメラ」。

**名称の由来**: ToiCamera = 「問い(Toi)」×「Toy」。AI に"問い"を投げるおもちゃの
ようなカメラ、というダブルミーニング。英語圏でも "toy camera" と音が重なり覚えやすい。

M5Stack Stopwatch の円形 AMOLED をコンパクトカメラの背面モニタに、Unit CamS3 を
レンズに見立てた 3D プリントボディに収める。シャッター(KEYA 黄)→ 撮影画像表示 →
AI 解説のテキスト表示 + スピーカー読み上げ、という一連の体験を 4〜8 秒で完結させる。

## 2. ハードウェア構成

| 役割 | デバイス | 要点 |
|---|---|---|
| ホスト/UI | M5Stack Stopwatch Dev Kit (SKU C152) | ESP32-S3R8、16MB Flash / 8MB PSRAM、466×466 円形 AMOLED(CO5300/QSPI)、CST820B タッチ、ES8311+AW8737A+1W スピーカー、マイク、KEYA=G2(黄)/KEYB=G1(青)、Grove=GND/5V/G10/G11 |
| カメラ | M5Stack Unit CamS3 | ESP32-S3 N16R8、**5MP 版で確定**(実機検証済み)、microSD、バッテリーなし。**カスタムファーム**(公式 UserDemo + STA サーバーパッチ)で運用 |
| (Phase 1.5) 位置情報 | Unit GPS v1.1 (SKU U032-V11) | AT6668、UART Grove、48×24mm |

### 接続(Phase 1 / MVP)

- Grove ケーブルは **5V/GND のみ結線**(給電専用)。CamS3 の Grove データピンは
  USB D+/D-(G20/G19)であり、GPIO 信号を流し込まない
- 画像データは **Stopwatch 自身が立てる専用 AP** 経由の HTTP で受け渡す
  (自宅ルーター・PC・スマホはカメラ経路に一切関与しない)

詳細は [`wiring.md`](wiring.md)。

## 3. システムアーキテクチャ

```
┌─────────────┐   Grove(5V給電のみ)    ┌──────────┐
│  Stopwatch  │═════════════════════│  CamS3   │
│  SoftAP+STA │◀─ WiFi: 専用AP ────── │(カスタムFW│
│ AMOLED/SPK  │   "ToiCamera"         │ STAサーバー)│
└──────┬──────┘   192.168.4.0/24      └──────────┘
       │              GET /api/v1/capture (JPEG)
       │ WiFi(STA): 自宅 or テザリング
       └─ HTTPS POST /analyze ─▶ Cloudflare Worker ─▶ AI vision
          HTTPS POST /tts ─────▶ (API キーは Worker 秘匿) ─▶ OpenAI TTS → WAV
```

Stopwatch は ESP32 の **SoftAP+STA 同時動作**を使い、カメラ収容(AP)とクラウド
接続(STA)を 1 チップで両立する。屋外はスマホテザリングだけで完結する。

### 採用理由(主要な設計判断)

| 判断 | 採用 | 理由 / 棄却案 |
|---|---|---|
| 画像の受け渡し | Stopwatch の SoftAP に カメラを収容(WiFi HTTP) | 当初の「同一 LAN」案はルーター依存と初回設定の煩雑さで棄却(ユーザー要望)。UART 化は両側カスタム FW + USB ピン転用のリスクがあるため Phase 2 のストレッチ。SoftAP は **stock サブネット(192.168.4.1)必須** — softAPConfig で変更すると DHCP プールが追従せずクライアントが IP を取れない(実測) |
| カメラファームウェア | 公式 UserDemo への **STA サーバーパッチ**(`firmware/cams3/patches/0001`、101 行) | 工場ファームは STA モードで REST サーバーを起動しない(TCP 診断で port 80/81 拒否を確認)。接続失敗 30 秒で工場 AP モードへフォールバック(ロックアウト防止) |
| AI 呼び出し | Cloudflare Worker 中継 | API キーをデバイスに置かない。プロンプト・モデル切替・TTS 差し替えを再書き込みなしで実施可能。ESP32 側の TLS/JSON 実装が単純化 |
| 解析モデル | OpenAI 互換 API(vars `MAIN_API_BASE_URL`、既定 api.openai.com)。モデルメニューは vars `MODELS`(既定 `gpt-5.6-terra,gpt-5.6-luna`)で Worker が配信し、デバイスは `GET /config` で取得して `X-Model` で選択を返す | base URL を Cloudflare Tunnel 経由のローカル LLM(Ollama 等)に向け替え可能。モデル追加・切替は Worker 再デプロイのみでデバイス無関係 |
| TTS | OpenAI `gpt-4o-mini-tts` → WAV 24kHz mono | M5Unified Speaker は WAV/RAW のみ(MP3 デコーダ非搭載)。品質不満時は Google TTS `ja-JP-Neural2`(LINEAR16)へ Worker 側のみで差替 |
| 日本語表示 | M5GFX 内蔵 `efontJA_16` | 追加フォント資材なしで UTF-8 日本語描画。品質を上げたければ VLW 変換が後続手段 |
| デバイス→Worker TLS | `setInsecure()` | 自前 Worker のみに接続・送信物は画像+デバイストークンのみ。トレードオフを README に明記。将来はルート CA ピン留め |

## 4. コンポーネント設計

### 4.1 Stopwatch ファームウェア(`firmware/stopwatch/`)

単一スレッド状態機械(PlatformIO + Arduino + M5Unified):

```
BOOT → WIFI_CONNECTING → HOME
HOME --[KEYA 黄]--> IDLE(ファインダー) --[KEYA 黄]--> CAPTURING → ANALYZING → RESULT
HOME --[KEYB 青]--> SLEEPING --[KEYA/KEYB]--> WIFI_CONNECTING → HOME
IDLE --[KEYB 青]--> HOME
IDLE --[KEYB 青長押し]--> カメラ再探索/再ペアリング → IDLE
RESULT --[KEYA 黄]--> CAPTURING(再撮影)   RESULT --[KEYA 黄長押し]--> 音声質問
RESULT / ERROR --[KEYB 青]--> IDLE
任意状態 --失敗--> ERROR --[KEYA 黄]--> リトライ
```

- HOME / SLEEPING では MJPEG ストリームを停止。カメラ探索・初回ペアリングは
  起動時ではなく、最初の IDLE 進入時まで遅延する
- HOME は RTC/NTP 時計・バッテリー・GPS 地名/最寄駅・ソフトウェア歩数を表示し、
  1 分ごとまたは表示データ更新時だけ M5Canvas から再描画する
- バッファは全て PSRAM(`ps_malloc`): JPEG ≤2MB、WAV ≤4MB。撮影サイクル毎に解放
- 表示: `drawJpg`(scale-to-fit)、解説文は 320px 幅の 8bit `M5Canvas` に禁則付き
  折返し描画し、タッチドラッグ+自動スクロール
- WiFi は 2 スロット(自宅 + テザリング)をビルドフラグ(`secrets.ini`、gitignore)で注入

### 4.2 CamS3 ファームウェア(`firmware/cams3/`)— カスタム(2026-07-28 実機稼働確認)

**変種は 5MP で確定**(2026-06-02 実機検証。ベース =
[m5stack/UnitCamS3-UserDemo](https://github.com/m5stack/UnitCamS3-UserDemo)
branch `unitcams3-5mp`、MIT ライセンス)。

工場ファームの STA モードは EzData poster 専用で **REST サーバーが起動しない**
(TCP 診断で確定)ため、第 3 の起動モードを追加するパッチを作成した:

- 起動分岐: `startPoster=="yes"` → poster / `wifiSsid` 設定あり → **STA サーバー
  (新設)** / それ以外 → 工場 AP モード
- STA サーバー: 保存済み SSID(= Stopwatch の SoftAP)に接続し、工場 AP モードと
  同一の REST API 群(`/api/v1/capture` 等)を提供。**接続 30 秒失敗で AP モードへ
  フォールバック**(ロックアウト防止)。LED は接続中点滅 → 確立で点灯
- ビルド: `firmware/cams3/build.sh`(ESP-IDF v5.1.4 + uv の Python 3.11。
  esp_insights の SHA_SIZE バグ修正を自動適用)。書き込みは USB-C、`erase-flash`
  で設定を初期化してから焼く(→ AP モードで起動しペアリング可能な状態になる)

**露出の罠**: 工場初期値は awb/aec/agc 全 OFF で画像が真っ黒(実機検証)。
Stopwatch 側が初回ファインダー進入時に `configureCamera()` で自動露出 ON +
QVGA/quality 1 を適用する。

**再起動の制約**: Grove 5V は常時給電(ALWAYS_ON)で Stopwatch からの電源断は
不可。設定反映のカメラ再起動は USB 経由(esptool reset)か Grove/USB の物理
抜き差しで行う(ペアリング完了画面にその案内を表示)。

手順・API リファレンス: `firmware/cams3/README.md`

### 4.2b ペアリングフロー(初回のみ・全自動)

```
Stopwatch 起動 → HOME → 黄ボタンで初回ファインダー進入
  → カメラ探索(SoftAP の DHCP リース .2〜.12 を probe)
  → 見つからない場合:
      工場 AP "UnitCamS3-WiFi" に直接 join(3 回試行)
      → POST set_config {wifiSsid: "ToiCamera", startPoster: "no"}(readback 検証)
      → 自 AP+STA 復帰 → カメラ再起動(USB reset or 抜き差し)を待つ
      → カメラが SoftAP に参加 → 発見 → configureCamera()
ファインダーで青長押し: 手動再探索/再ペアリング
```

### 4.3 AI 中継 Worker(`worker/`)

| Endpoint | 認証 | 入力 | 出力 |
|---|---|---|---|
| `GET /health` | なし | — | `{ok, model}` |
| `GET /config` | `X-Device-Token` | — | `{models, voice, tts}` — Worker が提供するモデルメニューと TTS 声名(ファームは NVS にキャッシュ) |
| `POST /analyze` | `X-Device-Token` | raw `image/jpeg` | `{caption(≤15字), detail(≤150字)}` — structured outputs(json_schema)でスキーマ強制 |
| `POST /ask` | `X-Device-Token` | raw `audio/wav` + query `caption`, `detail` | `{question, answer}` — STT で文字起こし後、写真の文脈で回答 |
| `GET /place` | `X-Device-Token` | query `lat`, `lon` | `{place, station, distance_m, walk_min}` — 地名 + 最寄駅/徒歩分(取得失敗時は駅情報を空で返す) |
| `POST /digest` | `X-Device-Token` | `{items: string[]}` | `{summary}` — 撮影/質問見出しから今日の行動を 1 文要約 |
| `POST /tts` | `X-Device-Token` | `{text}` | `audio/wav`(パススルーストリーム) |

シークレット(`wrangler secret`): `TOICAMERA_MAIN_API_KEY`(チャット/画像解説の
バックエンド用。STT の認証にも使われるため、音声質問を使うには OpenAI で有効な
キーが必要)/ `TOICAMERA_TTS_API_KEY`(TTS 用。未設定ならチャープ音フォールバック)/
`DEVICE_TOKEN`。
vars: `MODELS` / `TTS_VOICE` / `TTS_MODEL` / `MAIN_API_BASE_URL`(チャット系の
接続先。ローカル LLM に向けても STT/TTS は `AUDIO_API_BASE_URL`(既定
api.openai.com)に接続する)/ `ANALYZE_MAX_TOKENS` / `ANALYZE_STYLE_LOW` /
`ANALYZE_STYLE_HIGH`。

### 4.4 ケース(`case/`)

LEGO 互換バックプレート、Bambu Lab X2D で印刷。Blender スクリプト
(`case/blender/build_case.py`)から生成した STL(`case/blender/out/*.stl`)を配布。クリアランス +0.3mm、2 イテレーション想定。詳細は `case/README.md`。

## 5. 性能・容量見積り

- E2E レイテンシ目標 4〜8 秒: 撮影 0.3s + アップロード 0.5〜1s(SVGA ~100KB)+
  LLM 解析 1.5〜3s + TTS 1〜3s + 音声 DL 0.5〜1s
- PSRAM ピーク <5MB / 8MB(JPEG 0.5MB + フレームバッファ 0.43MB + キャンバス
  0.45MB + WAV ≤3MB)
- CamS3 消費電流: 撮影/WiFi ピーク 200〜400mA(Stopwatch 5V レールから供給、
  450mAh バッテリー駆動時間は実測で確認)

## 6. 拡張計画

| フェーズ | 内容 | 条件 |
|---|---|---|
| Phase 1.5 | Unit GPS v1.1 で撮影位置を Worker に送り、地名を解説に注入。内蔵マイクで撮影後の音声質問(Worker で STT) | MVP(E2E)完成後。遅延時は無条件カット |
| Phase 2 | CamS3 の G19/G20 を GPIO マトリクスで UART 転用し Grove 1 本の単体完結型へ(921600bps、フレーム `[AA55][type][len][payload][crc16]`) | 1 日タイムボックス。eFuse は焼かない |

## 7. リスクと対策

1. ~~STA モードで HTTP サーバー不達~~ → **顕在化し解決済み**(カスタム STA サーバーパッチで克服、2026-07-28 実機確認)
2. **日本語 TTS 品質** → Worker 側のみで Google TTS へ差替可能な構造
3. **PSRAM 圧迫** → 状態遷移ごとのバッファ解放、SVGA 運用、音声長制限
4. **デモ時の WiFi 不調** → テザリング SSID を第 2 スロットに焼き込み、動画は事前収録
5. **印刷スケジュール** → ブラケット形状へのフォールバック

## 8. スケジュール(2026-07-23 → 08-07)

| 日 | マイルストーン |
|---|---|
| D1-D2 (7/23-24) | scaffold(済)・センサー変種判別・CamS3 FW・Worker デプロイ |
| D3-D6 (7/25-28) | ✅ Worker 稼働(OpenAI 無料トークン)/ Stopwatch 実機稼働 / カメラ経路確立(カスタム FW) |
| **D7 (7/29)** | **E2E 完成 = MVP**(黄ボタン通し試験 → 10 被写体) |
| D8-D10 (7/30-8/1) | ケース CAD・印刷 #1→#2、Phase 1.5(任意) |
| D11 (8/2) | Phase 2 UART スパイク(タイムボックス) |
| D12-D14 (8/3-5) | デモ動画・Hackster 記事(EN)・リポジトリ public 化 |
| D15 (8/6) | Google Form 提出(1 日前倒し) |

クリティカルパス: 変種判別 → D7 E2E → 動画+記事。
カット順: UART → GPS/音声質問 → 疑似プレビュー → ケース 2 回目。

## 9. 検証方針

- Worker 単体: curl による `/analyze`(JSON スキーマ・日本語品質)・`/tts`(WAV 再生)確認
- CamS3 単体: `/capture` 連続 20 回取得の安定性
- E2E: 10 種類の被写体で通し試験、Grove 給電のみ(USB 非接続)でのバッテリー動作
- 提出物: リポジトリ public 化後の clone→build 再現テスト

検証エビデンス(写真・ログ)は dev-workflow の規約に従い各 issue / PR に添付する。

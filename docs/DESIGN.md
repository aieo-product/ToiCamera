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
| カメラ | M5Stack Unit CamS3 | ESP32-S3 N16R8、センサーは 2MP OV2640 または 5MP PY260(実機判別が必要)、microSD、バッテリーなし |
| (Phase 1.5) 位置情報 | Unit GPS v1.1 (SKU U032-V11) | AT6668、UART Grove、48×24mm |

### 接続(Phase 1 / MVP)

- Grove ケーブルは **5V/GND のみ結線**(給電専用)。CamS3 の Grove データピンは
  USB D+/D-(G20/G19)であり、GPIO 信号を流し込まない
- 画像データは WiFi(同一 LAN)経由の HTTP で受け渡す

詳細は [`wiring.md`](wiring.md)。

## 3. システムアーキテクチャ

```
┌─────────────┐  Grove(5V給電のみ)   ┌──────────┐
│  Stopwatch  │═══════════════════│  CamS3   │
│ AMOLED/SPK  │                    └────┬─────┘
└──────┬──────┘  WiFi(同一LAN)          │
       │←─── HTTP GET /capture(JPEG) ───┘
       └─ HTTPS POST /analyze ─▶ Cloudflare Worker ─▶ Claude vision
          HTTPS POST /tts ─────▶ (API キーは Worker 秘匿) ─▶ OpenAI TTS → WAV
```

### 採用理由(主要な設計判断)

| 判断 | 採用 | 理由 / 棄却案 |
|---|---|---|
| 画像の受け渡し | WiFi HTTP | CamS3 純正 FW に UART プロトコルが無く、Grove ピンは USB 専用。UART 化は両側カスタム FW + USB ピン転用のリスクがあるため Phase 2 のストレッチに格下げ |
| AI 呼び出し | Cloudflare Worker 中継 | API キーをデバイスに置かない。プロンプト・モデル切替・TTS 差し替えを再書き込みなしで実施可能。ESP32 側の TLS/JSON 実装が単純化 |
| 解析モデル | `claude-haiku-4-5`(env `MODEL` で切替) | 1.5〜3 秒・約 $0.002/枚。デモ動画収録時のみ上位モデルに切替 |
| TTS | OpenAI `gpt-4o-mini-tts` → WAV 24kHz mono | M5Unified Speaker は WAV/RAW のみ(MP3 デコーダ非搭載)。品質不満時は Google TTS `ja-JP-Neural2`(LINEAR16)へ Worker 側のみで差替 |
| 日本語表示 | M5GFX 内蔵 `efontJA_16` | 追加フォント資材なしで UTF-8 日本語描画。品質を上げたければ VLW 変換が後続手段 |
| デバイス→Worker TLS | `setInsecure()` | 自前 Worker のみに接続・送信物は画像+デバイストークンのみ。トレードオフを README に明記。将来はルート CA ピン留め |

## 4. コンポーネント設計

### 4.1 Stopwatch ファームウェア(`firmware/stopwatch/`)

単一スレッド状態機械(PlatformIO + Arduino + M5Unified):

```
BOOT → WIFI_CONNECTING → IDLE
IDLE --[KEYA]--> CAPTURING → (photo 表示) → ANALYZING → FETCHING_AUDIO → RESULT
RESULT --[KEYA]--> CAPTURING(再撮影)   RESULT --[KEYB]--> 音声リプレイ
任意状態 --失敗--> ERROR --[KEYA]--> リトライ
```

- バッファは全て PSRAM(`ps_malloc`): JPEG ≤2MB、WAV ≤4MB。撮影サイクル毎に解放
- 表示: `drawJpg`(scale-to-fit)、解説文は 320px 幅の 8bit `M5Canvas` に禁則付き
  折返し描画し、タッチドラッグ+自動スクロール
- WiFi は 2 スロット(自宅 + テザリング)をビルドフラグ(`secrets.ini`、gitignore)で注入

### 4.2 CamS3 ファームウェア(`firmware/cams3/`)

**変種は 5MP で確定**(過去プロジェクト
[vlogCamera](https://github.com/aieo-product/vlogCamera) の 2026-06-02 実機検証。
工場ファーム = `UnitCamS3-UserDemo` branch `unitcams3-5mp`)。

**MVP はカスタムファーム不要**: 工場ファームの REST API(`/api/v1/capture`・
`/api/v1/control`・`/api/v1/led_on|off`・`set_config` による STA 化)をそのまま使う。
Stopwatch 側が起動時に `configureCamera()` で露出設定(awb/aec/agc ON — 工場初期値は
全 OFF で画像が真っ黒になる既知の罠)と SVGA/q12 を適用する。

- 残検証: STA モードで HTTP サーバーが LAN 側 IP から叩けるか(go/no-go)
- フォールバック: vlogCamera の patch/overlay ビルド(ESP-IDF v5.1.4、WiFi 再接続
  ウォッチドッグ・AP フォールバック付き)を流用して改修版を焼く
- 手順・API リファレンス: `firmware/cams3/README.md`

### 4.3 AI 中継 Worker(`worker/`)

| Endpoint | 認証 | 入力 | 出力 |
|---|---|---|---|
| `GET /health` | なし | — | `{ok, model}` |
| `POST /analyze` | `X-Device-Token` | raw `image/jpeg` | `{caption(≤15字), detail(≤150字)}` — Claude structured outputs でスキーマ強制 |
| `POST /tts` | `X-Device-Token` | `{text}` | `audio/wav`(パススルーストリーム) |

シークレット(`wrangler secret`): `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `DEVICE_TOKEN`。
vars: `MODEL` / `TTS_VOICE`。

### 4.4 ケース(`case/`)

コンパクトカメラ型、Bambu Lab X2D で印刷。STEP + 3MF(Bambu Studio プロファイル)を
配布。クリアランス +0.3mm、2 イテレーション想定。詳細は `case/README.md`。

## 5. 性能・容量見積り

- E2E レイテンシ目標 4〜8 秒: 撮影 0.3s + アップロード 0.5〜1s(SVGA ~100KB)+
  Claude 1.5〜3s + TTS 1〜3s + 音声 DL 0.5〜1s
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

1. **STA モードで HTTP サーバー不達の可能性** → set_config で STA 化して LAN から `/api/v1/capture` を叩く go/no-go 検証を最優先。NG なら vlogCamera の patch ビルドで改修版を焼く
2. **日本語 TTS 品質** → Worker 側のみで Google TTS へ差替可能な構造
3. **PSRAM 圧迫** → 状態遷移ごとのバッファ解放、SVGA 運用、音声長制限
4. **デモ時の WiFi 不調** → テザリング SSID を第 2 スロットに焼き込み、動画は事前収録
5. **印刷スケジュール** → ブラケット形状へのフォールバック

## 8. スケジュール(2026-07-23 → 08-07)

| 日 | マイルストーン |
|---|---|
| D1-D2 (7/23-24) | scaffold(済)・センサー変種判別・CamS3 FW・Worker デプロイ |
| D3-D6 (7/25-28) | Stopwatch 実機ブリングアップ → 撮影表示 → AI 連携 → 音声 |
| **D7 (7/29)** | **E2E 完成 = MVP** |
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

# ToiCamera 引き継ぎ(2026-07-29 セッション終了時点)

> M5Stack Global Innovation Contest 2026 応募作品。**締切 2026-08-07 23:59 PST**
> (Hackster.io 英語記事 + Google Form、両方必須)。残り約 9 日。
> 正典: 設計=`docs/DESIGN.md` / カメラ制約=`firmware/cams3/README.md` / issue=#1〜#11(親 #9)

## 現在の到達点(MVP 動作中 🎉)

黄ボタン → 撮影(即時)→ AI 解説表示 → アニマルエーズ読み上げ → 黄長押しで音声質問、
の全機能が実機で動作確認済み。ユーザー評価: 「うごいた!」。

## アーキテクチャ(確定)

```
CamS3(カスタムFW) --WiFi: StopwatchのSoftAP "ToiCamera"(192.168.4.1)--> Stopwatch
Stopwatch --WiFi STA(自宅/テザリング)--> Cloudflare Worker(toicamera.take-otani.workers.dev)
Grove ケーブル = 5V 給電のみ(常時給電・切断制御は不可)
```

- ファインダー: カメラの MJPEG `/api/v1/stream` を購読、**HTTP デチャンク後に FFD8/FFD9 マーカーで
  フレーム再構成**(デチャンクを飛ばすと画像が横帯状に破損する。過去に実際に起きた)
- シャッター: 最後のファインダーフレームを流用(0ms・WYSIWYG)
- 解析: Worker `/analyze`(現在 **OpenAI gpt-5.6-luna**、無料学習トークン `OPENAI_FREE_API_KEY`、
  `detail:low`、strict json_schema)。GPS 測位時は `?lat=&lon=` で Nominatim 地名を注入(edge cache 7日)
- 音声: TTS 廃止 → **オンデバイス アニマルエーズ**(文字ごとチャープ+文イントネーション、FreeRTOS タスク)
- 音声質問: 黄長押し=録音(16kHz WAV)→ `/ask`(STT gpt-4o-mini-transcribe→whisper-1 fallback + 回答生成)

## ハードウェア既知事実(重要・再調査不要)

| 事実 | 詳細 |
|---|---|
| CamS3 = 5MP PY260(mega_ccm ドライバ) | **対応解像度は QVGA/VGA/HD/UXGA/FHD/5MP + 96/128/320 正方形のみ**。非対応値は「ok」を返すが無視される |
| quality レジスタ無反応 | 3 値どれでも QVGA≈80KB 固定 → フレーム縮小不可。ファインダー 2.5fps がセンサー上限 |
| 320x320 モード | 破損の主因はデチャンク前のパーサだった。現在未使用(必要なら再検証) |
| Grove 5V は ALWAYS_ON | `M5.Power.setExtOutput` での電源断は不可 → カメラ再起動は USB(esptool reset)か抜き差し |
| 工場FWの STA モード | REST サーバー起動せず(TCP 診断で確定)→ カスタムパッチ必須(適用済み) |
| StopWatch ボタン | KEYA(黄)=G2=BtnA / KEYB(青)=G1=BtnB。Grove=G10/G11 |
| GPS(Unit GPS v1.1) | Grove で NMEA 受信実績あり(RX=G10)。**現在シリアルで無音 — 接続要確認**。屋内では測位不可 |
| ArduinoJson | グローバル変数名 `detail` は namespace 衝突するので使わない(detailText に改名済み) |

## ビルド・書き込み(全て検証済みコマンド)

```bash
# Stopwatch(要 secrets.ini — gen-secrets.sh で生成、akc からトークン注入)
cd firmware/stopwatch && pio run -t upload --upload-port /dev/cu.usbmodem83101
# ポート特定: pio device list — Espressif VID 303A、SER=44:1B:F6:...=Stopwatch / 3C:DC:75:...=CamS3

# CamS3(ESP-IDF v5.1.4 + uv の python3.11 必須。brew python は ensurepip 破損)
cd firmware/cams3 && ./build.sh          # or build.sh flash(erase+flash=設定初期化→要再ペアリング)
# 設定温存で app だけ: build-tree/platforms/unitcam_s3_5mp で idf.py -p <port> flash

# Worker
cd worker && npx wrangler deploy         # シークレットは akc 経由(README 参照)

# シリアルデバッグ(Stopwatch): [toi] ログ、コマンド d=フレームdump(base64)/0-2=画質/a,b=QVGA,VGA
/opt/homebrew/Cellar/platformio/6.1.19_2/libexec/bin/python -c "import serial;..."  # pyserial は pio 同梱
```

## ペアリング挙動(実装済み・自動)

起動時にカメラ探索(SoftAP の DHCP .2〜.12)→ 見つからなければ工場 AP `UnitCamS3-WiFi` に
blind join → set_config(SSID=ToiCamera)→ カメラ再起動待ち(手動抜き差し or esptool reset が必要
= Grove 常時給電のため)。青ボタン=手動再探索。AP フォールバック時は 3 分で自動リブート再試行。
起動順レース対策済み(AP にクライアントが来たら自動再探索)。

## issue 状態(リポジトリ: aieo-product/ToiCamera、private)

- #1 CamS3 FW: ✅ 実質完了(クローズ前に安定性試験の記録推奨)
- #2 Worker: ✅ 実質完了(TTS 試聴は廃止により不要化)
- #3 ブリングアップ / #4 E2E=MVP: 動作 OK・**エビデンス(動画・10 被写体)未取得** ← 次の主作業
- #5 ケース(Bambu Lab X2D): 未着手。締切逆算で **7/30-8/1 に CAD/印刷必須**
- #6 Phase1.5: 音声質問 ✅ / GPS 配線再確認と屋外測位テスト残
- #7 UART / #8 提出物: 未着手(#8 は 8/3〜必着手)
- #10 ホーム画面(電池対策・時刻・現在地・歩数・最寄り駅・スリープ) / #11 設定画面(モデル・音量・画質): 今回 issue 化、未着手
- 音量: SW 上限 255 到達済み。物理改善は #11 のタスク 6(AW8737A ゲイン調査)

## 直近の推奨順序

1. #10 ホーム画面(電池問題はデモ撮影にも影響するため優先)+ #11 設定画面
2. GPS 復旧確認 → 屋外で位置入り解説の実証(#6 クローズ)
3. #5 ケース CAD・印刷(並行)
4. #4/#3 エビデンス取り → #8 デモ動画・Hackster 記事 → **8/6 提出**

## 運用メモ

- dev-workflow スキル運用中(issue コメントに判断トレース)。Codex ログイン済み(レビュー活用実績あり)
- Anthropic API はクレジット切れ。課金後 `--var ANALYZE_PROVIDER:anthropic` で Claude へ切替可
- デバイストークン: akc `TOICAMERA_DEVICE_TOKEN` / メモリ: `~/.claude/.../memory/toicamera-project.md` も更新済み

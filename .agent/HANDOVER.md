# ToiCamera 引き継ぎ(2026-07-29 夜 セッション時点)

> M5Stack Global Innovation Contest 2026 応募作品。**締切 2026-08-07 23:59 PST**
> (Hackster.io 英語記事 + Google Form、両方必須)。残り約 9 日。
> 正典: 設計=`docs/DESIGN.md` / カメラ制約=`firmware/cams3/README.md` / issue=#1〜#11(親 #9)

## ゴール

#10 ホーム画面 → #11 設定画面 → GPS 実証(#6) → ケース(#5) → エビデンス(#3/#4) → 提出物(#8)

## 完了(このセッション)

- **#10 実装完了 → PR #12**(ブランチ `feature/issue-10-home-screen`、未マージ)
  - コミット: `1127156`(本体・Codex 実装+親 Claude レビュー)+ `6eeb888`(レビュー指摘 2 件修正)
  - 内容: Home/Sleeping 状態、カメラ探索の初回ファインダー進入時への遅延、
    ストリーム停止ログ(`[toi] finder: stream stopped (home|sleep)`)、
    NTP(SNTP コールバックでゲート)→RX8130 RTC 同期、light sleep(GPIO G1/G2 wakeup)、
    SW 歩数(加速度ピーク検出。BMI270 HW step counter は M5Unified 非対応で見送り=検証記録済)、
    Worker `GET /place`(Nominatim+HeartRails 最寄り駅+徒歩分、edge cache 7日)
  - ボタン変更: Idle 青クリック=ホームへ / **再ペアリングは青長押しに移設**
  - 検証: `pio run` ✅ / `npm run typecheck` ✅ / Codex+Claude レビュー ✅ LGTM(PR コメント参照)

## 進行中・ブロッカー

- **Worker デプロイ未実施**(`npx wrangler deploy` が権限クラシファイアにブロック)。
  `/place` はデプロイまで実機で 404。変更は追加のみで後方互換
- **実機 E2E(/issue-test)未実施**: フラッシュ+ホーム→カメラ→スリープ→復帰の動画、
  ストリーム停止のシリアルログ、1 時間放置の電池比較 → PR #12 の LGTM 後にマージ依頼

## 未着手

- #11 設定画面 / #6 GPS 屋外実証(シリアル無音の配線確認から) / #5 ケース CAD(7/30-8/1 必須) / #7 / #8

## 次アクション(新セッション最初のコマンド)

1. `cd worker && npx wrangler deploy`(ユーザー承認つきで実行)
2. 実機フラッシュ: `cd firmware/stopwatch && pio run -t upload --upload-port /dev/cu.usbmodem83101`
3. `/issue-test https://github.com/aieo-product/ToiCamera/pull/12`(実機 E2E+エビデンス)
4. LGTM → 人間マージ → `/post-merge-test` → #11 へ

## 検証状態

- ビルド: firmware ✅(RAM 15.5%/Flash 25.0%)、worker typecheck ✅
- 実機: 未(light sleep 復帰後のカメラ再接続、SW 歩数精度、SoftAP 復帰が要確認ポイント)
- light sleep 中は USB CDC 切断(シリアルデバッグ時は注意)

## 申し送り(#10 実装の要注意点)

- MJPEG デチャンク・JPEG 再構成(`previewTick`/`feedJpeg`)は今回未変更(触るの禁止レベルで壊れやすい)
- NTP 同期は `sntp_set_time_sync_notification_cb` の `sntpSynced` フラグでゲート
  (`getLocalTime` だけだと RTC 復元済み起動で誤判定する — Codex P2 指摘対応済み)
- ホーム描画は 466x466 8bit M5Canvas(PSRAM)。efontJA_16 に絵文字グリフ無し

## 運用メモ(変更なし)

- ハードウェア既知事実・ビルドコマンド・ペアリング挙動は前回記載どおり
  (CamS3=PY260/QVGA 固定、Grove 5V ALWAYS_ON、KEYA=G2/KEYB=G1、GPS=Grove G10/G11 で現在無音)
- dev-workflow 運用中 / Codex ログイン済み / Anthropic API クレジット切れ
- デバイストークン: akc `TOICAMERA_DEVICE_TOKEN` / メモリ: `~/.claude/.../memory/toicamera-project.md`

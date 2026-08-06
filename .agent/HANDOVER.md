# ToiCamera 引き継ぎ(2026-08-06 昼 — 提出前日/最終調整セッションの店じまい)

> **締切: 2026-08-07 23:59 PST = 日本時間 8/8 15:59**。
> リポジトリは **public 化済み**(機密監査済・MIT LICENSE・README 刷新済)。
> 正典: `docs/DESIGN.md` / `firmware/cams3/README.md` / `case/README.md`

## いまの到達点

- **全機能実機動作**: 撮影→AI解説→アニマルエーズ / 音声Q&A(頭切れ修正済) / GPS測位(115200修正済・千代田区で実証) / ダッシュボード(問い数・歩数・要約・位置は都道府県+市区町村・最終測位保持) / スワイプ3ページ / 設定(モデル terra/luna・音量+10dBブースト・画質QVGA/VGA・AI精度low/high・WiFi/トークンQRポータル・言語ja/en/zh) / スリープ
- **main に全マージ済み**(PR #12,#15,#18,#21,#23,#26,#27,#28,#29,#33)。open PR: **#17(たまごっち・別セッション成果物。提出後にマージ判断、コンフリクト解消必要)**
- **デモ動画ドラフト1完成**: `userInput/ToiCamera_demo_EN_draft1.mp4`(2:12・英語キャプション)。動画最終化は**専用セッション**(`userInput/VIDEO_SESSION_PROMPT.md` を新セッションに貼る)
- **Hackster 記事 EN ドラフト**: `userInput/hackster-article-draft.md`(動画URL・記事URLのプレースホルダあり)
- **ケース STL 3 種**(`case/blender/out/`、全て検証PASS・印刷向き=レール面上の平置き):
  - `toicamera.stl` 2列12穴 / `toicamera_grid3.stl` 3列11穴・円内 / **`toicamera_duo.stl` v4 = 方位確定版**(N=ボタン/スピーカー側・ネジ左右±20・中央横ペア±8=カメラ縦置き・下段横ペア×2 z=-12=カメラ+GPS並列。**ジョイントは16mmスパン実測確定**)
  - **ネジ実測確定(2026-08-06): 元ネジ = M2×8mm** → プレート共締めは **M2×12 タッピングで確定(実機確認済 2026-08-06)**。頭形状は元ネジに合わせる(皿なら皿もみに収まる/なべなら次セッションで座ぐり変更可)
  - duo は印刷前確認待ち(レンダ送付済み)。生成: `/Applications/Blender.app/Contents/MacOS/Blender -b --python case/blender/build_case.py -- --part all --out case/blender/out/toicamera.stl`

## issue 状況(2026-08-06 午後 — 方針転換後・全 PR 済み)

1. **#30 行ズレ → 再現せず・close 済み**(90°回転写真の誤読。画素解析エビデンスは issue コメント+evidence ブランチ)
2. **#31 言語が効かない → Worker(/analyze x-lang:en curl 検証済・英語応答)・ファームコードとも異常なし**。最有力仮説=実機が言語対応ファーム反映前。**次回 Stopwatch(SER=44:1B:F6)接続時: PR マージ後の main を再フラッシュ → 言語タップで `[toi] language: en` → wrangler tail で x-lang 到達 → 英語解説確認で close**
3. **ユーザー方針転換(2026-08-06 昼)による新規 3 PR(いずれもレビュー済・マージはユーザー判断)**:
   - **PR #39**(#34): 設定画面を旧レイアウト(ラベル+下段値・78px ピッチ)+縦スクロールに再設計、アーク回避。Codex 実装+親レビュー+pio SUCCESS。**実機確認が残**
   - **PR #37**(#35+#36): 稼働 Worker 情報除去(gen-secrets.sh は `WORKER_URL=... ./gen-secrets.sh` 形式必須に変更)+ Worker 構築ガイド docs/worker-setup.md + Pages index
   - **PR #38**(#32): ポータルのトークン欄を「Worker 認証用」明記+ガイドリンク。pio SUCCESS
4. **GitHub Pages 有効化済み**: https://aieo-product.github.io/ToiCamera/ (main /docs 配信。**#37 マージまでルートは 404**、マージ後 1〜2 分でビルド)
5. マージ順の推奨: #37 → #38 → #39(#38 のリンクは #37 マージ後に有効化)。マージ後に Stopwatch 再フラッシュで #31/#34/#32 の実機確認を一括実施

## 次アクション(新セッション最初のコマンド)

1. `bash /Volumes/AIWorkSSD/AIWorkSpace/Skills/session-handover/scripts/state-dump.sh /Volumes/AIWorkSSD/AIWorkSpace/github/aieo-product/ToiCamera`
2. ユーザーのマージ判断確認 → PR #37/#38/#39 マージ → Stopwatch 接続時に再フラッシュ+実機確認(#31 言語 / #34 スクロール / #32 ポータル表示)(**ファーム作業は worktree `/Volumes/AIWorkSSD/AIWorkSpace/github/aieo-product/ToiCamera-wt11` を再利用可**。ブランチは main から切り直すこと。secrets.ini コピー済み・worker/node_modules は本体への symlink)
3. フラッシュ: `PORT=$(pio device list | grep -B3 "44:1B:F6" | grep "^/dev" | head -1)` → `pio run -t upload --upload-port $PORT`(Stopwatch SER=44:1B:F6 / CamS3=3C:DC:75。**繋ぎ直しでポート番号が変わる**)
4. Worker デプロイ: `cd worker && npx wrangler deploy`(伝播に十数秒〜、curl 検証は akc 経由: `export TOICAMERA_DEVICE_TOKEN=keychain://TOICAMERA_DEVICE_TOKEN && akc run -- sh -c 'curl -H "x-device-token: $TOICAMERA_DEVICE_TOKEN" ...'`)
5. 提出フロー: 動画セッションで最終書き出し → ユーザーが YouTube へ → 記事/README のリンク差し替え → Hackster 投稿 → **Google Form 提出(8/8 15:59 JSTまで)+受付スクショ**

## 検証状態・ハマりどころ(新規分のみ — 過去分は git log と各 README)

- 設定6行レイアウトは #30 のとおり描画ズレあり(言語・トークンポータル自体は動作確認済み。トークン保存→再起動→NVS優先も動作)
- Codex 委譲: `node ~/.claude/plugins/cache/openai-codex/codex/1.0.1/scripts/codex-companion.mjs task --background --write --fresh "<仕様>"`(**リポジトリ cwd で実行**。state は `~/.claude/plugins/data/codex-openai-codex/state/<dir名-hash>/jobs/`。監視は job json の status をポーリング)。実装後は必ず親レビュー+ビルド
- Blender 検証で duo のみシーン内に 0.1mm スライバ警告が出るが **エクスポート STL は非多様体 0 で PASS**(仕様: strict_mesh=False)
- ffmpeg: drawtext 無し→PNG オーバーレイ / ループ内 `-nostdin` 必須 / concat は再エンコード(詳細 `userInput/VIDEO_SESSION_PROMPT.md`)
- 無料枠(OPENAI_FREE_API_KEY)は 16:00 JST リセット。枯渇時はデバイスに「AI無料枠が上限(16:00頃リセット)」表示(有料フォールバックは撤去済み・ユーザー方針)
- akc: `TOICAMERA_DEVICE_TOKEN`。シークレット値は絶対にログ・コミットしない

## 運用

- dev-workflow 運用(issue コメントに判断トレース)。マージはユーザー指示ベース(今セッションは明示指示により実施)
- メモリ: `~/.claude/projects/.../memory/toicamera-project.md` も参照

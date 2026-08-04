# issue #13 チャレンジ設計: ぷにキャラ育成×ごはんカロリー記録(確定版 v2)

作成: 2026-08-04 / 設計・検証・レビュー: Claude(Fable=マネージャー) / 実装: Codex / 画像: gpt-image-2
v1 への敵対的チャレンジ(組込レンズ・スコープレンズ)反映済み。タイムボックス: 本日 1 日(超過時は画像品質未達でも打ち切り)。

## コンセプト

DQ スライム風「ぷにぷに丸生物」のドット絵キャラをホーム画面で飼う。
ごはんを撮ると食べて育ち、**食事カテゴリの分布で成体が5種に分岐**するたまごっち型育成。

## 進化ツリー(8 形態、form id 固定)

| id | 形態 | 条件 |
|---|---|---|
| 0 | たまぷに(赤ちゃん) | 初期 |
| 1 | すこやかぷに(子供A) | 累計3食時、(veg+seafood) >= (meat+sweet) |
| 2 | もりもりぷに(子供B) | 累計3食時、上記以外 |
| 3 | リーフぷに(成体) | 累計10食時、vegetable が有効食数の40%以上で最多 |
| 4 | マッスルぷに(成体) | 同、meat 最多 |
| 5 | マリンぷに(成体) | 同、seafood 最多 |
| 6 | キャンディぷに(成体) | 同、sweet 最多 |
| 7 | レインボーぷに(成体) | どのカテゴリも40%未満(バランス=隠れベスト) |

- 有効食数 = veg+meat+seafood+sweet(grain/other は total にのみ算入、分岐の分母から除外)
- 40%判定同率は id 小さい方。退化なし。成体後もカウント継続(Phase C 余地)
- **進化判定・カテゴリ集計は Arduino 非依存の純関数**(`src/character_logic.h`)に置き、
  ホスト(g++)で単体テスト実行(実機フラッシュ禁止下のデモ成果物)

## 食事カテゴリ(Worker LLM 判定)

RESULT_SCHEMA 追加フィールド(OpenAI strict + Anthropic output_config **両方**、全 required):

```
is_food: boolean / food_name: string("" if not food) / kcal_est: number(0 if not food)
food_category: enum ["vegetable","meat","seafood","sweet","grain","other"]  // 非食品は "other"
```

- SYSTEM_PROMPT に食品判定・1人前目安 kcal・主要素 1 カテゴリ選択の指示を追記
- FALLBACK_RESULT にも is_food:false/food_name:""/kcal_est:0/food_category:"other" を追加
- デバイス側パースは `doc["is_food"] | false` 等デフォルト付き(後方互換)

## デバイス状態(NVS)

- Preferences namespace "toichar"、**単一 struct を putBytes 1 発**(個別 put 禁止)
- 内容: version(u8), stage(u8), form(u8), cnt[6](u16), kcalDay(u32), dayKey(u32)
- 書込みタイミング: 給餌イベント時 + enterSleeping 時のみ(ループ毎書込み禁止)
- **dayKey sentinel ルール**: kcalDay リセットは「時刻有効(getLocalClock, tm_year>=125 ゲート)
  かつ 有効日付 != dayKey かつ dayKey != 0」のときのみ。時刻無効中の給餌は kcalDay 加算+
  dayKey=0(sentinel)とし、次回有効時刻でリセットせずに日付を採用(食事分を消さない)

## スプライト仕様

- 32x32 RGB332、透明キー 0xE3。形態ごと 4 フレーム: idle_a / idle_b(squash) / eat / happy
- ヘッダ: `firmware/stopwatch/src/sprites/<form>.h` + 集約 `sprites/sprites.h`
  (`ToiSpriteSet { idle_a, idle_b, eat, happy }` の form id 順テーブル `TOI_SPRITES[8]`、
  `TOI_SPR_SIZE=32`, `TOI_SPR_TRANSPARENT=0xE3`)。**プレースホルダ生成済み、シンボル名は固定契約**
- 描画: `homeCanvas.pushImageRotateZoom(232, 264, 16, 16, 0, 6.0f, 6.0f, 32, 32,
  (const uint8_t*)frame, (uint8_t)0xE3)` — **非AA版必須**(WithAA 禁止=にじむ)、
  透明キーは **uint8_t キャスト必須**(int で渡すと rgb888 解釈で透過不一致)
- 初回リリースは静止(idle_a)+食事演出のみ。ぷにぷに呼吸(idle_a/b 交互)は
  キャラ矩形 192x192 の部分描画で実装(フル drawHome 再描画の高頻度化は禁止)。時間切れ時は cut 可

## ホームレイアウト(確定)

battery y=40 / date y=80 / time y=130(上詰め)/ **キャラ x=136..328(偶数開始), y=168..360、
中心 (232,264)** / 歩数+当日kcal を 1 行統合 y=362(例「1234歩 ・ 560kcal」)/
地名・駅は 1 行統合または省略(円形クリップ内で調整)/ 設定ピル y=378 へ微下げ
(**タッチ判定定数も連動更新**、main.cpp L1441-1446)

## 食事演出

- フック: runCaptureCycle の analyzePhoto 成功後〜buildResultCanvas 間(main.cpp L1324-1326)
- eat→happy フレームを M5.Display 直描き+効果音 → 「たべた! +NNN kcal」約2秒
- **speakAnimalese(L1335)開始前に演出・効果音を完結**(音声タスク干渉防止)
- Result/Idle 画面への演出は禁止(feedJpeg の state==Idle 描画と競合)
- previewTick/feedJpeg は不変更(改変禁止)

## 画像パイプライン(gpt-image-2、工数圧縮版)

1. コンセプト画 8 形態(1024px 白背景ピクセルアート)→ Claude 目視判定、NG は再生成 **1 回まで**
2. アニメシート: 採用画を参照に /v1/images/edits で 2x2(idle/squash/eat/happy)、再生成 1 回まで。
   **失敗時フォールバック**: idle_a の機械派生(squash=縦75%圧縮、eat/happy=idle_a 流用)で前進
3. 変換: 4分割→トリム→32x32 LANCZOS→15色量子化→RGB332(0xE3 は 0xE2 へ強制置換済み=
  スクリプト実装済み)→ C 配列 + **RGB332 適用後プレビュー(preview332)で検収**
4. 検収: preview332 + 466x466 ホーム合成モック(実データ・確定レイアウト座標)を Claude 目視

## Worker 変更(Phase A)

- スキーマ・SYSTEM_PROMPT・FALLBACK_RESULT: 上記
- **analyzeWithOpenAI を「パース済み結果を返す」形にリファクタ**(Response 直返しをやめる)、
  handleAnalyze で `ctx.waitUntil(insert.catch(console.error))` → json(result)。Anthropic パスも同様に保存
- D1: binding `DB`、database_name "toicamera"、**database_id はプレースホルダ**(本番デプロイ禁止のため
  `wrangler d1 create` は実行しない)。`migrations/0001_create_meals.sql`:
  `meals(id INTEGER PK AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
  device_id TEXT, caption TEXT NOT NULL, detail TEXT NOT NULL, is_food INTEGER NOT NULL DEFAULT 0,
  food_name TEXT, kcal_est INTEGER, food_category TEXT, lat REAL, lon REAL, provider TEXT)`
  + created_at DESC index
- `GET /history?limit=N`(既定20、1..100 clamp、ORDER BY id DESC、is_food は boolean 化して返す)。
  **L459 の expectedMethod を GET 許可セット方式に変更**(忘れると 405)
- 認証は既存の共通ガード(X-Device-Token)がそのまま適用される
- `.dev.vars` はダミー値のみ(実シークレット書き込み禁止 = akc ルール)。`.dev.vars.example` を用意
- `worker/.gitignore` に `.wrangler/` と `.dev.vars` を追加
- 検証: `npm run typecheck` → `npx wrangler d1 migrations apply toicamera --local` →
  `npx wrangler dev` + curl(/history、可能なら /analyze 実打=OpenAI パスのみ)。
  **--remote / wrangler deploy は禁止**

## 実装順(デモ価値順、cut line 付き)

1. Worker Phase A(フル検証可能)
2. firmware 育成ロジック+レイアウト(**プレースホルダスプライトで pio run 通過まで**)
3. 画像生成・差し替え(並行実行、cuttable — 時間切れ時は絵が仮でも機能完成で着地)

## デモ成果物(実機フラッシュ禁止下)

(a) character_logic 純関数のホスト単体テスト実行ログ(進化分岐の全ケース)
(b) 各ステージの 466x466 ホーム合成モック PNG(実スプライトデータ)
(c) wrangler dev での /analyze→D1 INSERT→/history curl トランスクリプト
(d) 実機デモ用 NVS デバッグシード手段はシリアルコマンドで用意(小さければ実装、大きければ TODO)

## PR 明記事項(TODO)

- database_id プレースホルダのため本番 deploy は失敗する — マージ後に
  `wrangler d1 create toicamera` → id 反映 → `d1 migrations apply --remote` が必要
- Anthropic パスはスキーマ変更済みだが実打未検証
- マージ順: 提出完了後にユーザー判断(マージ依頼はしない)。実機フラッシュも提出後

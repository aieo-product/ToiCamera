# issue #13 引き継ぎ(チャレンジ案件・worktree ToiCamera-issue13)

> 2026-08-04 実施。メイン checkout は提出物ライン(#8)専用のため不可侵。
> 本番 Worker デプロイ禁止・実機フラッシュ禁止・main マージ禁止(提出後にユーザー判断)。

## 状態

- 実装完了: Worker Phase A + firmware Phase B(たまごっち育成)+ スプライト 8 形態
- 検証: worker typecheck ✅ / ローカル D1 + curl ✅ / ホスト単体テスト 56 checks ✅ /
  pio run ✅ (RAM 15.7% Flash 25.7%) / スプライト・ホームモック目視検収 ✅
- 未検証: 実機 E2E(フラッシュ禁止のため)/ Anthropic パス実打 / /analyze 実 API 打鍵
- 設計の正典: `.agent/ISSUE13_DESIGN.md`(敵対的チャレンジ反映済み v2)

## マージ後にやること(PR にも記載)

1. `wrangler d1 create toicamera` → wrangler.jsonc の database_id 差し替え
2. `npx wrangler d1 migrations apply toicamera --remote` → `npx wrangler deploy`
3. 実機フラッシュ → シリアル 'F' コマンドで育成デモ(カテゴリ巡回給餌)
4. 実機 E2E: ごはん撮影 → たべた!演出 → /history 確認

## 運用メモ

- スプライト差し替えは tools/sprites/README.md の手順で同名 .h 上書き
- NVS namespace "toichar" 単一 blob。レイアウト変更時は TOI_CHAR_VERSION を上げる
- 進化閾値: 3食で子供、10食で成体(character_logic.h の定数)

# AGENTS.md

このリポジトリでの開発は **issue 駆動ワークフロー（dev-workflow スキル）** に従います。
Codex CLI をはじめとする各 AI エージェントは、以下の規約とワークフロー正典に従って作業してください。

- 正典（エンジン非依存の手順書）: `/Users/takehiro/.claude/skills/dev-workflow/workflows/*.md`
- Claude Code 用エントリポイント: `/Users/takehiro/.claude/skills/dev-workflow/SKILL.md`
- 他エージェント（Codex 等）向け詳細規約: `/Users/takehiro/.claude/skills/dev-workflow/AGENTS.md`

## ワークフロー全体像（Step 0〜6）

- Step 0: 設計・タスク分解・issue 作成 … `workflows/issue-create.md`
- Step 1+2: 調査・対応方針 … `workflows/issue-investigate.md`
- Step 3: 実装・PR 作成（検証ゲート込み） … `workflows/issue-implement.md`
- Step 3.5: E2E テスト・エビデンス（投稿前ゲート込み） … `workflows/issue-test.md`
- Step 4: セルフレビュー … `workflows/pr-review.md`
- Step 4+: チャレンジレビュー … `workflows/pr-adversarial-review.md`
- Step 6: マージ後テスト … `workflows/post-merge-test.md`

## コマンド → ファイル対応

スラッシュコマンドが使えない環境では、該当する `workflows/<name>.md` を読み、手順に従ってください。

| コマンド | ファイル |
|---|---|
| /issue-create | workflows/issue-create.md |
| /issue-investigate | workflows/issue-investigate.md |
| /issue-implement | workflows/issue-implement.md |
| /issue-test | workflows/issue-test.md |
| /pr-review | workflows/pr-review.md |
| /pr-adversarial-review | workflows/pr-adversarial-review.md |
| /post-merge-test | workflows/post-merge-test.md |

## ツール対応（Claude Code ⇄ Codex/汎用）

| Claude Code | Codex/汎用 |
|---|---|
| AskUserQuestion | ユーザーに質問を提示し回答を待つ |
| Agent tool サブエージェント委譲 | インラインで順次実行 |
| playwright-mcp | playwright CLI スクリプト |
| /codex:review | `codex exec` またはセルフレビュー |
| upload-evidence 等のシェルスクリプト | 共通（そのまま利用） |

## 必須規範（エンジンに関係なく MUST）

- 判断トレース: `workflows/traceability.md`（T-8: 検証ゲートとマージ禁止を含む）
- Red/Green 検証ゲート: `workflows/redgreen.md`
- エビデンスゲート: `workflows/issue-test.md` Phase 4.5
- git 操作の安全規則: `workflows/git-ops.md`（force push 禁止 / main 直 push 禁止 / merge は人間のみ）

## モデルルーティング

- 単一モデル環境では N/A。詳細は `workflows/model-routing.md`。
- ただし git-ops の入出力契約・安全規則は同様に適用する。

## 設定

- 設定値の読み込み: `/Users/takehiro/.claude/skills/dev-workflow/scripts/load-config.sh`
- 設定ファイル: `config.toml` / `config.local.toml`

---

このファイルは dev-workflow の setup.sh が生成した縮約版です。プロジェクト固有の規約はこの下に追記してください。

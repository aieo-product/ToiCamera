# スプライト生成パイプライン (issue #13)

ぷにキャラ 8 形態のドット絵を gpt-image-2 で生成し、32x32 RGB332 の C 配列
(`firmware/stopwatch/src/sprites/*.h`) へ変換するツール群。

```bash
# 1. コンセプト画 (1024px, 白背景ピクセルアート)
export OPENAI_API_KEY=keychain://OPENAI_API_KEY
akc run -- python3 genimg.py gen concepts/baby.png prompts/baby.txt

# 2. アニメシート (2x2: idle/squash/eat/happy, コンセプト画を参照)
akc run -- python3 genimg.py edit sheets/baby.png sheets/baby_prompt.txt concepts/baby.png

# 3. 変換 (分割→32x32→15色量子化→RGB332, 透明キー0xE3は0xE2へ強制置換)
python3 convert_sprite.py sheet sheets/baby.png baby out/baby
#    シート品質が悪い場合の機械派生フォールバック:
python3 convert_sprite.py derive concepts/baby.png baby out/baby

# 4. 検収は out/<name>/<name>_preview332.png (実機色空間) で行う
# 5. ホーム画面モック (レイアウト座標は main.cpp drawHome と対応)
python3 make_home_mock.py out mocks
```

シンボル契約: `SPR_<FORM>_<FRAME>`、form id 順は `sprites/sprites.h` の
`TOI_SPRITES[8]` に固定(0=baby..7=rainbow)。差し替えは同名 .h の上書きのみ。

# ToiCamera ケース v3 — オープン型バックパックプレート

M5Stack StopWatch C152 をケースで囲わず、背面の上下 2 列のメスピンヘッダ外周へ小型プレートを差し込む構成です。画面、KEYA / KEYB、スピーカー、USB-C、電源ボタン、Grove ポートは完全に露出します。印刷物はバックパックプレート 1 枚だけで、Unit CamS3 は市販の M5Stack CLIP-A/B（LEGO Technic 互換）を介して取り付けます。

正本は [`blender/build_case.py`](blender/build_case.py) です。寸法は `PARAMS` に集約し、1 Blender Unit = 1 mm で STL を生成します。写真から推定したヘッダ寸法は必ず先にクーポンで確認してください。

## v3 構成

- **バックパックプレート**: 約 30.4 × 40 × 3 mm。背面視で右へ寄せ、右側は円形のウォッチ背面に沿う輪郭です。背面視左のスピーカー領域には出ません。
- **ヘッダクランプ**: 上下 2 列それぞれに、黒いヘッダハウジングの外周を上下から挟む、ウォッチ側へ開いた U 字（コの字）チャンネルを配置します。2.54 mm の穴へ FDM ピンを挿す構造ではありません。
- **CamS3 取付穴**: 外面に φ4.8 mm、8 mm ピッチの 2 × 2 貫通穴。CLIP-A/B の Technic ピンを使います。
- **GPS 予約穴**: 上側に同じ φ4.8 mm の 1 × 2 貫通穴。GPS は初期構成に含めず、半透明ゴーストで示す後付けオプションです。
- **ねじアクセス**: ウォッチ背面の 12 時 / 6 時ねじ中心を ±23.7 mm としてパラメータ化し、プレート上下端を ±20 mm に収めています。
- **配線**: 初期構成はウォッチ右下 Grove ポートから CamS3 へ直結します。Grove Y 分岐は GPS を追加するときだけ使用します。

座標は Blender の X=背面視左右、Y=ウォッチ背面から外向き、Z=上下です。プレート外面は +Y 側です。

## 最初に 5 分クーポンを印刷する

本体より先にクランプ部だけの 20 × 10 mm フィットチェック用クーポンを生成します。

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part coupon \
  --out case/blender/out/toicamera_coupon.stl
```

0.20 mm レイヤー、壁 3 周、サポート OFF、PLA の標準プロファイルを出発点にしてください。スライサーの見積もりは機種や設定で変わりますが、目的は約 5 分で次を確認することです。

1. 無通電のウォッチで、クーポンの開口を黒いヘッダハウジングの後端へ合わせます。
2. ヘッダ穴には何も差し込まず、ハウジングの外側だけへまっすぐ押し込みます。
3. 軽い指圧で奥まで入り、逆さにしても自然落下せず、工具なしで外せる把持力なら合格です。
4. ヘッダ、基板、ウォッチ背面が白化・変形するほど固い場合は本体を印刷しないでください。

### クランプ公差の調整

最初に変更するのは `PARAMS["HEADER_FIT_TOL"]` です。初期値 `0.2` mm は、写真推定の `HEADER_LENGTH` / `HEADER_WIDTH` / `HEADER_DEPTH` のそれぞれへ加える**全体公差**です。初期キャビティは 18.2 × 2.7 × 8.7 mm になります。

- 固すぎる: `HEADER_FIT_TOL` を 0.05 mm 刻みで増やす（例: 0.25、0.30）
- 緩すぎる: 0.05 mm 刻みで減らす（例: 0.15、0.10）
- 奥まで入らないが上下の把持力は良い: `HEADER_DEPTH` の実測値を修正する
- 幅方向だけ合わない: `HEADER_LENGTH` を修正する
- 上下列へ同時に入らない: `HEADER_ROW_SPACING`（初期値 30.0 mm）を実測中心距離へ修正する

`CLAMP_WALL` は弾性と耐久性に関わるため、公差調整より先に薄くしないでください。実機の黒ハウジングは約 18 × 2.5 × 8.5 mm、列中心距離は約 30 mm という写真推定値で、すべて `PARAMS` から変更できます。

## バックパック STL の生成

クーポン合格後に本体を生成します。`--part` を省略した場合も `backpack` が既定です。

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part backpack \
  --out case/blender/out/toicamera_backpack.stl
```

両方を一度に生成する場合:

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part all \
  --out case/blender/out/toicamera.stl
```

`--part all` は次のサフィックスを付けます。

- `case/blender/out/toicamera_backpack.stl`
- `case/blender/out/toicamera_coupon.stl`

旧 v2 の `shell` / `lid` パートは廃止しました。

## 自己検証

スクリプトは空シーンから形状を構築し、`use_scene_unit=False, global_scale=1.0` で STL を出力します。各 STL を再インポートし、次を検証します。

- bbox が期待値から ±0.3 mm 以内
- 非多様体エッジが 0
- 接続コンポーネントが 1

期待 bbox（X × Y × Z）は次のとおりです。Y はヘッダ奥行、公差、プレート厚を含む総突出量です。

| STL | 期待 bbox |
|---|---:|
| バックパック | 31.2 × 11.7 × 40.0 mm（30.4 mm プレート + 左クランプ端壁） |
| クーポン | 20.0 × 11.7 × 10.0 mm |

最後に `CASE_BUILD_RESULT: PASS` が表示された STL だけを印刷してください。スクリプトは加えて、スピーカー領域、12 時 / 6 時ねじ、穴周囲肉厚、8 mm ピッチ、ヘッダ公差のパラメータ契約も検証します。

## 印刷向き

1. プレートの**平らな外面（CLIP-A/B を付ける面）をビルドプレートへ向けます**。U 字クランプの開口は上向きです。
2. Technic 穴の軸が造形 Z 軸になるため、φ4.8 mm 穴を各レイヤーの円として印刷でき、横穴より真円に近づきます。
3. PLA、0.4 mm ノズル、0.20 mm レイヤー、壁 3 周、上下面 4 層、インフィル 15〜20%、サポート OFF を初期設定にします。
4. クランプを強くする目的で XY 穴補正を変える前に、必ず同じ設定でクーポンを再印刷します。

## 組み立て: プレートと CLIP-A

1. ウォッチを無通電にし、上下ヘッダの 12 時 / 6 時ねじと左スピーカーが完全に見えることを確認します。
2. プレートの U 字チャンネル 2 列を黒いヘッダハウジングへ同時に合わせ、ウォッチ面に対して垂直に押し込みます。穴へピンを入れたり、左右へこじったりしません。
3. 4 個の主取付穴へ CLIP-A の Technic ピンを掛けます。CLIP-B を使う場合も同じ 2 × 2 配列を使い、使用部品の説明に従ってロックします。
4. CLIP-A の左右の爪を CamS3 側面の確認済みの溝へ掛け、両側が同じ深さまで入ったことを指で確認します。背面視で CamS3 を右へ寄せ、左端と爪がスピーカーグリルへ重ならない向きを選びます。
5. CamS3 のレンズをウォッチ画面と反対の**後ろ向き（被写体側）**へ向けます。
6. Grove ケーブルをウォッチ右下ポートから CamS3 へ直接接続します。ケーブルで KEYB、USB-C、電源ボタン、スピーカーを横切らないよう、右外周へ自然なサービスループを残します。

装着後はプレートを軽く上下左右へ動かし、ヘッダハウジングだけで保持され、基板やソケット穴へ曲げ荷重が掛かっていないことを確認してから通電します。

## GPS の後付け

GPS は初回構成に含めません。追加時は次の順序です。

1. 上側の 1 × 2 Technic 穴へ、市販または別設計の GPS ブラケットを取り付けます。GPS 基板をプレートへ直接ねじ込まないでください。
2. GPS アンテナ面を外側へ向け、12 時ねじ、上側ヘッダクランプ、CamS3 の画角と干渉しない位置に調整します。
3. この時点で初めて Grove Y 分岐を追加し、ウォッチ右下ポートから CamS3 と GPS へ分けます。
4. 市販 Y ケーブルで信号線を単純並列にできるとは限りません。CamS3 と GPS の電源・信号ピン、I2C/UART 構成、電流容量を実機回路に合わせて確認してから通電します。

## 主要パラメータ

| パラメータ | 用途 |
|---|---|
| `HEADER_LENGTH` / `HEADER_WIDTH` / `HEADER_DEPTH` | 黒ヘッダハウジング外形（初期 18 / 2.5 / 8.5 mm） |
| `HEADER_FIT_TOL` | 各キャビティ寸法へ加えるクランプ全体公差（初期 0.2 mm） |
| `HEADER_ROW_SPACING` | 上下列の中心距離（初期 30 mm） |
| `CLAMP_WALL` / `CLAMP_END_WALL` | U 字チャンネルの上下壁厚 / 左右端壁厚 |
| `PLATE_WIDTH` / `PLATE_HEIGHT` / `PLATE_THICKNESS` | プレート基準外形（約 30 × 40 × 3 mm） |
| `PLATE_CENTER_X` | スピーカーを避ける右寄せ量 |
| `TECHNIC_HOLE_D` / `TECHNIC_PITCH` | φ4.8 mm / 8 mm の取付規格 |
| `TECHNIC_*` / `GPS_HOLE_CENTER_Z` | 2 × 2 主穴と上側 1 × 2 の位置 |
| `SCREW_CENTER_Z` / `SCREW_ACCESS_MARGIN` | 12 時 / 6 時ねじの非遮蔽検証 |
| `SPEAKER_*` | 背面視左スピーカーの立入禁止領域 |

## 3D 組立シミュレーター

[`simulator/index.html`](simulator/index.html) をブラウザで直接開けます。

```bash
open case/simulator/index.html
```

初期視点は背面です。露出したウォッチ、2 列の黒ヘッダ、右寄せバックパック、簡略 CLIP-A、後ろ向き CamS3、GPS の半透明ゴーストを表示します。「組立 ⇔ 分解」で各部の掛かり方と Grove の直結経路を追えます。薄い GPS 側配線は後付け時だけ使う Y 分岐の説明表示です。

three.js、OrbitControls、CSS2DRenderer は jsDelivr CDN から ES modules として読み込むため、初回表示時はインターネット接続が必要です。

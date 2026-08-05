# ToiCamera ケース v3.4 backpack / v3.5 grid3

M5Stack StopWatch C152 の背面ネジ 2 本を長ネジへ交換し、汎用拡張ラックを樹脂ボスへ共締めする構成です。v3.3 の LEGO テクニック寸法を維持したまま、プレートを 64 mm へ延長し、取り付け可能な位置まで 2 列 × 8 行の候補を敷き詰めました。Unit CamS3、GPS、その他の Unit は CLIP-A/B またはピン式ブラケットで空き穴へ追加できます。

v3.5 では、既存の `backpack` を一切変更せず、モジュールを多めに盛る用途向けの 3 列版を別パーツ `grid3` として追加しています。`grid3` はウォッチ外周内へ円形クリップされるため、v3.4 backpack と用途に応じて選択できます。

正本は [`blender/build_case.py`](blender/build_case.py) です。寸法は `PARAMS` に集約し、1 Blender Unit = 1 mm で STL を生成します。公式寸法の根拠は M5Stack の [`C152-StopWatch-model-size.pdf`](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1242/C152-StopWatch-model-size.pdf) です。

## v3.4 形状

- **プレート外形**: 幅 22 mm、長さ 64 mm、基材厚 3 mm。背面視で X=-7〜+15、Z=-32〜+32 です。2 列の中心 X=0 / +8 に対して左右を均等に確保するため、プレート中心は X=+4 です。
- **ネジ固定**: 既存の X=0、Z=±20 をそのまま使い、中心間隔 40.0 mm、φ2.4 貫通、外面 φ4.5・90°皿もみを維持します。各 φ8 のネジタブ領域は厚さ 3 mm のままです。
- **隆起した穴帯**: X=-4.8〜+12.8、Z=-32〜+32 の全域を穴軸方向厚 7.8 mm にします。幅 17.6 mm は、v3.3 の 9.6 mm 梁幅に列ピッチ 8.0 mm を加えた値です。ネジタブの円形領域だけは隆起を除きます。
- **テクニック穴**: 規格 φ4.8 mm に径補正 +0.15 mm を加え、STL の貫通径は φ4.95 mm です。各穴の両面に φ6.2 × 深さ 0.8 mm の座ぐり、座ぐり底の内側エッジに 0.3 mm 面取りを設けます。
- **干渉回避**: 2 × 8 の候補ごとに、ネジ座 φ4.5 + ウェブ 0.8 mm、外周リム 1.6 mm、スピーカー keep-out、磁石逃げ座との干渉を自動判定します。
- **既存部品の逃げ**: 背面視左のスピーカー keep-out と、25.46 mm 格子上の φ5.5 × 0.3 mm 磁石逃げ座を維持します。右側 2 個の磁石逃げ座と重なる候補穴は生成しません。

座標は Blender の X=背面視左右、Y=ウォッチ背面から外向き、Z=上下です。ウォッチ接触面は Y=0、ネジタブ外面は Y=3.0、穴帯頂面は Y=7.8 です。

## v3.5 grid3（別パーツ）

- **別パーツ**: `--part grid3` で生成します。v3.4 の `backpack` の寸法・穴・形状は変更しません。
- **3 列グリッド**: 列中心は X=`-4 / +4 / +12` mm、行候補は Z=`-28〜+28` mm の 8 mm ピッチです。単列梁幅 9.6 mm を列間へ延長した穴帯／基材の幅は 25.6 mm（X=-8.8〜+16.8）です。
- **列選定理由**: スピーカー keep-out の右端は X=-9.2 mm、採用した穴帯左端は X=-8.8 mm で 0.4 mm の外形間隔を確保します。左シフト案 `-12/-4/+4` はスピーカー外形と干渉し、右シフト案は円周側で生成可能穴数が減るため、keep-out を満たす 8 mm ピッチ案で穴数が最大の `-4/+4/+12` を採用しています。
- **円形クリップ**: 公式外径 φ51.95（半径 25.975 mm）に対し、全外形を半径 25.5 mm の円でクリップします。実マージンは半径方向 0.475 mm、Z 方向は -25.5〜+25.5 mm で、下端もウォッチ外周ぎりぎりまで延長されます。
- **既存規格を維持**: 基材厚 3.0 mm、穴帯厚 7.8 mm、規格穴 φ4.8 + 径補正 0.15 mm、両面座ぐり φ6.2 × 0.8 mm、内側面取り 0.3 mm、ネジ間隔 40.0 mm、φ2.4 貫通と φ4.5・90°皿もみ、磁石逃げを共通仕様として使います。
- **想定用途**: CamS3 に加えて GPS、センサー、ライトなどを複数固定する「モジュール盛り」向けです。実装前に総重量、片持ち荷重、ケーブル曲げ半径を確認してください。

### grid3 穴グリッド座標マップ

`●` が生成穴、`—` が自動干渉スキップです。

| Z (mm) | X=-4 | X=+4 | X=+12 |
|---:|:---:|:---:|:---:|
| +28 | — 円周 | — 円周 | — 円周 |
| +20 | — ネジ座 | — ネジ座 | — 円周 |
| +12 | ● | ● | — 磁石逃げ |
| +4 | ● | ● | ● |
| -4 | ● | ● | ● |
| -12 | ● | ● | — 磁石逃げ |
| -20 | — ネジ座 | — ネジ座 | — 円周 |
| -28 | — 円周 | — 円周 | — 円周 |

生成結果は **10 穴 / 24 候補**です。スキップ内訳は円形外周リム 8、ネジ座 4、磁石逃げ座 2、スピーカー 0。スピーカーは候補穴だけでなくプレート外形の段階で keep-out を確保します。

## 穴グリッド座標マップ

候補は X=`0, 8` × Z=`-28, -20, -12, -4, +4, +12, +20, +28` mm。`●` が生成穴、`—` が自動スキップです。

| Z (mm) | X=0 | X=8 |
|---:|:---:|:---:|
| +28 | ● | ● |
| +20 | — ネジ座 | ● |
| +12 | ● | — 磁石逃げ |
| +4 | ● | ● |
| -4 | ● | ● |
| -12 | ● | — 磁石逃げ |
| -20 | — ネジ座 | ● |
| -28 | ● | ● |

生成結果は **12 穴 / 16 候補**です。スキップ内訳はネジ座 2、磁石逃げ座 2、外周リム 0、スピーカー keep-out 0。端列 Z=±28 は規格穴 φ4.8 に対して外周リム 1.6 mm をちょうど確保します。径補正後の実形状ではリムが片側 0.075 mm 減り、1.525 mm になります。

## 取付例

| モジュール | 推奨固定 | 使用例 |
|---|---|---|
| Unit CamS3 | **CLIP-A** | 中央の 2 × 2（X=0/8、Z=-4/+4）を使い、レンズを画面と反対の後ろ向きへ向ける |
| Unit GPS v1.1 | **ピン 2 本**または **CLIP-B** | 下端の X=0/8・Z=-28 を 2 ピンブラケットで使う。16 mm スパンの CLIP-B は X=0・Z=-28/-12 が使用可能 |
| その他の M5Stack Unit | ピン式ブラケット / CLIP-A/B | 空き穴から荷重とケーブル経路に合う 1〜4 点を選ぶ。片持ちが長い場合は 2 点以上で固定する |

GPS を追加するときだけ Grove Y 分岐を追加し、電源・信号ピン、I2C/UART 構成、電流容量を確認してください。下端へ大きな Unit を付ける場合は、ウォッチ装着時の揺れ、操作部、ケーブル曲げ半径も実機で確認します。

## STL の生成

`--part` を省略した場合は `backpack` が既定です。`--part all` は指定したパスへ従来どおり backpack を書き出し、同じディレクトリへファイル名末尾 `_grid3` の grid3 も書き出します。下の例では `toicamera.stl` と `toicamera_grid3.stl` の 2 ファイルを生成します。

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part all \
  --out case/blender/out/toicamera.stl
```

別名で出力する場合:

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part backpack \
  --out case/blender/out/toicamera_backpack_v3_4.stl
```

grid3 だけを書き出す場合:

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part grid3 \
  --out case/blender/out/toicamera_grid3_v3_5.stl
```

## 自己検証とログ

スクリプトは候補ごとの採否を計算してから形状を構築し、次を自己検証します。

- プレートが 22.0 × 7.8 × 64.0 mm（X × Y × Z）、Z=-32〜+32
- ネジ中心間隔 40.0 mm、ネジタブ厚 3.0 mm、φ2.4 貫通、φ4.5・90°皿もみ
- 穴帯が幅 17.6 × 厚 7.8 × 長さ 64.0 mm
- 全候補と全生成穴が原点 `(0, -28)` から 8.0 mm 格子上にある
- 規格径 φ4.8、既定補正 +0.15、実効径 φ4.95 mm
- 両面の φ6.2 × 深さ 0.8 mm 座ぐりと 0.3 mm 面取り
- ネジ座、外周、スピーカー、磁石逃げとの非干渉
- 生成オブジェクトと再インポートした STL の非多様体エッジが 0、接続コンポーネントが 1
- grid3 が 25.6 × 7.8 × 51.0 mm（X × Y × Z）の bbox に収まり、全頂点の X/Z 半径が 25.5 mm 以下
- grid3 の列候補を穴数とスピーカー外形間隔で比較し、X=-4/+4/+12 が最大 10 穴になること
- grid3 の下端が Z=-25.5 mm の円弧へ届き、ウォッチ公式半径 25.975 mm に対して外へ出ないこと

backpack のログには `TECHNIC_HOLE_SKIP`、`TECHNIC_HOLES_GENERATED`、`TECHNIC_HOLES_SKIPPED`、`TECHNIC_SKIP_REASON_COUNTS`、`TECHNIC_GRID_CHECK` を出力します。grid3 では `GRID3_COLUMN_OPTION`、`GRID3_COLUMN_SELECTION`、`GRID3_TECHNIC_HOLE_SKIP`、`GRID3_TECHNIC_HOLES_GENERATED`、`GRID3_TECHNIC_SKIP_REASON_COUNTS`、`GRID3_TECHNIC_GRID_CHECK`、`GRID3_WATCH_CLIP` を追加し、各部品の `BACKPACK_STL_SELF_CHECK: PASS` / `GRID3_STL_SELF_CHECK: PASS` を確認します。最後に `CASE_BUILD_RESULT: PASS` が表示された STL だけを印刷してください。

## 印刷向き

1. **ウォッチ接触面をビルドプレートへ置き、穴帯の隆起を上向きにして平置き**します。
2. この向きではテクニック穴の軸がプリンターの Z 軸と一致し、穴を横向きに造形する場合より真円を出しやすくなります。
3. PLA、0.4 mm ノズル、0.20 mm レイヤー、壁 3 周、上下面 4 層、インフィル 20% 前後、サポート OFF を初期設定にします。
4. ウォッチ側にも深さ 0.8 mm の座ぐりがあるため、スライサーで座ぐり天井の短いブリッジを確認してください。初層のつぶれが強い場合は象の足補正を使います。
5. ピンがきつい／緩い場合は `TECHNIC_HOLE_D=4.8` を変えず、`TECHNIC_HOLE_PRINT_COMP` だけをプリンターに合わせて調整します。

## M2 ロングネジと組み立て

公式図面は樹脂側の φ2.2 下穴を示していますが、既存ネジのねじ山形状と実長は実機で確認してください。ネジ部周辺は v3.3 と同じ厚さ 3 mm なので、従来と同じ長さ選定を使えます。見込みは M2×8 前後ですが、実測を優先してください。

1. ウォッチを電源 OFF にし、背面ネジを 1 本ずつ外します。もう 1 本は本体保持のため残します。
2. プレートの X=0、Z=±20 の穴を樹脂ボスへ合わせ、同じ径・ねじ山で元ネジより頭下が約 +3 mm 長い皿ネジを入れます。
3. 2 本を数回ずつ交互に締め、がたつきが止まったところで終了します。締めすぎると樹脂ボスを破損します。
4. CLIP またはピン式ブラケットを選んだ穴へ取り付け、φ6.2 のピンカラー座へ正しく収まることを確認します。
5. KEYB、USB-C、電源ボタン、スピーカーをケーブルが横切らないことを確認してから通電します。

## 主要パラメータ

| パラメータ | 用途 |
|---|---|
| `PLATE_WIDTH` / `PLATE_LENGTH` / `PLATE_THICKNESS` | 22 × 64 × 3 mm の基材 |
| `SCREW_SPACING` / `SCREW_HOLE_D` | 40.0 mm 間隔 / φ2.4 mm 貫通穴 |
| `SCREW_COUNTERSINK_*` / `SCREW_TAB_D` | φ4.5・90°皿もみ / φ8・厚さ 3 mm のネジタブ領域 |
| `TECHNIC_GRID_XS` / `TECHNIC_GRID_ZS` / `TECHNIC_PITCH` | 2 列 × 8 行の候補座標 / 8.0 mm ピッチ |
| `TECHNIC_RAIL_WIDTH` / `TECHNIC_GRID_BAND_WIDTH` | v3.3 梁幅 9.6 mm / 2 列穴帯幅 17.6 mm |
| `TECHNIC_RAIL_THICKNESS` / `TECHNIC_RAIL_LENGTH` | 穴帯厚 7.8 mm / 全長 64 mm |
| `TECHNIC_HOLE_D` / `TECHNIC_HOLE_PRINT_COMP` | 規格 φ4.8 mm / 既定径補正 +0.15 mm |
| `TECHNIC_COUNTERBORE_*` / `TECHNIC_HOLE_CHAMFER` | 両面 φ6.2 × 0.8 mm / 内側 0.3 mm 面取り |
| `SCREW_KEEP_OUT_WEB` / `PLATE_OUTER_RIM` | ネジ座とのウェブ 0.8 mm / 規格穴基準の外周リム 1.6 mm |
| `MAGNET_GRID` / `MAGNET_RELIEF_*` | 25.46 mm 格子 / φ5.5 × 0.3 mm 内面逃げ |
| `SPEAKER_*` | 背面視左スピーカーの立入禁止領域 |
| `GRID3_PARAMS["WATCH_CLIP_RADIUS"]` | grid3 外形を制限する半径 25.5 mm の円 |
| `GRID3_PARAMS["TECHNIC_GRID_XS"]` | grid3 の 3 列 X=-4/+4/+12 mm |
| `GRID3_PARAMS["TECHNIC_GRID_X_OPTIONS"]` | 穴数とスピーカー keep-out を比較する列候補 |

## 3D 組立シミュレーター

[`simulator/index.html`](simulator/index.html) をブラウザで直接開けます。

```bash
open case/simulator/index.html
```

シミュレーターは v3.4 の 12 穴グリッド、3 mm ネジタブ領域、7.8 mm 隆起帯、中央の CamS3 / CLIP-A、下端グリッドへピン留めする GPS ゴーストを示します。正確な座ぐり・面取りは STL 正本を参照してください。three.js、OrbitControls、CSS2DRenderer は jsDelivr CDN から読み込むため、初回表示時はインターネット接続が必要です。

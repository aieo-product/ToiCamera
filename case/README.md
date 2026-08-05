# ToiCamera 一体型ケース

M5Stack StopWatch C152、Unit CamS3 5MP、Unit GPS U032 を一体化する、Bambu Lab X2D 向けの 2 ピースケースです。正本は Blender Python スクリプトで、1 Blender Unit = 1 mm の寸法規約からシェルと背面フタの STL を再生成できます。

## 構成

- 上段: StopWatch クレードル（内寸 52.4 × 52.4 × 16.0 mm、表示開口 Ø48 mm）
- 下段前方: CamS3 ベイ（内寸 40.4 × 24.4 × 11.4 mm、レンズ開口 Ø10 mm）
- 下段後方: GPS ベイ（内寸 48.4 × 24.4 × 8.4 mm）
- カメラ横: Grove Y 分岐用 15 × 24 × 8 mm スペース
- 内部: StopWatch から分岐ベイ／GPS へつながる 8 × 6 mm 配線ダクト
- 背面: GPS アンテナ側を 1.2 mm に抑えたフタ、M2 セルフタップ 4 本留め

座標は Blender の X=左右、Y=前後、Z=上下です。ケース前面が -Y、背面フタと GPS アンテナ面が +Y です。

## STL の生成

Blender 4.x を使用します。リポジトリルートで次を実行してください。

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --out case/blender/out/toicamera_case.stl
```

`--part` の既定値は `all` です。この場合は次の 2 ファイルを生成します。

- `case/blender/out/toicamera_case_shell.stl`
- `case/blender/out/toicamera_case_lid.stl`

片方だけ生成する場合:

```bash
# --out のパスへシェルだけを出力
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part shell --out case/blender/out/toicamera_case_shell.stl

# --out のパスへフタだけを出力
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part lid --out case/blender/out/toicamera_case_lid.stl
```

スクリプトは空シーンから形状を構築し、`use_scene_unit=False, global_scale=1.0` で STL を出力します。出力後に STL を再インポートし、次を自己検証します。

- bbox が仕様値から ±0.3 mm 以内
- 非多様体エッジが 0
- 接続コンポーネントが 1

最後に `CASE_BUILD_RESULT: PASS` が表示された STL のみを印刷に使用してください。

## Bambu Studio / X2D 推奨設定

1. シェルとフタの STL を Bambu Studio に読み込み、単位を mm として扱います。
2. シェルは**前面（表示／レンズ開口側）をビルドプレートに向け、背面の大きな開口を上**にします。内部サポートを避けやすい向きです。
3. フタは外面をビルドプレート側にして平置きします。
4. 素材はまず PLA、ノズル 0.4 mm、レイヤー 0.20 mm、壁 3 周、上下面 4 層、インフィル 15〜20% を推奨します。
5. サポートは原則 OFF。ポッド肩は 45°以内、ポート穴は短い水平ブリッジとして設計しています。スライサープレビューでブリッジと薄肉を必ず確認してください。
6. 初回は低速または標準プロファイルで寸法確認用に出力し、部品を無通電で仮組みしてから配線します。

フタ固定は M2 セルフタップねじ 4 本を想定し、シェル側下穴 Ø1.7 mm、フタ側クリアランス Ø2.4 mm です。樹脂やねじの個体差に応じて、M2×6 mm 前後から現物合わせしてください。締め過ぎると 1.2 mm のフタが変形するため注意してください。

## パラメータ調整

寸法は [`blender/build_case.py`](blender/build_case.py) 冒頭の `PARAMS` に集約しています。値を変更したら STL を再生成し、自己検証ログを確認します。

主な調整項目:

| パラメータ | 用途 |
|---|---|
| `TOL` | 片側クリアランス 0.2 mm。現在の内寸は実測外寸に合計 +0.4 mm |
| `WALL` / `FILLET` | 公称壁厚 2.0 mm / 外周フィレット 2.0 mm |
| `BUTTON_ANGLE_DEG` | KEYA/KEYB 窓。0°=右、90°=上、180°=左、-90°=下 |
| `USB_ANGLE_DEG` | USB-C 窓の角度。既定 180° |
| `GROVE_ANGLE_DEG` | StopWatch 下側 Grove 窓の角度。既定 -90° |
| `*_DEPTH_OFFSET` | 各側面窓の前後位置 |
| `CAM_LENS_X_OFFSET` / `CAM_LENS_Z_OFFSET` | レンズ中心の CamS3 ベイ中心からのオフセット |
| `MICROSD_X_OFFSET` / `MICROSD_Y_OFFSET` | 底面 microSD スリットの位置 |
| `LID_THICKNESS` | GPS アンテナ面の樹脂厚。**1.2 mm を超えないこと** |

### 現物合わせが必要な不確実点

StopWatch のボタン、USB-C、Grove ポートの正確な角度／前後位置は公開寸法から確定できていません。また CamS3 のレンズ端寄り量と microSD スロット位置も、個体を基準に最終調整が必要です。現在値は初回フィットテスト用の仮値であり、`PARAMS` 内にも `ADJUST AFTER FIT TEST` と明記しています。

初回印刷前にノギスで次を測り、必要ならパラメータを更新してください。

- StopWatch 前面中心を基準にした各ポート中心角
- 各ポート中心の前面からの距離
- CamS3 左右中心からレンズ中心までの距離
- CamS3 前端／左右端から microSD スロット中心までの距離

## 組立と配線

1. CamS3 をレンズが前面 Ø10 mm 窓を向くように前方ベイへ入れます。
2. GPS をその背面側へ平置きし、セラミックアンテナを 1.2 mm 背面フタ側へ向けます。
3. Grove Y ハーネスを 15 × 24 × 8 mm の分岐スペースへ収めます。
4. StopWatch は上段へ前面から合わせ、配線を 8 × 6 mm ダクトへ通します。
5. ケーブルがねじボスやフタに挟まれていないことを確認し、背面フタを M2 ねじ 4 本で固定します。

配線の想定は赤=5V、黒=GND、黄=G10、白=G11 です。CamS3 分岐は 5V/GND のみ、GPS は 4 線を接続します。市販 Grove Y ケーブルをそのまま信号分岐に使う設計ではないため、ハーネスの導通とピン順をテスターで確認してから通電してください。

## 3D 組立シミュレーター

[`simulator/index.html`](simulator/index.html) をブラウザで直接開けます。ビルドやローカルサーバーは不要です。

```bash
open case/simulator/index.html
```

three.js、OrbitControls、CSS2DRenderer は jsDelivr CDN から ES modules として読み込むため、初回表示時はインターネット接続が必要です。マウス／トラックパッドで回転・ズームし、右下の「組立 ⇔ 分解」スライダーで exploded view を確認できます。Grove 4 線は色別の 3D チューブで表示され、分解時も各部品のポートへ追従します。

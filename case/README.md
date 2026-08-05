# ToiCamera ケース v2 — 握って撮るコンデジ型

M5Stack StopWatch C152 をファインダー兼ディスプレイとして手前に向け、Unit CamS3 5MP と Unit GPS U032、Grove Y 分岐をウォッチ背面へ重ねる 2 ピースケースです。v1 の「ウォッチ下ポッド」は廃止し、前面リングと背面ポッド（フタ兼用）のサンドイッチ構成へ変更しました。

正本は [`blender/build_case.py`](blender/build_case.py) です。寸法は `PARAMS` に集約し、1 Blender Unit = 1 mm の規約で Bambu Lab X2D 向け STL を再生成します。

## v2 構成

- **前面リング**: StopWatch 収納 52.4 × 52.4 × 15.7 mm、表示開口 Ø48 mm。外形 56.4 × 56.4 mm、前面ベゼル 2.0 mm
- **背面ポッド兼フタ**: 背面視 74 × 96 mm の小判型、奥行 14.3 mm。前縁は 2 mm 進む間に 2 mm 広がる 45°肩
- **CamS3**: 背面視右寄り・縦中央。40.4 × 24.4 mm ベイにレンズを被写体側へ向けて格納し、背面に Ø10 mm レンズ窓と 12 × 4 mm microSD スリットを配置
- **GPS**: 上端ヘッダより外側の上部に 48.4 × 24.4 mm で横置き。セラミックアンテナは被写体側を向き、対向する背面壁は 1.2 mm
- **配線ベイ**: 下部に Grove Y 分岐と余長用の 15 × 24 × 8 mm 空間。Grove ポート直近の 10 × 8 mm リング切り欠きからポッド前縁のノッチへ直接引き込む
- **スピーカー**: 背面視左のグリル位置に Ø16.5 mm の完全貫通開口。ポッド前面の空気層と連続し、背面壁で塞がない
- **固定**: リング側 M2 ボス 4 点、下穴 Ø1.7 mm。ポッド側クリアランス Ø2.4 mm

座標は Blender の X=背面視左右、Y=前後、Z=上下です。`+X` が背面視右、`-Y` がディスプレイ／撮影者側、`+Y` がレンズ／被写体側です。

### 厚みとエアギャップ

| 区間 | 寸法 |
|---|---:|
| 前面ベゼル | 2.0 mm |
| StopWatch 収納深さ | 15.7 mm |
| ポッド内部（空気層 + CamS3） | 2.0 + 11.1 mm |
| GPS アンテナ側背面壁 | 1.2 mm |
| **組立外形厚** | **32.0 mm** |

実機 StopWatch（厚さ 15.5 mm）と CamS3（厚さ 11.0 mm）を各基準面へ寄せたとき、両者の間は 2.3 mm 空きます。上端・下端の 2.54 mm ヘッダ突出 2.0 mm を逃がし、ウォッチ背面全域で 2 mm 以上の空気層を確保する設計です。GPS 前面までの空きは 5.3 mm です。

## 実機背面との対応

背面から見て次の向きで組み立てます。

- 左中央: スピーカーグリル → Ø16.5 mm 開口
- 左側面: KEYA（黄・上）／KEYB（青・下） → 連続ボタン窓
- 右側面: USB-C と電源ボタン → 個別のパラメトリック窓
- 右下 4〜5 時方向: Grove HY2.0-4P → 10 × 8 mm の後端寄り切り欠き
- 上端・下端: 2.54 mm ヘッダ列 → 2.3 mm エアギャップ内へ逃がす
- 12 時・6 時: StopWatch 背面ねじ → 同じエアギャップ内で非接触

## STL の生成

Blender 4.x を使用します。リポジトリルートで次を実行してください。

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --out case/blender/out/toicamera_case.stl
```

v1 とのファイル名互換を維持しており、`--part shell` は前面リング、`--part lid` は背面ポッドを表します。`--part all`（既定）では次を生成します。

- `case/blender/out/toicamera_case_shell.stl` — 前面リング + M2 ボス
- `case/blender/out/toicamera_case_lid.stl` — 背面ポッド兼フタ

片方だけ生成する場合:

```bash
# 前面リング
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part shell --out case/blender/out/toicamera_case_shell.stl

# 背面ポッド
/Applications/Blender.app/Contents/MacOS/Blender -b \
  --python case/blender/build_case.py -- \
  --part lid --out case/blender/out/toicamera_case_lid.stl
```

スクリプトは空シーンから形状を構築し、`use_scene_unit=False, global_scale=1.0` で STL を出力します。出力後に STL を再インポートし、次を自己検証します。

- bbox が期待値から ±0.3 mm 以内
- 非多様体エッジが 0
- 接続コンポーネントが 1

v2 の期待 bbox（X × Y × Z）は次のとおりです。

| STL | 期待 bbox | 備考 |
|---|---|---|
| 前面リング (`shell`) | 63.6 × 30.8 × 56.4 mm | X/Y は背面へ伸びる M2 ボスを含む |
| 背面ポッド (`lid`) | 74.0 × 14.3 × 96.0 mm | 45°前縁肩を含む最大外形 |

最後に `CASE_BUILD_RESULT: PASS` が表示された STL のみを印刷に使用してください。

## Bambu Studio / X2D 推奨設定

1. 2 個の STL を Bambu Studio に読み込み、単位を mm として扱います。
2. 前面リングは**表示開口側をビルドプレートへ向け**、M2 ボスを上向きにします。
3. 背面ポッドは**レンズ／スピーカー開口がある外面をビルドプレートへ向け**、ウォッチ側の大きな開口を上向きにします。
4. 素材はまず PLA、ノズル 0.4 mm、レイヤー 0.20 mm、壁 3 周、上下面 4 層、インフィル 15〜20% を推奨します。
5. サポートは原則 OFF。ポッド前縁は 45°肩、各部品ベイは組立面側へ開放しています。スライサープレビューで Ø10 レンズ窓、Ø16.5 スピーカー開口、M2 ボスの立ち上がりを確認してください。
6. 初回は標準以下の速度で寸法確認用に出力し、全部品を無通電で仮組みしてから配線します。

M2 セルフタップねじは 6〜10 mm を現物合わせしてください。リング側の長いボスへ被写体側からねじ込みます。締め過ぎると 1.2 mm の背面壁やポッドが変形するため注意してください。

## パラメータ調整

主な調整項目:

| パラメータ | 用途 |
|---|---|
| `TOL_XY` / `TOL_DEPTH` | XY 片側 0.2 mm、基準面から奥行 0.1 mm の初回クリアランス |
| `WALL` / `REAR_SKIN` | 公称壁厚 2.0 mm / GPS アンテナ対向壁 1.2 mm |
| `POD_AIR_GAP` | ウォッチ背面全面の最小空気層 2.0 mm |
| `CAM_CENTER_*` / `GPS_CENTER_*` | 背面視の CamS3・GPS 配置 |
| `SPEAKER_CENTER_*` / `SPEAKER_OPENING_D` | 実機グリルと貫通開口の位置・直径 |
| `BUTTON_ANGLE_DEG` | KEYA/KEYB。背面視 180°=左 |
| `USB_ANGLE_DEG` / `POWER_ANGLE_DEG` | USB-C／電源ボタン。背面視 0°付近=右 |
| `GROVE_ANGLE_DEG` | Grove。背面視 -45°=右下 4〜5 時方向 |
| `CAM_LENS_*_OFFSET` | CamS3 ベイ中心からレンズ中心までの背面視オフセット |
| `MICROSD_*_OFFSET` | CamS3 ベイ中心から microSD スリット中心までのオフセット |

### 初回フィットテストが必要な点

写真で向きと領域は確定していますが、各中心位置の実測値は未確定です。`PARAMS` の初期値は安全側の開口を持つ初回試作用なので、印刷前にノギスで次を確認してください。

- StopWatch 中心からスピーカーグリル中心までの X/Z 距離
- KEYA/KEYB、USB-C、電源ボタン、Grove ポートの中心角と前面からの距離
- CamS3 外形端からレンズ中心、microSD 中心までの距離
- 使用する Grove プラグの最大外形と曲げ半径

## 組立と配線

1. CamS3 を背面視右のベイへ置き、レンズを背面 Ø10 mm 窓へ合わせます。
2. GPS を上部へ横置きし、セラミックアンテナを 1.2 mm 背面壁へ向けます。
3. Grove Y 分岐と余長を下部 15 × 24 × 8 mm ベイへ収めます。配線はウォッチ背面から 2 mm 以上後方へ押さえてください。
4. Grove ケーブルを右下ポートから 10 × 8 mm 切り欠きへ入れ、外周へ出さず、そのままポッド前縁ノッチから内部へ曲げます。
5. StopWatch を前面リングへ背面から入れます。左スピーカー、上下ヘッダ、12/6 時ねじがポッドや配線へ接触しないことを確認します。
6. ポッドをリング側 M2 ボスへ合わせ、ケーブルを挟んでいないことを確認して 4 本を均等に締めます。

配線色は赤=5V、黒=GND、黄=G10、白=G11です。CamS3 分岐は 5V/GND、GPS は 4 線を接続します。市販 Grove Y ケーブルを信号線まで単純並列にはできないため、ハーネスの導通とピン順をテスターで確認してから通電してください。

## 3D 組立シミュレーター

[`simulator/index.html`](simulator/index.html) をブラウザで直接開けます。

```bash
open case/simulator/index.html
```

初期視点は被写体側の背面です。スピーカー穴群、ポッドの Ø16.5 開口、2.3 mm エアギャップ、上部 GPS、右寄り CamS3、下部配線ベイを確認できます。右下の「組立 ⇔ 分解」で、右下 Grove ポート → 切り欠き → ポッド内 Y 分岐 → CamS3/GPS の経路を追跡できます。

three.js、OrbitControls、CSS2DRenderer は jsDelivr CDN から ES modules として読み込むため、初回表示時はインターネット接続が必要です。

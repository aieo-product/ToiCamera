# NOTICE — sanoTTS-jp model weights

ToiCamera's on-device voice ("sanoTTS" voice mode) uses the sanoTTS-jp model.
The inference code is MIT (see `LICENSE`); the model weights
(`model/saanotts-jp-v3-int8.bin`) are distributed under the
**sanoTTS-jp Model License 1.0** (`model/LICENSE-MODEL.md`), which requires the
attribution block below to be reproduced verbatim and restricts how the generated
speech may be used (no attacks on individuals/groups, no political or religious
advocacy, no adult content, no redistribution of the generated audio as a voice
material collection). Those obligations propagate to anyone redistributing this
firmware.

```
This model was distilled from a piper-plus teacher model.
sanoTTS-jp — https://github.com/ayutaz/sanoTTS-jp

つくよみちゃんコーパス
  本ソフトウェアの音声合成には、フリー素材キャラクター「つくよみちゃん」
  （© 夢前黎）が無料公開している音声データを使用しています。
  https://tyc.rei-yumesaki.net/material/corpus/

MOE-Speech (litagin) — https://huggingface.co/spaces/litagin/moe-speech-license
  著作権法 30 条の 4（情報解析のための利用）に基づき学習に使用。

蒸留に使用したテキストコーパス:
  - Common Voice ja (Mozilla) — CC0-1.0
      https://github.com/common-voice/common-voice
  - ROHAN4600 (森勢将雅) — CC0-1.0
      https://github.com/mmorise/rohan4600
  - ITA コーパス — CC0-1.0
      https://github.com/mmorise/ita-corpus
  - JSUT ver1.1 (高道慎之介) — CC-BY-SA-4.0 ほか（subset 別）
      https://sites.google.com/site/shinnosuketakamichi/publication/jsut

教師実装: piper-plus (MIT) — https://github.com/ayutaz/piper-plus
```

sanoTTS-jp is an independent re-implementation of arXiv:2608.21378 (sanoTTS), not
the authors' official implementation. つくよみちゃん (© 夢前黎) does not endorse
this project.

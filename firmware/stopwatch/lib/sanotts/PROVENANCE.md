# Provenance

`src/` is a verbatim copy of the C99 inference core from
[ayutaz/sanoTTS-jp](https://github.com/ayutaz/sanoTTS-jp) `csrc/`
at commit `a478680073aacfec4fc16c31e370d63ef09c8d14` (2026-09-03, post-v0.2.0
with the S1–S5a speed work and blob format v2):

| file | role |
|---|---|
| `saanotts.c` / `saanotts_stream.c` / `fft.c` / `saanotts_int8.c` | inference core (all four are required to link) |
| `g2p.c` + `g2p_table.h` | kana intermediate representation → student ids (on-device G2P) |
| `*.h` | headers of the above |

ToiCamera-specific files (not upstream): `saan_port_toi.h`, `saan_model_blob.S`,
`saan_model_blob.h`, `library.json`.

Build configuration = upstream `esp32/boards/m5unified` with `-DSAAN_ENABLE_PIE=1`:
`SAAN_INT8_ACT=1 SAAN_PIE=1` (W8A8 + ESP32-S3 PIE SIMD), `-O2`, erf table in DRAM.

`model/saanotts-jp-v3-int8.bin` is generated from the v0.2.0 release checkpoint
`saanotts-jp-v3-stage4.pt` with `scripts/export_c_weights.py --int8` at the same
commit (blob **v2** — the v1 blob shipped in the v0.2.0 release is rejected by this
core with `SAAN_ERR_VERSION`). The weights are **not MIT** — see `model/LICENSE-MODEL.md`
and `NOTICE.md`.

To update: copy the files above from a newer upstream commit, regenerate the blob,
and record the commit here. Do not edit the core in place.

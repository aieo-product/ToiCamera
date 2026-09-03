/* sanoTTS-jp int8 weight blob (SAAN v2, ~654 KB) embedded into the app
 * .rodata, 16-byte aligned. The core reads it in place from flash (no copy).
 * ee.vld.128.ip (PIE) needs the 16-byte alignment — every tensor offset in
 * the blob is a multiple of 16, so aligning the base is enough.
 *
 * SAAN_BLOB_PATH is passed from platformio.ini (absolute path under lib/sanotts/model). */
#ifndef SAAN_BLOB_PATH
#error "SAAN_BLOB_PATH not defined (see platformio.ini build_flags)"
#endif
    .section .rodata.saan_model, "a"
    .balign 16
    .global saan_model_blob
    .type saan_model_blob, @object
saan_model_blob:
    .incbin SAAN_BLOB_PATH
saan_model_blob_end:
    .size saan_model_blob, saan_model_blob_end - saan_model_blob

    .balign 4
    .global saan_model_blob_size
    .type saan_model_blob_size, @object
saan_model_blob_size:
    .word saan_model_blob_end - saan_model_blob
    .size saan_model_blob_size, 4

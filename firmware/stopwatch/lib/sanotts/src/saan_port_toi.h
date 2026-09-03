/* ToiCamera placement attributes for the sanoTTS-jp core (Arduino-ESP32).
 * Mirrors esp32/components/saanotts_core/saan_port_esp32.h upstream: the erf
 * table (1,032 B) goes to internal DRAM so it does not fight the weight stream
 * for D-cache. Values are unchanged — placement only. */
#ifndef SAAN_PORT_TOI_H
#define SAAN_PORT_TOI_H
#ifndef __ASSEMBLER__
#include "esp_attr.h"
#define SAAN_HOT_DATA DRAM_ATTR
#define SAAN_HOT_CODE IRAM_ATTR
#endif
#endif

# Wiring / 配線

## Phase 1 (MVP): WiFi data + Grove power

| Stopwatch Grove | wire | Unit CamS3 Grove |
|---|---|---|
| GND (pin 1) | black | GND |
| 5V (pin 2) | red | 5V |
| G10 (pin 3) | — **not connected** | (G20 = USB D+) |
| G11 (pin 4) | — **not connected** | (G19 = USB D-) |

Use a Grove cable with the two data wires removed (or cut), because the CamS3
Grove data pins are USB D+/D- — driving GPIO signals into them can confuse the
USB peripheral. Power only.

Data path is WiFi: both devices join the same LAN; give the CamS3 a DHCP
reservation and put its IP into `firmware/stopwatch/secrets.ini` (`CAM_URL`).

## Phase 2 (stretch): single-cable UART

Custom CamS3 firmware re-muxes G19/G20 to UART via the GPIO matrix (runtime
config only — **never burn eFuses**; USB flashing still works via the ROM
bootloader with BOOT held).

| Stopwatch | wire | CamS3 |
|---|---|---|
| GND | black | GND |
| 5V | red | 5V |
| G10 (Serial1 RX) | yellow | G20 (TX) |
| G11 (Serial1 TX) | white | G19 (RX) |

Protocol: 921600 8N1, frames `[AA 55][type][len:u32][payload][crc16-ccitt]`,
1KB chunks with ACK/NAK retry. SVGA JPEG ≈1.5–2s per shot.

## Reference photos

Device photos in `docs/photos/`.

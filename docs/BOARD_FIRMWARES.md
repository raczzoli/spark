# Firmware files by board

The local release has `app/Spark.exe` for the Windows GUI and `pico-firmwares/`
for board-specific UF2 files. Every supplied UF2 contains both **EC Programmer**
and **Battery Analyzer**; choose one for the exact board, not a different firmware
for each workspace:

| UF2 | Board and Pico SDK profile |
| --- | --- |
| `Pico-RP2040.uf2` | Raspberry Pi Pico / Pico H (`pico`) |
| `Pico-W-RP2040.uf2` | Raspberry Pi Pico W / Pico WH (`pico_w`) |
| `Pico-2-RP2350.uf2` | Raspberry Pi Pico 2 / Pico 2 with headers (`pico2`) |
| `Pico-2-W-RP2350.uf2` | Raspberry Pi Pico 2 W / Pico 2 W with headers (`pico2_w`) |
| `Waveshare-RP2350-USB-A.uf2` | Waveshare RP2350-USB-A (`waveshare_rp2350_usb_a`) |
| `Waveshare-RP2040-Zero.uf2` | Waveshare RP2040-Zero (`waveshare_rp2040_zero`) |
| `Waveshare-RP2350-Tiny.uf2` | Waveshare RP2350-Tiny (`waveshare_rp2350_tiny`) |
| `Waveshare-RP2350-Zero.uf2` | Waveshare RP2350-Zero (`waveshare_rp2350_zero`) |
| `Seeed-XIAO-RP2040.uf2` | Seeed Studio XIAO RP2040 (`seeed_xiao_rp2040`) |
| `Seeed-XIAO-RP2350.uf2` | Seeed Studio XIAO RP2350 (`seeed_xiao_rp2350`) |

All ten variants compile and have UF2 metadata matching their Pico SDK board
profile, RP2040/RP2350 family, and USB CDC console feature.
The board used during EC protocol development was the Waveshare RP2350-USB-A.

## Connections by workspace

| Task | Default Pico GPIOs | Target |
| --- | --- | --- |
| ITE EC programming | GP3 SDA, GP2 SCL, common GND | Board's confirmed EC programming signals |
| ENE EC programming | GP2 CLK, GP3 DI, GP4 DO, GP5 CS, common GND | Model-specific EDI pins and KSO3 strap |
| Battery Analyzer | GP7 DATA, GP9 CLOCK, common GND | Confirmed battery D, C and B− contacts; B+ stays disconnected from Pico |

The EC and battery workspaces retain their own GPIO settings. Use GPIO numbers
rather than a board's printed I2C labels. ITE uses the same GP2/GP3 pair as
ENE CLK/DI: GP2 goes to EC SCL and GP3 goes to EC SDA.
The GUI permits another adjacent GPIO pair.

The header-equipped Raspberry Pi Pico variants differ physically in their
headers and debug connector, so they use the base board UF2. See
[Raspberry Pi Pico board documentation](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html).

For ENE EDI, all builds use SPI0 on fixed **GP4 (EDI DO)**, **GP5 (EDI CS)**,
**GP2 (EDI CLK)**, and **GP3 (EDI DI)** plus common GND. The target's KSO3
test signal also needs the board-specific low connection. Check that those
GPIOs are exposed on your Pico variant before choosing its UF2. See the ENE
section in the main README for target-side signal names.

For batteries, connector positions and any present/enable link are model-specific.
Use Spark's connector search and the [battery guide](BATTERIES.md); the
[ITE guide](HARDWARE.md) describes EC wiring.

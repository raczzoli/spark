Spark - EC Programmer + Battery Analyzer 0.4.0 / 9b9993d792fa

Automated tests passed. See docs/ENE.md for protocol details.
Run app/Spark.exe; pico-firmwares/ contains board-specific UF2 files.
Install only the UF2 matching your board. Pico 2 H uses Pico-2-RP2350.uf2.
Default ITE pins: GP3 SDA, GP2 SCL, common GND. Default timing is unchanged.
Battery tab: offline connector search, SBS readings, monitoring, PDF/JSON/CSV reports.
Default battery pins: GP7 DATA, GP9 CLOCK, common GND; battery B+ stays off Pico.
Physical pin numbers are shown only for the standard 40-pin Pico footprint.
TI bq40z50-R3 access profile needs the battery's own keys.
ID 4555 / firmware 0003 supports read-only diagnostics; no service commands.
ENE Read checks forward/reverse pages and compares two full passes before saving.
Write erases, programs and verifies; no automatic backup.
ITE IT51xx/IT55xx/IT8xxx: Read, Write, Erase; Write verifies the complete image.
Size: numeric/manual for ITE (64/128/192/256/384/512/1024 KiB); automatic and locked for ENE.
ENE: GP2 CLK, GP3 DI, GP4 DO, GP5 CS, common GND; confirm target strap/pins.
ENE models: KB9012QF, KB9022Q, KB9028Q, KB902FQ C, KB9052QD (128 KiB).
KB9548QF2 A0/07: 160 KiB, model-specific EDI wiring.
Source and instructions: https://github.com/raczzoli/spark

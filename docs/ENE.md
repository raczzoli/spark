# ENE EDI support

ENE uses a common SPI EDI register transport and a shared eFlash page engine.
The GUI lists documented physical models from [ENE_PINOUTS.md](ENE_PINOUTS.md);
compatible models share the protocol groups below.
All groups below are implemented and simulator-tested. KB9022Q identification
has succeeded on hardware. KB9548QF2 A0/07 has two matching 160 KiB physical readouts. Existing ITE algorithms are separate.

| Internal protocol group | Documented examples | HWVERSION / EDIID | Full range used by reference implementations |
| --- | --- | --- | --- |
| KB901x | KB9010, KB9012, KB9016, KB9018 | C3 / 04 | 128 KiB |
| KB902x | KB9022; KB9028 | B1 / 07; C0 / 07 | 128 KiB |
| KB9052 (B/D) | KB9052 interface variants B and D | B0 / 0B; D0 / 0B | 128 KiB |
| KB9052QE | User-identified KB9052QE | E0 / 0B | 128 KiB reference range |
| KB9542GF | upstream KB9542GF; community KB9542 revision | F0 / 07; A0 / 07 | 160 KiB |

The group names do not claim support for every possible matching model number.
The two ID bytes select a documented interface variant; they do not identify
the motherboard firmware, and an EDI response alone does not prove flash compatibility.
The community A0/07 signature is published as KB9542, without establishing
that all package suffixes are equivalent. It shares the KB9542GF GUI group
but retains its own entry behavior.

## Size and operations

**Size is filled automatically and disabled for the selected ENE model.** KB901x,
KB902x and KB9052 (B/D) use 128 KiB; KB9542GF uses the full 160 KiB range.
The GUI labels this as a family value, not a capacity measured from the chip.
The application rejects partial images. The internal KB9542GF engine retains
160 KiB support. KB9548QF2 exposes that engine for the measured A0/07 revision
and its model-specific wiring.
For ITE, the numeric Size field remains editable.

All supported variants use 128-byte pages and erase to **00**, not FF.
Read starts at zero and offers Save after completion. Write erases the full
family range, programs it, then verifies every byte. Erase only erases that
range. There is no automatic backup or separate erased-flash scan.
The host checks the family range and image length before destructive operations;
firmware rejects unaligned or out-of-range page commands.

## Session variants

The common engine uses EDI register read/write commands 30/40, eFlash registers
FEA8-FEAD and PXCFG FF14 bit 0 to hold the 8051 in reset. Flash commands are
03 (read), 20 (page erase), 80 (clear latch), 02 (latch byte), 70 (program page).
Entry runs SPI0 in mode 0 at 2 MHz, with a dummy read to activate EDI and
bounded retries while the EC firmware is still running.

**F0/07** uses the upstream WDTCFG FE80 = 48 sequence. **KB9052QE E0/0B**
also uses this password after physical diagnostics showed CPU reset clearing
after four seconds while WDTCFG remained 83. QE reads back WDTCFG as 00;
entry checks that reset/interrupt enables (bits 0/1) are cleared, rather than
requiring the password bits to echo. The KB9012 datasheet, section 4.12.3,
documents the 1001b disable password in bits 6:3 (48 hex). This handling is
scoped to these exact signatures; A0/07 and the other KB90xx profiles are unchanged.
CPU reset is confirmed before a session is accepted. Page operations check
that CPU reset and flash command enable remain asserted. Failures attempt
flash disable and session cleanup; close returns the GPIOs to inputs even
if the EC does not acknowledge CPU release. A physical reset may still be
needed after a communication failure.

## Firmware and wiring

Use the new matching UF2: the GUI requires capability **ENE_EDI_V2** and sends
`ENEOPEN KB901X`, `ENEOPEN KB902X`, `ENEOPEN KB9052`, `ENEOPEN KB9052QE`, or `ENEOPEN KB9542GF`.
The original bare `ENEOPEN` remains a KB9052-only command for old clients.
The reply remains `ENEOPEN HW=xx EDI=xx`; page command formats are unchanged.
An older UF2 is rejected before opening an ENE session. No ITE waveform or
SDA/SCL pin selection is used for ENE.

| Pico GPIO | EC signal |
| --- | --- |
| GP4 | EDI DO / MISO (KSI7 on the documented KB9012 interface) |
| GP5 | EDI CS (KSI4) |
| GP2 | EDI CLK (KSI5) |
| GP3 | EDI DI / MOSI (KSI6) |
| GND | Target ground |

Confirm the EC-side pins, programming-mode strap (for example KSO3), and
power rails from the target schematic. Package pin numbers and connector
positions are not universal. The target supplies its normal 3.3 V power;
Pico is the SPI transport. Not every Pico variant exposes all four GPIOs.

## Evidence and validation

- [flashrom ENE definitions](https://github.com/flashrom/flashrom/blob/0bc4b2ddb0f83e3829e8fad840ece804640c37f3/flashchips/ene.c)
  define KB9012 at 128 KiB and KB9542GF at 160 KiB, both with 128-byte pages
  and the same read/write/erase functions.
- [flashrom EDI implementation](https://github.com/flashrom/flashrom/blob/0bc4b2ddb0f83e3829e8fad840ece804640c37f3/edi.c)
  and [ENE register definitions](https://github.com/flashrom/flashrom/blob/0bc4b2ddb0f83e3829e8fad840ece804640c37f3/include/ene.h)
  supply the base engine, F0/07 identity and its watchdog handling.
- [Jack O'Neo's flashrom extension and contributor reports](https://eletronicabr.com/forums/topic/111881-ler-e-gravar-kbc-ene-kb90xx-com-o-gravador-ch341a-usando-flashrom-no-mint-linux/)
  supply the KB9010/16/18 grouping and KB9022/28, KB9052 B/D and KB9542 A0/07
  signatures.
- [ENE KB9012 datasheet](https://www.eliptor.pl/pub/pdf/ene/KB9012.pdf)
  documents the EDI interface and the KB9012 signal mapping.

Native tests compile the production ENE C module against a register-level EC
simulator. They check all listed signatures, 64/128 KiB address crossings,
the final 160 KiB page, erase/program/read sequences, busy/ready framing,
wrong-family rejection, session loss, timeout and cleanup. Python tests cover
USB command construction, selected ranges, full verification, worker and GUI
integration. Existing ITE traces are tested separately.

## KB902FQ C

KB902FQ C reuses the common EDI engine with an assumed 128 KiB range and
128-byte pages. `ENEOPEN KB902FQ` accepts a nonzero/non-FF hardware byte with
EDIID 07, except known 160 KiB signatures A0/07 and F0/07. This is an explicit
compatibility assumption, not a measured KB902FQ identity. The actual HW/EDI
is displayed and retained for session-change detection. No watchdog override
is applied. Existing exact-model identity checks remain unchanged.

Pin mapping comes from the user-provided ASUS X541NA rev 2.1 FZ BoardView,
whose BOM identifies U3001 as KB902FQ C, LQFP128. A published 128 KiB dump
is supporting evidence for size, not a capacity probe:
https://eletronicabr.com/en/files/file/34880-bios-notebook-asus-f540sa-xx183t-x540sa-and-kb902fq-rev-21-8mb/
If the chip reports another EDI ID, capture it before extending this rule.

## KB9548QF2 read validation (2026-11-13)

Two complete 163,840-byte readouts matched SHA-256
`ca0601d34a3223f75e1424d0b187274aea963e3afbcb3b58004cd6831781c6ee`.
The upper 32 KiB contains nonuniform data and differs from the first 32 KiB.
An intervening read stopped on EDI_NOT_READY. Page failures now stop the
operation without automatic page replay. Erase/program commands are never retried.
No physical erase or program operation was run. The selectable KB9548QF2 profile
uses the existing simulator-tested legacy A0/07 engine and full 160 KiB image
guard. Write erases, programs and verifies the complete image.

## Single-pass Read

Every EC Read makes one pass over the selected image range. ENE requests each
128-byte page once and firmware issues one flash READ per byte, in ascending
address order. There is no reverse page pass, second complete pass, automatic
page replay or readback comparison within Read. Progress ends at the selected
image size (128 KiB for a 128 KiB image). ITE also reads its selected range once.
Protocol framing and session-state checks still stop on transport/session errors.
A single read cannot detect a syntactically valid wrong byte. Repeat Read
manually and compare saved dumps when an independent comparison is wanted.
Write still erases, programs and verifies the complete image; its readback is
an explicit Verification stage. The QE watchdog fix is retained.

Earlier versions added reverse page and second full passes after an intermittent
KB9548QF2 byte mismatch. These automatic repetitions were removed at the user's
request on 2026-11-15. Earlier matching-dump measurements describe those prior
builds and do not imply repeated reads in the current Read operation.

Physical validation of single-pass build `4509d1e36543` on KB9052QE E0/0B:
one 131,072-byte read issued exactly 1,024 page requests, completed in 74
seconds and ended at progress 131,072/131,072 bytes. Comparing its result
in memory with the previously stored dump matched SHA-256
`1edd40be48e7e1a0bad7029ce2ad84223fe7768834ec7cdedbf6faef69d453cd`.
This comparison issued no additional target reads. All 272 automated tests
passed, including ascending single-read counts for every ENE signature.

## KB9052QE

`ENEOPEN KB9052QE` accepts only E0/0B, reported from the user target on
2026-11-15. It holds the CPU in reset, disables the watchdog with FE80=48
and checks that WDTCFG bits 0/1 read back clear. It uses 128-byte pages and
the KB9052 reference range of 128 KiB. The old
`ENEOPEN KB9052` B/D identities remain unchanged. See README for validation
status and ENE_PINOUTS.md for the wiring reference.

On 2026-11-15, QE diagnostics at 2 MHz showed WDTCFG=83 and PXCFG changing
from 01 to 00 after approximately four seconds even without flash reads.
With FE80=48, WDTCFG read back as 00 and PXCFG remained 01 after six seconds
idle and throughout two complete matching 128 KiB read passes. Physical
read validation used build `a2dd5abaf32e`; the final build retains the same
production fix and adds regression tests. The image SHA-256 is
`1edd40be48e7e1a0bad7029ce2ad84223fe7768834ec7cdedbf6faef69d453cd`.
No physical EC erase/program was performed.

`ENESTATE` reads HWVERSION, EDIID, PXCFG, EFCFG and WDTCFG in an open
session without changing registers or issuing flash commands. It remains
available after a session-state failure to inspect the target before closing.

# Spark

**EC Programmer + PD Controller + Battery Analyzer. One Windows application. One Raspberry Pi Pico.**

Spark combines laptop EC programming, PD controller flash access and SMBus smart
battery diagnostics in three workspaces. All use the same USB interface and
combined Pico firmware. Choose the workspace for the connected target; each task
has its own wiring and controls.

![Spark connections: ITE EC and PD Controller use GP3 for SDA and GP2 for SCL; Battery Analyzer uses GP7 for DATA and GP9 for CLOCK. All use common ground. Battery B+ stays disconnected from Pico.](docs/images/spark-connections.svg)

| EC Programmer | PD Controller | Battery Analyzer |
| --- | --- | --- |
| Identify supported ITE and ENE controllers | Identify a TI 4CC host interface | Read standard SBS battery information |
| Read, erase and write supported EC flash | Read, erase and write external SPI through the PD controller | View voltage, current, temperature, charge and capacities |
| Verify the complete written image | Verify the complete written image and erased contents | Plot live readings and save PDF, CSV or JSON reports |
| Model-specific ENE wiring diagrams | Model selection, configurable GPIOs and automatic host-address discovery | Search connector references and see their Pico connections |
| Stage progress, saved backups and operation log | Stage progress, saved backups and operation log | Controller status and cell voltages where supported |

[Download Spark 0.5.0](https://github.com/raczzoli/spark/releases/tag/v0.5.0) · [Choose Pico firmware](docs/BOARD_FIRMWARES.md) ·
[EC wiring guide](docs/HARDWARE.md) · [Battery guide](docs/BATTERIES.md)

## Get started

1. Download and extract the repository using **Code > Download ZIP**.
2. Run **[release/app/Spark.exe](release/app/Spark.exe)**. No Python installation is needed.
3. Hold **BOOTSEL** while connecting Pico, then copy the UF2 matching the exact
   board from **[release/pico-firmwares](release/pico-firmwares)** to its USB drive.
4. Reconnect normally and wait for **Interface: COMx — Pico… | Connected**.
   Spark detects the interface at startup and when it is plugged in.
5. Choose **EC Programmer**, **PD Controller** or **Battery Analyzer**, then follow that tool's
   wiring instructions below.

The same supplied UF2 supports all three tools; changing workspaces does not require
reflashing Pico. Use one target at a time and disconnect power before changing
the wiring. Use the GPIO numbers shown in Spark rather than a board's printed
I²C function labels. GPIO signals use **3.3 V logic**.

The current application and all ten firmware variants are included in
**[release/](release)**. [GitHub Releases](https://github.com/raczzoli/spark/releases)
also contains versioned archives; check their version before using an older package.

## EC Programmer

### Supported controllers

The names below match the **Manufacturer** and **Model / Family** selectors in
the EC workspace.

| Manufacturer | Model / family | Operations |
| --- | --- | --- |
| ITE | IT51xx | Read, Write, Erase — Untested |
| ITE | IT55xx | Read, Write, Erase — Untested |
| ITE | IT8xxx | Read, Write, Erase |
| ENE | KB9012QF | Read, Write, Erase |
| ENE | KB9022Q | Read, Write, Erase |
| ENE | KB9028Q | Read, Write, Erase |
| ENE | KB902FQ C | Read, Write, Erase — 128 KiB |
| ENE | KB9052QD | Read, Write, Erase |
| ENE | KB9052QE (E0/0B) | Read, Write, Erase — 128 KiB |
| ENE | KB9548QF2 (A0/07) | Read, Write, Erase — 160 KiB |

KB9052QE E0/0B identification was reported from the user target. The profile
uses the KB9052Q wiring reference and 128 KiB range; capacity and physical
erase/write have not been validated on this revision.
A physical diagnostic found PXCFG clearing after four seconds while WDTCFG
remained 83, even without flash reads. The QE entry sequence now disables
the watchdog using FE80=48 and verifies its reset/interrupt enables are clear.
The 500 kHz entry trial was below ENE's documented 1?8 MHz activation range;
the configured SPI rate remains 2 MHz. No physical EC erase/program was issued.
All 272 automated tests passed, including simulated watchdog reset, ignored
watchdog-disable writes, session diagnostics, exact single-pass command counts
for every ENE model and one READ command per flash byte in every ENE signature.
Earlier physical read validation on QE E0/0B: after six seconds idle with the CPU
held in reset, both complete 128 KiB read passes matched, including each
page's forward/reverse check. SHA-256:
`1edd40be48e7e1a0bad7029ce2ad84223fe7768834ec7cdedbf6faef69d453cd`.
Current single-pass validation on the same QE target: 131,072 bytes read in
1,024 page requests, progress ending at 128/128 KiB, in 74 seconds. The result
matched the previously saved dump above; comparison did not reread the EC.

ITE operations use the detected flash command set: 8315 eFlash uses AAI
programming and 1 KiB sector erase; KGD eFlash uses page programming and
4 KiB sector erase. IT51xx/IT55xx use the v2 command path. Select the target's
flash size from 64, 128, 192, 256, 384, 512 or 1024 KiB. Write verifies the
complete image after programming. See [ITE protocol details](docs/ITE.md).

### Connect an ITE EC

| Pico default | Target board |
| --- | --- |
| **GP3** | EC **SDA** |
| **GP2** | EC **SCL** |
| **GND** | Board **GND** |

Confirm the target signals from the board's schematic or netlist. The EC is
powered by its board. SDA/SCL GPIOs can be changed in the EC workspace; use an
adjacent pair for the implemented DBGR waveform.

ITE uses the same GPIO pair as ENE CLK/DI: **GP2 is SCL**, **GP3 is SDA**.
See the [ITE wiring guide](docs/HARDWARE.md) for the electrical setup.

### Connect an ENE EC

Select the exact model, then use **View wiring diagram** for its EC pin numbers
and pin-1 orientation. The exposed LQFP-128 models use:

| Pico | ENE signal | Physical EC pin |
| --- | --- | --- |
| **GP4** | EDI DO / KSI7 | **62** |
| **GP5** | EDI CS / KSI4 | **59** |
| **GP2** | EDI CLK / KSI5 | **60** |
| **GP3** | EDI DI / KSI6 | **61** |
| **GND** | Board ground | Board ground |
| Board ground | KSO3 programming strap | **42** |

Ground KSO3 before powering the target. These are **chip pin numbers**, not
keyboard connector positions. See [ENE model pinouts](docs/ENE_PINOUTS.md) and
[protocol and validation notes](docs/ENE.md) before wiring.

### Read, write or erase

1. Select **Manufacturer** and **Model / Family**.
2. For ITE, choose the GPIOs and flash **Size**. For ENE, Size is filled from
   the selected model.
3. Click **Connect to EC** and follow any power-cycle prompt.
4. Choose **Read**, **Write** or **Erase**. Write erases, programs and verifies
   the complete image; it does not create an automatic backup.

Read performs one pass over the selected range for every EC model. ENE pages
are read once in firmware, with no automatic page replay or second full pass.
Progress counts the selected image size. Repeat Read manually to obtain
another dump for comparison. Write still verifies the complete programmed image.
Read opens a save dialog. Canceling it keeps the backup in memory until you
choose **Save…** or **Discard**. Progress shows the current stage, transferred
KiB and elapsed time. The compact EC log remains visible, and **Open folder**
locates a saved backup.

## PD Controller

The **PD Controller** tab reads, writes and erases external SPI flash through
the PD controller's **TI 4CC I²C host interface**. Connect Pico to the PD
controller's SDA/SCL pins; the SPI flash stays connected to the controller.

| Pico default | Target signal |
| --- | --- |
| **GP3** | Host-interface **SDA** |
| **GP2** | Host-interface **SCL** |
| **GND** | Board **GND** |

Power the target separately and confirm its host-interface pinout, bus pull-ups
and 3.3 V logic. The SDA/SCL GPIOs are selectable in the PD workspace.

1. Choose the exact **Model** from the **Select model** field.
2. Locate the external SPI flash on the target board and determine its capacity
   from its marking or datasheet. Select that capacity in **Size**, beside SDA/SCL.
3. Click **Connect to PD**. Spark discovers the I²C address automatically and
   displays the controller's firmware version.
4. Choose **Read**, **Write** or **Erase**.

**Size** starts empty and remains editable. External SPI capacity can vary
between boards using the same PD controller, so Spark does not preselect it from
the model, previous settings or backups. Changing the model, wiring or USB
connection clears the selection; identifying a different controller also clears
it. The current TI host interface does not expose automatic flash-capacity
detection.

- **Read** reads the entire selected range from address zero and opens a save
  dialog. Canceling the dialog retains the image until **Save…** or **Discard**.
  Existing backup files are never overwritten.
- **Write** accepts a complete binary image matching the selected flash capacity,
  erases that range, programs the image and verifies every byte. Use a full SPI
  image including its headers, rather than a patch bundle intended for RAM loading.
- **Erase** erases the selected range and reads it back to verify that every byte
  is `FF`. It does not restart the PD controller.

Save a backup before Write or Erase; these operations do not automatically save
one. Each saved read includes a `.pd.json` file with the controller identity,
selected size and image checksum. Progress shows the operation stage, transferred
KiB and elapsed time; **Open folder** locates the saved image.

Keep target power connected through programming and verification. Only one
workspace can own Pico at a time, and unsaved EC or PD reads must be saved or
discarded before switching tools. This workspace accesses external SPI flash;
internal ROM extraction, internal-flash programming and RAM patch loading are
not provided.

## Battery Analyzer

### Connect a smart battery

1. Open **Battery Analyzer** and type the battery model or part number in the
   searchable **Battery** selector.
2. Choose the matching connector reference. Spark shows every listed contact,
   the connector orientation and which contacts connect to Pico. Unknown
   contacts remain marked **?**.
3. Confirm the connector view and connect the identified signals:

| Battery signal | Pico default |
| --- | --- |
| **DATA / D / SDA** | **GP7** |
| **CLOCK / C / SCL** | **GP9** |
| **B− / GND** | **GND** |
| **B+** | **Leave disconnected from Pico** |
| Present, temperature or other contacts | Follow that exact model's reference |

The battery's connector positions vary by model. The table maps **signals to
GPIOs**, not connector pin numbers. Present/enable contacts are linked to ground
only when documented for that exact reference. GPIOs can be changed under
**Controller > Advanced**.

Pico is the communication interface; it does not charge or discharge the pack.
Use suitable pull-ups to **3.3 V**, short leads and the confirmed connector
pinout. The [battery connection guide](docs/BATTERIES.md#connect-and-read) covers
the electrical setup and interpreting missing readings.

### Read and diagnose

Click **Read battery**, then choose a section:

| Section | What it shows |
| --- | --- |
| **General info** | Identity, voltage, charge, capacities, temperature and cycles where reported; operational status and individual cells when supported |
| **Measurements** | Voltage, current, temperature and charge graphs; **Live readings** and **Stop** |
| **Controller** | Detected controller, available protection/cell checks and supported service operations; connection settings and raw data under **Advanced** |

**Save report** exports PDF, JSON or CSV after a read. Live capture updates every
three seconds and stops when you change a main or battery tab. The voltage graph
follows the displayed values with **2 V below the minimum and 2 V above the maximum**.

The catalog contains **3,840 entries**: **129 connector references** and **3,711
model/part-number identities without a pinout**, with **7,824 distinct searchable
codes** after normalizing punctuation. **103** references identify DATA, CLOCK
and GND; some pinouts remain partial. Models without wiring show **Pinout unavailable**
and no invented contacts or GPIO assignments. A catalog entry does not guarantee
controller-specific diagnostics or unlock support. A battery
absent from the catalog can still be read if it supports SBS and its wiring is
independently confirmed.

The compact brand selector includes the 31 brands observed in NLBA 5.2.4 and
other catalog manufacturers, including brands with no imported models yet.
It filters the model dropdown and alias search; All brands searches the entire catalog.

### Unlock and controller access

**Battery lockout and Seal/Unseal are separate states.** Standard SBS readings
do not provide a universal unlock command.

| Controller profile | Current support |
| --- | --- |
| Standard SBS | Basic measurements and battery information; no controller-specific unlock |
| LGC AC14B8K, ID `4555`, firmware `0003` | Verified read-only diagnostics, operational status and cell voltages; no unlock implementation |
| Asus C41N1906-1, live identity `AS1GWDF3KC / FX50658`, ID `4556`, firmware `0008` | Automatic identification, protection status and four cell voltages; latch recovery and service access are not implemented |
| TI bq40z50-R3, ID `4500`, firmware `03xx` | Seal/Unseal/Full access and PF recovery using the battery's keys when required |

**Unlock battery** is available only for a supported, confirmed PF lockout.
The **Locked** display also covers active safety protections that block battery
operation. Reports retain the exact protection state, cause and raw registers;
the shared label does not enable an unsupported reset procedure.
Missing diagnostics stay **Unknown**. See [controller support and recovery
limits](docs/BATTERIES.md#battery-lockout-and-controller-memory-access) for details.

On 2026-11-16 the connected C41N1906-1 returned device `4556`, firmware
`45560008000E0003850200`, OperationStatus `00006B81`, SafetyStatus `00000800`
and PFStatus `00000000`, with verified PEC. The diagnostic compatibility profile
uses the TI BQ40 status layout: ASCDL indicates a latched discharge short-circuit
protection, while PF is clear. Cell registers returned 4026/4025/4025/4025 mV.
These were direct SMBus reads; no reset, key attempt, configuration write,
charge/discharge test or successful recovery was performed. The existing
bq40z50-R3 PF reset is not used for this device. Eighty battery/controller/status/UI
tests passed for this change; UI tests use temporary settings.

Further recovery investigation on 2026-11-16 found a
[firsthand BQ40Z556 repair case with the same SafetyStatus `00000800`](https://www.laptopu.ro/community/laptop-battery-chip-reset-and-repair/asus-as1gsuc3kc-bq40z556-unlock/paged/2/).
The owner reports success after Unseal followed by Device Reset `0x0041`;
this is evidence for a recovery candidate, not verification on C41N1906-1.
[TI's BQ40Z50 manual](https://www.ti.com/lit/ug/sluua43a/sluua43a.pdf)
documents the default unseal pair and excludes Device Reset from sealed-mode
commands. Under the owner's authorization, one default TI unseal pair was
sent to the connected `4556 / 0008` battery. The controller remained Sealed;
OperationStatus stayed `00006B81`, SafetyStatus `00000800`, PFStatus `00000000`.
No retry, full-access attempt, reset, FET forcing or configuration write followed.
Recovery remains unavailable pending a working pack-specific unseal method and
validation of the reset procedure. No successful recovery is claimed.

An additional authorized investigation compared the documented
[BQ40Z50 two-word security protocol](https://www.ti.com/lit/ug/sluua43a/sluua43a.pdf)
with the different SHA-1/HMAC Unseal protocol in TI's
[BQ30Z50/55-R1 manual, SLUU852A](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/399/BQ30Z50,55-R1_TechRef.pdf).
The exact security mechanism of OEM `4556 / 0008` remains unconfirmed.
A read-only timing proxy (40 cycles, two SBS reads plus a controller status
query per cycle) averaged 0.2183 seconds per cycle. At that proxy rate, an
exhaustive 32-bit search would take about 29.7 years; this is not a measured
key-attempt rate or a firmware speed limit.
Thirty-one one-bit variations of the documented TI default key pair were
then physically tried, excluding candidate words below `0x0100` and waiting
4.2 seconds between pairs. None changed the controller from Sealed;
OperationStatus, SafetyStatus and PFStatus remained `00006B81`, `00000800`
and `00000000`. No reset, full-access attempt, FET-forcing or configuration
write was performed. This small heuristic search neither exhausts the key
space nor establishes that the OEM firmware uses the two-word protocol.

Twelve further first-word observations (four previously tried prefixes, three
rounds) all received ACK and returned unchanged ManufacturerData and
ManufacturerAccess `6B81`. No useful prefix distinction was observed in this
set. USB timing cannot resolve internal processing or clock stretching, and no
known correct OEM first word was available as a positive control.
Further static NLBA analysis also corrected the initial transport-only inference:
the BQ40Z50 service class calls an HTTP request path and processes its FU reply.
The earlier serial control bytes do not establish where the complete Unseal
algorithm or battery key resides. No server request, license operation, additional
full key-pair attempt or battery reset was performed in this follow-up. No key
or functioning independent Unseal procedure has been recovered.

## Supported Pico boards

- **Raspberry Pi:** Pico, Pico W, Pico 2 and Pico 2 W. Header-equipped variants
  use the corresponding base-board firmware.
- **Waveshare:** RP2040-Zero, RP2350-Zero, RP2350-Tiny and RP2350-USB-A.
- **Seeed Studio:** XIAO RP2040 and XIAO RP2350.

Choose the exact UF2 in the [board-to-firmware map](docs/BOARD_FIRMWARES.md).
Both workspaces use USB CDC with the standard Windows serial driver. On the
Waveshare RP2350-USB-A, connect the PC through **USB-C**. Board-specific photos
and printed pin labels do not replace the GPIO mapping for the selected task.

## Testing and feedback

Release 0.5.0 validation (2026-11-20): 274 automated tests passed on Windows,
including native C firmware regressions. All ten board profiles compiled and
passed UF2 board/family/build validation; packaged startup passed with temporary
settings. This release preparation did not include physical target tests.

Report EC, battery or interface results in [GitHub Issues](https://github.com/raczzoli/spark/issues).
Include the Pico model, application/firmware versions, target model and operation.
For EC operations, include the log; for batteries, include the diagnostic report
and controller ID if available. State whether the result is a read, identification
or a completed programming/recovery operation.

See [ENE protocol details](docs/ENE.md) and [battery diagnostics](docs/BATTERIES.md)
for model-specific behavior and technical references.

## Build from source

Python 3.10+ on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app\requirements.txt
.\.venv\Scripts\python.exe -m app
```

To build the complete package, install `requirements-release.txt` and
`requirements-test.txt`, the Raspberry Pi Pico SDK with submodules, CMake,
Ninja and the Arm GNU toolchain, then run:

```powershell
.\.venv\Scripts\python.exe devtools/build_release.py --sdk C:/path/to/pico-sdk
```

The builder runs the automated tests and creates **Spark.exe**, board-specific
UF2 files and SHA-256 manifests in `release/`. See [build instructions](docs/RELEASING.md)
and the [code map](docs/ARCHITECTURE.md) for development details.

## License and credits

Project source is licensed under **GNU GPL v2 or later** (`GPL-2.0-or-later`);
see [LICENSE](LICENSE).

ITE implementation draws on Chromium OS EC `iteflash` and the entry waveform
from `I2C-Pico-USB-ITE-EC-prog`. ENE implementation draws on flashrom and
Jack O'Neo's extension with contributor reports. Battery connector references
link their public sources. See [source attribution](docs/THIRD_PARTY.md).
Bundled libraries retain their own licenses; Qt/PySide6 notices are included
with the Windows application.

Software by **R89 Repairs** | [www.r89-repairs.ro](https://www.r89-repairs.ro)

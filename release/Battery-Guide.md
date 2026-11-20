# Battery workspace

Spark and its combined UF2 contain EC and battery tools. The shared interface
status sits above the two tool tabs, and the EC log sits directly under Operations.
Run `release/app/Spark.exe`. The current build is updated directly in
`release/app/` and `release/pico-firmwares/`.

## Connect and read

1. Connect Pico by USB. The compact **Interface** bar above the EC / Battery tabs
   detects it automatically, including when it was connected before startup.
   It shows, for example, **COM9 — Pico W (RP2040) | Connected** after confirming
   the supplied firmware. No COM selector or Refresh is needed. Both tools use
   this interface; unplugging it clears their target sessions, preserving readings.
   Enter **Battery Analyzer**; leaving EC ends its debug hold before another
   operation can acquire Pico. Finish/save an EC read before changing tools.

   **Read battery** defaults to automatic controller identification. Live SBS
   identity LGC / AC14B8K permits a TI DeviceType diagnostic query; returned
   device ID `4555` and firmware identity `4555 / 0003` must agree before status
   bits or cells are decoded. The UI then shows access state and all four measured
   cell voltages without a manual profile selection. Unknown live battery identities
   keep SBS readings and explain which controller profile is missing. The searchable
   connector selection never chooses a controller. **Standard SBS** remains available
   in Controller for basic-only reads.
2. Type the model or part number in the editable **Battery** combo in its header.
   It starts empty every time; battery selection is not saved between sessions.
   Its popup filters while typing, including aliases, and lists models alphabetically.
   Each result shows the model first, then its manufacturer and pin count underneath
   (for example, **Asus · 8 pins**), or **Lenovo · Pinout unavailable** when only
   the model identity is known. Arrow keys and Enter select a result.
   The compact connector appears directly below, with the Pico GPIOs
   beneath the contacts. Every listed contact, gap and unknown position is shown.
   Compare the documented view and the positive/negative landmarks. Right-click
   the connector to mirror its display, inspect a contact or open its source.
   For a model without a pinout, the header says so and shows no contact diagram
   or implied pin count. Identify its wiring separately before connecting; model
   selection does not supply a connector or identify a controller.
3. Defaults are **DATA GP7**, **CLOCK GP9** and common ground. The diagram uses
   GPIO numbers. On a 40-pin Pico, GP7 is physical pin 10, GP9 is pin 12 and a
   convenient GND is pin 8; these physical numbers do not apply to other boards.
   Battery B+ is never connected to Pico. The battery powers its own electronics;
   Pico is an SMBus adapter, not a charger or an electronic load. Use 3.3 V logic,
   short leads and suitable pull-ups; internal weak pull-ups are an option for
   short test leads, not a replacement for a properly designed interface.
4. Click **Read battery** beside the model selector. **General info** stays selected
   and shows the basic readings, capacities, identity, battery operation and cells.
   Missing diagnostics remain unknown. **Locked** covers PF/fuse lockout and
   active safety protections that block battery operation;
   **Unlocked** requires clear PF/safety data and active, uninhibited charge and
   discharge FETs. Reports retain the distinct internal protection states and
   raw diagnostics; the Locked label does not imply a permanent fault.
   Sealed memory access does not affect this
   operational status. **Save report** appears with the result
   and offers PDF, JSON and CSV.
5. **Measurements** contains the graph and **Live readings** toggle (three-second
   updates). The voltage scale dynamically follows the lowest and highest
   displayed readings, with **2 V below the minimum and 2 V above the maximum**
   (with a zero lower limit). It expands and contracts as the visible history
   evolves. Current and temperature use 1 A and 5 °C margins; charge uses a 0–100%
   scale. A different battery resets the scales. During capture the toggle becomes
   **Stop**, which remains available during
   reads. Stop cancels future polls immediately; an in-progress transaction finishes
   once and retains its result. The header Read battery button stays stable during
   live capture. Navigation remains available; any change of main or battery tab
   stops capture immediately. Returning to Measurements does not restart it.
   An in-progress read finishes normally before another operation can use Pico.
   A read error, identity change or
   edit to the model/connection settings also stops capture. **Controller** shows the detected identity,
   operational state, available recovery action and a plain-language summary of
   cell/protection checks. **Unlock battery** is offered for a confirmed lockout;
   unsupported recovery is disabled with a reason. **Advanced**,
   collapsed by default, contains identification methods, raw diagnostics, GPIO,
   PEC, pull-up and **7-bit** address controls (default 0x0B; 8-bit 0x16 is the
   same write address). The battery header contains only Battery/Read and its
   connector; automatic USB status lives in the shared Interface bar outside the tool pages.
   DATA, CLOCK and address require keyboard or arrow-button changes; scrolling
   over these fields does not change the connection. Errors show the selected GPIO
   or battery address to help distinguish a wrong setting from a wiring fault.

Action feedback stays at the bottom of the workspace, outside scrollable tab
contents. There is no battery log panel. A failure offers optional **Details**.
Cell comparison shows the measured spread against an explicit **50 mV display
reference**; this is not an OEM pass/fail limit and does not by itself certify
cell health or balance at another charge state/load. Pack voltage never supplies
guessed individual cell voltages.

Measurements include voltage, signed current, temperature, state of charge, cycle
count, capacities, design values, date, serial number, chemistry and status flags,
where reported by the pack. Health is full/design capacity reported by the gauge;
it is not a measured discharge capacity. Missing optional data is left absent,
not substituted with zero. SBS energy mode and voltage/current scale factors are
decoded. PEC auto mode enables CRC-8 checking when the specification word reports
SBS 1.1 with PEC; Require PEC is also available. A checksum error rejects the read.

The optional Standard SBS profile never sends manufacturer commands or changes
configuration. A new catalog reference or COM port resets the selected profile to
Automatic identification. Automatic mode queries documented diagnostic selectors
only for verified live identities and confirms the returned device/firmware IDs;
it does not change controller access or battery configuration.
Reports keep the reference used for their reading, even if another
model is searched afterwards. It can read a battery absent from the catalog if its physical
pinout is separately confirmed. Not every laptop battery implements SBS; for
example, the PA3905U source describes an EEPROM-only pack.

## Battery lockout and controller memory access

Battery lockout and Seal/Unseal are separate. NLBA describes its repair workflow
as [unseal the controller, then clear chip errors](https://www.laptopu.ro/product/laptop-battery-chip-reset-repair-and-program/).
TI [SLUUBU5A chapters 3 and 15.1.40](https://www.ti.com/lit/ug/sluubu5a/sluubu5a.pdf)
documents PF/SS, fuse, charge/discharge inhibition and FET states separately from
the SEC memory-access bits. The UI, JSON and PDF reports keep both states separate.
There is no Seal action masquerading as a command to disable a healthy battery.

Automatic identification supports the connected LGC AC14B8K diagnostic layout:
device ID `4555`, firmware `0003`. It displays operational status and cells on
General info. Seal/Unseal status is shown under Controller > Advanced. The
profile's name is the reported device ID; it does not guess a marketing chip name.
PF recovery is unavailable for this ID until its own service profile is implemented.
The TI diagnostic protocol, mixed field byte ordering, status bits and cell register
order follow [TI SLUUBU5A, chapter 15](https://www.ti.com/lit/ug/sluubu5a/sluubu5a.pdf);
the `4555 / 0003` compatibility path was separately checked on this real pack.

The explicitly selected **TI bq40z50-R3** profile checks device
type and firmware before decoding OperationStatus, SafetyStatus, PFStatus and
individual cell voltages. It supports Seal, Unseal and Full access with the
battery's supplied two-word keys. Buttons require a fresh supported identity,
verified PEC and the correct current security state. Every access operation
rechecks the pack identity before writing, and verifies the resulting state.
There are no automatic key guesses/retries and no key persistence or logging.

For the documented bq40z50-R3 profile, **Unlock battery** is a PF
recovery workflow. It requires a confirmed PF lockout, verified PEC, no active
safety/fuse/emergency-stop condition, and the pack's own keys if access must be
changed. It confirms Unsealed/Full access, rereads pack and firmware identity,
sends PF Data Reset (0x0029) and Device Reset (0x0041) once, then rereads operation.
Success requires the battery to report Unlocked; clearing a log or changing SEC
bits alone is not success. The pre-reset snapshot is retained in the successful
result/export.

Selecting a connector reference does not identify a controller.
Other controller families retain standard SBS reading. Unsupported revisions
cannot receive access commands. Unseal changes access rights; it does not clear
a protection fault or repair a weak cell. FET forcing, EEPROM/data flash editing,
cycle resets and charging/discharging are not implemented.

The profile is based on [TI SLUUBU5A](https://www.ti.com/lit/ug/sluubu5a/sluubu5a.pdf),
chapters 12 and 15. MAC block responses include two echoed command bytes. For
32-byte diagnostic payloads, register 0x44 therefore needs a bounded 34-byte block
extension; ordinary SBS strings remain limited to 32 bytes.

## Catalog provenance and updates

The compact brand selector precedes the model search. It includes the 31 labels
observed in NLBA 5.2.4's Battery Pinout brand list, merged with the manufacturers
already present in Spark. `app/assets/battery_brands.json` stores these labels
separately from battery records, so brands with no models remain selectable
without inventing battery entries or pinouts. Both the dropdown and alias search
respect the selected brand. All brands removes the filter. Changing brands
clears the previous model and connector reference; brand/model choices are not
saved between sessions.

The offline catalog currently has **3,840 entries**: **129 connector references**
and **3,711 model/part-number identities without a reviewed pinout**. It has
**7,824 distinct searchable names/codes** after ignoring case and punctuation
(8,022 names when repeated aliases across records are counted). Aliases are not
counted as separately verified connectors. Connector records may be partial, inferred from a padded reference table or
conflicting between variants; the UI says so. Only the AC14B8K has local
communication verification. Uncertain data/clock contacts get no GPIO assignment.
Present/enable contacts are connected to ground only where that exact reference
documents it. A label such as T is not globally treated as a thermistor.

Sources for connector references are the [LötLabor Jena table](https://loetlabor-jena.de/doku.php?id=projekte:pinout:laptopbatteries:start),
[Power Cartel PackProbe](https://powercartel.com/projects/packprobe/battery-connection/)
and individually reviewed [public NLBA forum posts](https://www.laptopu.ro/community/laptop-battery-pinout/).
Individual source URLs are bundled with each record. Drawings are generated by
the application. No private/proprietary pinout database is copied.

The 2026-11-13 public-forum crawl attempted 362 topic URLs in laptop pinout
categories and selected related discussions. It retrieved 336 topics plus 27
additional reply pages. Reviewing the published text added **37 connector
references**; it did not turn every request, image-only post or proposed wiring
into a catalog entry. Subsequent per-model Google searches added two reviewed
references, [Acer AC14B18J](https://www.laptopu.ro/community/pinouts-for-acer-batteries/acer-battery-ac14b18j-and-green-pin-out/)
and [Dell WDX0R](https://www.laptopu.ro/community/pinouts-for-dell-batteries/dell-wdx0r-pinout/),
from the moderators' battery-side mappings. Both retain unknown contacts and an
inferred contact count. The WDX0R cable-side attempt is not used; related FW8KR
identity information does not inherit WDX0R wiring. Previously omitted alternate
identity codes are retained as model-only references rather than losing them when
a connector is added. The catalog now has **103 references with documented
DATA/CLOCK/GND**, of which **25 identify every listed position**. This is source
documentation, not physical verification on 103 batteries.

The review follows replies and corrections: A1382 uses data 4/clock 6;
A32-F82 has a thermistor at 3 and two grounded present contacts at 6/7;
J60J5 position 4 is system present rather than an internal ground. Unidentified
contacts remain unknown, auxiliary RTC power is not labelled pack B+, and
sparse numbering retains its inferred-count flag. Connector variants and
source views are kept explicit. A source's successful reading does not add
controller diagnostics or recovery support to Spark. L22D2PG2 is now listed with
its published Lenovo ASM/FRU aliases; it still has no verified pinout.

Model-only identities come from Lenovo's official
[Battery Information Finder](https://www.lenovo.com/content/dam/lenovo/site-design/esg-document-library/global/battery-msds/BatteryInformationFinder.xlsx),
HP's public [Notebook/Tablet battery SDS library](https://h20195.www2.hp.com/v2/library.aspx?doctype=103)
and [supplier battery-name table](https://h20195.www2.hp.com/v2/getpdf.aspx/c07284208.pdf),
Dell's [BYD battery SDS](https://i.dell.com/sites/csdocuments/Legal_Docs/en/BYDSDS20210101.pdf),
and the public [Creeson supplier catalog](https://www.laptopu.ro/wp-content/uploads/wpforo/default_attachments/1612006850-laptopS-PINOUT.pdf).
Additional current model identifiers are taken from reviewed names in public
forum topic titles. These include requests without a wiring solution and remain
marked as forum identity references; laptop chassis names and obvious title
typos are not imported as battery models.
The Lenovo import selects notebook records, excluding UPS/server/coin-cell rows;
the HP import uses battery model, regulatory and customer part-number fields,
excluding cell names and generic laptop titles. Wrapped/ambiguous Creeson model
cells are omitted. Supplier references remain identified as such in their notes.
Only identity information is imported from these sources; even a source that
also lists wiring does not automatically grant a connector assignment.

`verification: model_listed` plus an empty `pins` list means the pinout is
unavailable, not a zero-contact connector. No count, DATA/CLOCK contact or present
jumper is guessed. Known connector entries retain their previous IDs and data;
model-list aliases do not overwrite those references. JSON reading reports include
an explicit `pinout_available` flag for the selected reference.

`app/assets/battery_catalog.json` is the runtime database (schema 1).
`devtools/import_battery_catalog.py` regenerates it from cached public HTML plus
the factual curated entries in `devtools/battery_reviewed.json`. This research
utility needs `beautifulsoup4`; the application does not. Download the two source
pages into `build/battery-sources/wiki.html` and `packprobe.html`, UTF-8, then run:

```powershell
python devtools/import_battery_catalog.py
```

The factual connector-review inputs are `devtools/battery_reviewed.json` and
`devtools/battery_forum_reviewed.json`. Keep the latter's per-record source URL,
review date, orientation, count limitation and correction notes when updating
it. Only reviewed assignments enter the runtime catalog; forum fetching is
research work and is not performed by the application. Unshipped crawl
snapshots and the local crawl report live under `build/battery-sources/forum/`.

`devtools/battery_models.json` contains the reviewed model-source identities and
source-file hashes; catalog regeneration reads it without network access. To
refresh those identities first, use `devtools/import_battery_models.py` with
cached `lenovo.xlsx`, `hp-wistron.pdf`, `hp-notebook-documents.json`, `creeson.pdf`
and `dell-byd.pdf` under `build/battery-model-sources/`, then rerun the catalog
import. This research utility needs PyMuPDF; it reads XLSX values with the Python
standard library and executes no spreadsheet formulas. HP's JSON cache is the
complete public notebook/tablet library result (1,720 source documents), fetched
through its normal search/Load More interface. The GUI has no crawler or download
dependency.
`devtools/battery_forum_models.json` is the separate reviewed input for model
names mentioned in public topics; it supplies no connector assignments. Its
identities are merged after manufacturer sources and never replace an official
model with a duplicate part-number-only forum reference.

## Google research queue

`devtools/battery_pinout_search.py` researches each model-only entry with a known
brand using a separate Google Chrome session. It is a research utility, outside
the Spark interface and firmware. Its optional dependency is `playwright`; it
uses the installed Chrome rather than downloading a browser or using the user's
normal Chrome profile. Nothing is searched when Spark starts.

The current queue has **3,700 eligible model/brand pairs**. The 11 records whose
brand is Unspecified are omitted. Each query includes the exact quoted model and
brand plus `battery pinout`. Brands are interleaved, current model references
precede older supplier references, and `--first MODEL` can prioritize a model.
Completed searches are cached and not submitted again after a restart.

Defaults are one search every **90–150 seconds**, a **10-minute pause after 20**,
and no more than **500 searches in a rolling 24 hours**. The queue reserves its
next slot before navigation, keeps its budget in SQLite, and permits only one
worker per queue. Lowering the interval below 60 seconds is rejected. Browser
errors, unparsed pages, HTTP errors and rate limits pause the queue rather than
being counted as successful searches or causing a retry loop. A 429 reserves at
least a one-hour cooldown. These measures limit traffic; Google can still require
verification even for a first query.

The normal research Chrome window is minimized. If Google requests CAPTCHA or
consent, searches stop and the window becomes visible for the user to complete
the check. No CAPTCHA solving, proxy rotation or browser-identity spoofing is
implemented. The worker inspects the existing page while waiting and continues
only when the expected results page loads. By default it waits up to 30 minutes;
if the user closes the browser or the timeout expires, progress remains saved and
the queue stays paused. `--headless` or `--verification-timeout 0` pauses immediately
instead of waiting in a visible window.

Queue, isolated profile, results, logs and `status.json` live under the ignored
`build/battery-pinout-search/` directory. Search snippets and AI Overview text are
saved as **unverified research leads**. Only promising technical Google redirects
are resolved, at most two per search; stores are not crawled. An opaque Google
tracking link is not treated as a primary source. The utility never writes pin
assignments to the application catalog. Before adding a result to a reviewed
connector input, check the exact battery/connector variant, numbering and view,
power landmarks, DATA/CLOCK and the actual meaning of sensor/present contacts in
the cited source. A Gemini answer or compatibility listing alone is not proof.

From the repository in PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install playwright
.venv\Scripts\python.exe devtools/battery_pinout_search.py init --first L22D2PG2
.venv\Scripts\python.exe devtools/battery_pinout_search.py run
.venv\Scripts\python.exe devtools/battery_pinout_search.py status
.venv\Scripts\python.exe devtools/battery_pinout_search.py stop
.venv\Scripts\python.exe devtools/battery_pinout_search.py resume
```

`run` uses the terminal until finished or paused. To run a hidden background
helper while retaining interactive Chrome verification when necessary:

```powershell
$researchWorkspace = (Get-Location).Path
$researchPython = Join-Path $researchWorkspace '.venv\Scripts\python.exe'
Start-Process -FilePath $researchPython -ArgumentList @('-m', 'devtools.battery_pinout_search', 'run') -WorkingDirectory $researchWorkspace -WindowStyle Hidden -RedirectStandardOutput 'build/battery-pinout-search/worker.log' -RedirectStandardError 'build/battery-pinout-search/worker-error.log'
```

The helper continues while that Windows session is running; no Windows startup
task is installed. After restarting the PC, use `run`, or `resume` if Google needs
attention. `stop` asks the worker to exit cleanly without killing other Chrome or
Spark processes. `--max-jobs N` provides a bounded batch. Search completion and
technical leads are separate from reviewed/imported pinouts in the status file.

Each record includes manufacturer/model/aliases, consecutively numbered positions,
signal roles and uncertainty, connector orientation, source URLs, an explicit
contact-count inference flag, a verification level and present-to-ground policy.
Never infer a model's pinout from its brand or its controller type.

## Verification on 2026-11-12

A combined Pico W build was loaded **only into SRAM**, after verifying every UF2
payload address was inside RP2040 RAM. Installed flash firmware was left intact.
Read-only SBS communication through GP7/GP9 returned LGC / AC14B8K / LION,
serial 31516, manufacture date 2017-07-28, approximately 15.186 V, 90% charge,
214 cycles, 2034 mAh remaining, 2282 mAh full and 3220 mAh design. All word and
string block checksums passed. No manufacturer access/reset/write command was
sent during this initial SBS validation. The GUI worker also read and displayed the real measurements.

Automated tests cover EC golden traces and lifecycle, shared operation ownership,
SMBus wire order/CRC/errors, units, catalog wiring, controller identity gates,
plot rendering and PDF/CSV/JSON exports.

To update the current local distribution:

```powershell
python devtools/build_release.py --toolchain "C:/Program Files (x86)/Arm GNU Toolchain arm-none-eabi/14.2 rel1" --picotool vendor/picotool-win/picotool
```

All ten board profiles include both tools. A RAM test disappears when USB power
is removed; install the matching normal UF2 from `release/pico-firmwares/` for persistent support.

The Pico W was subsequently found running the older EC-only flash build
`c7ba7014c6bb`; its capabilities did not include SMBUS1. After repeating the RAM
test, the combined `bf378ee841d8` Pico W UF2 was installed in flash. The application
then automatically identified COM9 / Pico W and completed a real Read battery
through its shared worker: AC14B8K, approximately 15.185 V, 90%, 214 cycles and
PEC verified. Installed firmware reports both the existing EC capabilities and
SMBUS1. USB startup additionally handles a lost first HELLO or fragmented greeting
without replaying any EC or battery operation.

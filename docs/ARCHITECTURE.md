# Code map and regression checks

The supported ITE flash algorithms are selected from numeric EC revision and
flash-command signatures in `app/flash_protocols.py`. There is no whitelist of
laptop boards or individual ITE part numbers. Capacity remains a user selection.
IT51xx/IT55xx use the v2 path with legacy or extended numeric identity handling;
IT8xxx retains revision-based selection. Host and firmware ranges extend to
1 MiB. See [ITE.md](ITE.md) for session commands and flash geometry.

## Host

- `app/gui.py`, `app/gui_layout.py`: the EC tool's widgets, progress, save/open
  dialogs and UI state. EC keepalive policy remains with this tool.
- `app/window_chrome.py`: themed Spark title bar and native Windows frame handling.
  Caption dragging, edge resizing, maximize/restore and Snap hit testing stay with
  the OS; maximized client bounds respect the monitor work area. Close always
  delegates to the existing operation and unsaved-backup guards in `Window.closeEvent`.
- `app/controller.py`: shared operation ownership. One worker runs at a time;
  the controller stays busy until the worker thread has exited, including cleanup.
  It has no EC commands, target models or widget dependencies.
- `app/operations.py`: a worker owns an entire connect/read/erase/write operation,
  including USB cleanup. It emits one terminal result. Cleanup warnings do not
  replace a successful verification or hide an earlier programming error.
- `app/session.py`: EC connection, existing-session reuse, power-cycle recovery,
  identity checks and background keepalive. No Qt widgets.
- `app/transport.py`: USB CDC framing, capability negotiation, response validation
  and command timeouts. New firmware supports request IDs; replies from an older
  request are ignored. After a timeout, this connection sends no more commands.
  Closing the shared transport only closes USB; it sends no target commands.
- `app/ec_transport.py`: EC command adapter, EC-specific timeout budgets,
  power-cycle entry, ITE register/flash commands and legacy raw I2C commands.
  Its cleanup sends the existing `RELEASE` command before closing USB, unless
  a timeout has made the connection unsynchronized. ENE command encoding remains
  in `app/ene.py`, using the same EC adapter and cleanup.
- `app/ec.py`: ITE operations and compatibility paths for older Pico firmware.
- `app/geometry.py`: common supported capacities and page geometry.
- `app/ene.py`: common ENE EDI flash engine; compatibility groups
  and selected ranges are in `app/ene_families.py`. Physical models, pinouts and
  identity restrictions are in `app/ene_models.py`. See [ENE](ENE.md).
- `app/pd.py`: TI 4CC host-interface discovery, identity, external SPI read,
  erase, programming and full readback verification. It selects native Pico
  mailbox commands or the generic I2C transport without a silicon-ID allowlist.
- `app/pd_operations.py`: PD workers using the shared operation controller;
  identity is checked again before each operation.
- `app/pd_gui.py`, `app/pd_models.py`: PD workspace and model storage profiles.
  Model selection starts empty. External SPI capacity is selected manually;
  internal-capacity profiles provide a fixed, disabled Size field.

The worker negotiates required capabilities before erase. Write remains
erase → program → full verification, without an automatic backup or erased-flash
scan. Keepalive and disconnect run on the worker thread. Failed operations clear
the GUI's connected state; a completed read remains available even if cleanup fails.
Flash operations selected in a file/confirmation dialog wait for any in-flight
keepalive before acquiring USB.

Spark starts with EC Programmer, PD Controller and Battery Analyzer tabs. A compact
`InterfaceBar` above their `QTabBar` displays the automatically confirmed USB interface;
`WorkspaceTabs` composes that bar with a `QStackedWidget` for the pages. The
window owns discovery, persistence and invalidation for all three tools. `app/interface.py`
enumerates USB inventory every 800 ms on a separate thread, filtering the SDK CDC
VID/PIDs for RP2040/RP2350. Identification uses only HELLO/CAPS/INFO through the
same operation controller as tool IO. Ordinary UART, Bluetooth, BOOTSEL and
MicroPython devices are not probed. The board model comes from firmware INFO;
legacy firmware without INFO is labelled without guessing a model. Failed or busy
ports retry with backoff. A confirmed device is retained while present, with its
USB serial preferred after reconnecting; if several devices are present, the last
used serial/port wins, otherwise the first compatible port. Generation checks
prevent late worker results from restoring a disconnected target session. Finished
EC/PD backup data and previous battery readings remain available. Inventory monitoring
continues during tool operations, but metadata probes wait for the controller.
Shutdown joins inventory and operation lifecycles asynchronously before disposing
the window. Tool changes do not change the interface. Each tool owns its target settings
and command adapter, and all use the same controller. Foreground operations
disable workspace changes; live battery reads keep navigation and configuration
available. An unsaved EC or PD read prevents switching to another
workspace. Leaving EC ends its debug session before PD or battery controls become
available. EC keepalive runs only in the EC workspace.
Changing either workspace or battery section stops capture; the current battery
transaction finishes before another operation can acquire USB. Each operation still opens
and closes its own USB connection.

USB startup retries HELLO up to three times on the same serial handle, within
the original timeout. Partial greeting fragments are accumulated; stale replies
are ignored until a complete known greeting arrives. CAPS ignores duplicate
HELLO replies before negotiating tagged framing. Handshake recovery sends no
target commands or leading newline that could complete a
previously interrupted target command. Failure identifies the port and reports
startup/busy/incompatible firmware as possibilities rather than asserting that
a previous command is still running.

`app/battery.py` implements SBS decoding, PEC negotiation and the explicit,
TI bq40z50-R3 profile. `battery_controllers.py` implements automatic
diagnostics for verified live SBS identities, independently of connector selection.
For LGC AC14B8K it confirms DeviceType 4555 against the embedded big-endian
FirmwareVersion ID and accepts the verified 0003 revision. Diagnostic selectors
0001/0002/0051/0053/0054 use ManufacturerAccess 0x00 and ManufacturerData 0x23;
cells are read in position order from 0x3F through 0x3C and checked against pack
voltage. Failed optional extensions keep their reason; PEC or USB loss invalidates
the read. Diagnostics never enable the 4555 controller's unimplemented service
operations. The SBS-only option remains available. `battery_operations.py` owns complete battery
transactions and closes SMBus before reporting success. `battery_gui.py` and
`battery_widgets.py` provide wiring guidance, measurements, trend plotting and
reports. `battery_catalog.py` reads the bundled factual connector references and
model-only identities. An empty pin list means pinout unavailable: the selector
and header show that state and clear any previous connector hit targets. Model
sources never supply guessed pin counts, GPIO assignments or controller profiles.
Pinout selection never selects a controller or sends a manufacturer command.
The battery header contains a searchable model combo/Read and a compact
GPIO-only connector. The shared Interface bar is outside both tool pages and
remains readable during a worker, pending EC backup or live battery capture.
General info, Measurements and Controller tabs
separate overview, live plotting and advanced work. Lock/unlock is contextual;
missing access/cell data remains unknown. Feedback is fixed outside the tabs,
without a log panel. Any workspace or battery section change stops live reading;
returning to Measurements never restarts it automatically.
Changing the battery reference or connection settings stops future polls; each
worker captures its reference and configuration revision so a late result remains
a previous reading and cannot enable controller service with changed settings.
`battery_status.py` derives operational status from a verified layout, PF/Safety,
inhibition and FET flags. Memory SEC bits never determine Locked/Unlocked. Missing
diagnostics remain unknown; temporary protection and disabled output are distinct
from PF lockout. General info and Controller share this result and PF recovery
handler. Seal/Unseal remains a separate Advanced operation. The R3
recovery handler validates identity/PEC, supplied access keys and current faults,
sends PF-data reset/device reset once, and reports success only after a fresh
Unlocked result. ID 4555 remains diagnostic-only. Identification methods, connection settings and
raw tables live in one Advanced disclosure, closed by default. Read battery in the
shared battery header remains the single read action.

## Firmware

- `main.c`, `line_reader.h`: USB input loop; discard an oversized command through
  its newline so its trailing text cannot become a second command.
- `usb_commands.c`, `usb_output.c`: USB framing, tagged replies, common metadata
  and routing to the installed tool's command handler. `command_parse.h` holds
  the shared bounded hex parser.
- `ec_commands.c`: EC routing, capability response, timeout budgets and ITE/ENE
  coexistence rules. `ite_commands.c` and `ene_commands.c` parse their respective
  command sets. Existing command strings, replies and ordering are preserved.
- `pd_commands.c`: `PD4CC1` mailbox operations. `PDTASK` executes a complete
  4CC task with bounded register lengths, idle/completion polling and I2C errors;
  `PDREAD` groups 16-byte `FLrd` tasks into reads of up to 256 bytes. Erase and
  programming commands are never replayed after an unknown USB outcome.
- `device_runtime.c`: the main loop's tool lifecycle boundary, including independent
  battery idle expiry and release/end-session cleanup.
- `smbus.c`, `smbus_commands.c`: independent open-drain battery engine and USB
  commands, advertised as `SMBUS1`. SMBOPEN ends ITE debug hold and closes ENE;
  EC commands are refused while SMBus is open. Its private pin mapping does not
  change the EC GPIO selection. SMBus uses bounded clock stretching and PEC;
  standard blocks have at most 32 bytes, with a 34-byte TI MAC echo extension at
  register 0x44. No legacy EC bus timing or algorithm is changed.
- `i2c_bus.c`: protocol-independent open-drain GPIO/I²C, bounded clock stretching
  and transaction deadlines. It has no ITE register state.
- `ite_bus.c`: ITE write adapter and selected-register tracking, including cursor
  invalidation when the legacy EC pin mapping changes. Both atomic EC commands
  and legacy split `WRITE` commands use this adapter.
- `ite_dbgr.c`: waveform, GPIO mapping, reset-time entry and register access.
- `ite_session.c`: watchdog hold, expiry and register-cursor restoration.
- `ite_flash.c`: page reads, sector erase, legacy AAI, newer AAI and page program.
- `ene_edi.c`: common EDI transport/page engine, with hardware revision
  parameters for capacity bounds and entry/watchdog behavior.

The PIO tail wait includes all 16 states that can remain after its FIFO empties.
Waveform contents, rates and SDA/SCL mapping are preserved. I²C retains the
validated 5 µs delays. `I2CTIMING 3` and `I2CTIMING 2` are developer-only experiments;
the GUI explicitly selects 5. Faster timing is not enabled or claimed tested.

Atomic `REGREAD`, `REGWRITE`, `FLASHID`, `SPISTATUS` and `ERASESECTOR` reduce USB
round trips and prevent idle watchdog work from interrupting these sequences.
The watchdog also restores the selected register for legacy split commands.
`RELEASE` frees the bus while keeping the timed debug hold; `ENDSESSION` stops
feeding it when the GUI closes. It does not itself reset or boot the target EC.

## Verification limits

`python -m unittest discover -s tests -v` runs host tests and compiles actual C
flash/session/parser code against a recording bus. Install `requirements-test.txt`
on Windows or provide a native C compiler. No test opens a real serial port.

`tests/fixtures/ite_flash_traces.json` records 18 command traces produced by the
pre-refactor C functions: legacy AAI 64/256, newer AAI 64/256, page program 64 and
page read, with success and injected write failures. The fixture records the
original source SHA-256. The harness fixes time/status responses; this protects
transaction ordering, not electrical timing or actual flash behavior. Separate
tests exercise watchdog cursor restoration, parser rejection, overflow recovery,
tagged output and atomic sector erase. Native tests also exercise the production
ITE cursor adapter, separation from generic bus writes, EC lifecycle cleanup and
ENE command exclusion. Host tests cover shared USB cleanup and exclusive worker
ownership through thread completion on both success and failure.

Battery tests execute actual SMBus C against scripted slave bits, ACK/NACK,
CRC errors, invalid block lengths and GPIO faults. They verify open-drain release,
exact write byte order, the TI block extension, idle expiry and EC exclusion.
Host tests cover units/scaling, missing values, identity/security gates and cleanup;
GUI tests cover tab isolation, filtering, all connector positions, plot rendering
and all three report formats. These tests never access physical USB.

PD tests execute the production C mailbox handler against a scripted I2C target
and cover discovery, transport framing, flash contents, write verification and
errors. GUI checks use temporary settings for model selection, manual external
capacity, fixed internal-capacity presentation, unsaved backups, USB loss and
shared-worker exclusion. Read-only flash blocks can retry reported bus faults;
erase/program operations and commands with unknown USB outcomes are not replayed.

The release builder supports ten board profiles and checks UF2 metadata. A successful
compile or simulation is not hardware validation. Build output is updated in release/;
the manifest does not imply that it has been exercised on a physical ITE target.
SBS reading was separately exercised on an AC14B8K through a RAM-only combined
firmware build; see [battery validation](BATTERIES.md). No TI access operation
has been performed on physical battery hardware.

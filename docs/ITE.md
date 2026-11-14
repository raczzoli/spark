# ITE DBGR flash programming

The IT51xx, IT55xx and IT8xxx selectors all implement Read, Erase and Write.
Write erases the selected range, programs the complete image and verifies every
byte. No automatic backup is created. Read starts at address zero and returns
exactly the selected size. Erase performs sector erase without programming.

## Flash commands

The flash ID is read with command `9F`, first through BLOCK (`79`) and then
through DATA (`35`) if needed. `FF FF FE` selects 8315 eFlash, with `D7` sector
erase in 1 KiB units and AAI word programming (`AD`). Manufacturer byte `C8` or
`EF` selects KGD eFlash, with `20` sector erase in 4 KiB units and page program
(`02`). Programming skips chunks that contain only erased bytes (`FF`).

IT51xx/IT55xx use the v2 command path, including revisions below three. V2 AAI
sends the first two bytes through DATA, polls readiness, then sends the remaining
bytes through quick BLOCK mode. KGD uses page programming. IT8xxx retains its
existing revision-based selection between legacy AAI and v2 AAI/page program.
Flash contents do not select the programming algorithm.

## Identity and session

`ITEFAMILY IT51XX`, `ITEFAMILY IT55XX` and `ITEFAMILY IT8XXX` select the DBGR
session layout. The firmware advertises `ITE5` for this command. Install the
matching firmware from `release/pico-firmwares/` alongside the current app.

Legacy IT51xx/IT55xx IDs come from DBGR registers `00` and `01`, with revision
in `02`. For the extended IT5xxxx layout, the additional ID byte is read from
`F02085`; CPU reset/halt uses `27 = 81`, and mapped watchdog access includes
the `80 = F0` bank. USB identity replies retain the complete numeric ID.

Changing between the ITE5 and IT8 session layouts clears the previous debug
hold. An ITE5 SESSION query requires an existing hold; initial connection enters
DBGR, stops the target and configures its watchdog before accepting the session.
Keepalive and page operations retain the watchdog bank and renew the timed hold.
The selected family is a protocol choice; Spark does not reject a connection
merely because its numeric ID is outside `8xxx`.

## Capacity and transfers

Capacity is selected explicitly: 64, 128, 192, 256, 384, 512 or 1024 KiB.
It is not inferred from the selected family name. Host and firmware commands
support aligned reads and programming up to 1 MiB, with full three-byte flash
addresses. Page reads restart FAST_READ for each 256-byte page, including at
256 KiB crossings. Programming transactions stay inside flash page boundaries.

Image length, command framing, address alignment, flash readiness, target
identity changes and byte verification are checked for every family. These
checks report an operation error instead of accepting a partial transfer.

## Implementation references and regression checks

- [Chromium OS EC iteflash](https://chromium.googlesource.com/chromiumos/platform/ec/+/main/util/iteflash.cc)
  supplies follow-mode, flash command signatures, v2 AAI and KGD programming,
  extended IT5xxxx identification, CPU halt and watchdog addressing.
- [I2C-Pico-USB-ITE-EC-prog](https://github.com/JohnDoe150489/I2C-Pico-USB-ITE-EC-prog/blob/main/iteflash-i2cpicousb.py)
  selects the v2 command path for IT5570 independently of its revision and uses
  the same DBGR transport for the IT51xx/IT55xx family selectors.

Native regression tests execute the production C session, parser, erase,
program and page-read functions against a register-level flash model. Full
cycles cover simulated IDs `5122`, `5570`, `51526` and `51626`, both flash
command sets and ranges from 128 KiB to 1 MiB. Existing IT8xxx recording traces
remain unchanged. Host tests run the actual worker and flash engine through
connect, read, erase, write and verification, including a changed target and
an incorrect final verification byte. GUI tests use temporary settings and
check that both family selectors expose all flash operations.

# EC Programmer: ITE wiring and operation

This guide covers the **EC Programmer** workspace in Spark. For ENE, use the
[model-specific EDI guide](ENE_PINOUTS.md). For a smart battery, use the
[Battery Analyzer guide](BATTERIES.md); its default CLOCK GPIO is **GP9**.

Connect Pico **GND** to the target board ground, Pico **GP3** to EC **SDA**,
and Pico **GP2** to EC **SCL** for the default GUI configuration. The GPIOs
are selectable; keep SDA and SCL on adjacent GPIOs for the implemented DBGR
waveform. Confirm the target pins from the board's schematic or netlist.
This is the same GPIO pair used for ENE CLK/DI. Follow the GPIO numbers
rather than the board's printed I2C function labels. On a standard 40-pin
Raspberry Pi Pico, GP2 is physical pin 4 and GP3 is physical pin 5.

The target must provide its own EC power and bus pull-ups. The Pico does not
power the EC. Measure the bus high level before connecting: the Pico GPIOs
are 3.3 V logic, not 5 V tolerant. Do not connect an unknown voltage rail to
a GPIO. Connect the Pico to the PC through its USB device port.

| Pico GPIO | ITE target signal |
| --- | --- |
| GP2 | SCL |
| GP3 | SDA |
| GND | Board ground |

RP2350 A2 silicon has a GPIO high-impedance erratum (E9) relevant to this
open-drain interface; Raspberry Pi reports it fixed in A4. See the
[Raspberry Pi RP2350 A4 notice](https://www.raspberrypi.com/news/rp2350-a4-rp2354-and-a-new-hacking-challenge/).

1. Flash the UF2 matching your Pico board through BOOTSEL.
2. Connect GND, SDA, and SCL; power the target board as required by its design.
3. Wait for the shared **Interface** bar to show Connected. Open **EC Programmer**,
   then select ITE, the EC family, the two GPIO numbers, and **Size**
   (64, 128, 192, 256, 384, 512 or 1024 KiB).
4. Click **Connect to EC**. If asked, remove target power for about five
   seconds and reconnect it while keeping the Pico attached.
5. **Read** starts at address 0 and saves exactly the selected range. Select
   the size for the physical EC; the program does not determine it from this
   choice.
   **Write** selects an image,
   erases, writes, and verifies it. **Erase** erases without writing.

The displayed CHIPID and CHIPVER are numeric protocol values. The GUI cannot
identify an exact package marking or a laptop model from these values. The
displayed flash size is the user's selection; the flash command set is
recognized from CHIPVER and the flash ID, without a model whitelist. A correct
size selection is required
for a full image operation.

All three ITE selectors support Read, Write and Erase. IT51xx/IT55xx select
the v2 flash command path; IT8xxx retains revision-based algorithm selection.
See [ITE protocol details](ITE.md) for the flash signatures and session layout.

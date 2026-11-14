# EC Programmer: ITE wiring and operation

This guide covers the **EC Programmer** workspace in Spark. For ENE, use the
[model-specific EDI guide](ENE_PINOUTS.md). For a smart battery, use the
[Battery Analyzer guide](BATTERIES.md); its default CLOCK GPIO is **GP9**.

Connect Pico **GND** to the target board ground, Pico **GP7** to EC **SDA**,
and Pico **GP6** to EC **SCL** for the default GUI configuration. The GPIOs
are selectable; keep SDA and SCL on adjacent GPIOs for the implemented DBGR
waveform. Confirm the target pins from the board's schematic or netlist.
On Seeed XIAO RP2040/RP2350, GP7 is labelled D5 and GP6 is D4. Follow the
GPIO numbers: with the GUI defaults, D5 goes to EC SDA and D4 to EC SCL.
The printed I2C function names on those boards use the opposite order.

The target must provide its own EC power and bus pull-ups. The Pico does not
power the EC. Measure the bus high level before connecting: the Pico GPIOs
are 3.3 V logic, not 5 V tolerant. Do not connect an unknown voltage rail to
a GPIO. Connect the Pico to the PC through its USB device port.

<details>
<summary>Board photo: Waveshare RP2350-USB-A, ITE EC wiring only</summary>

<img src="images/waveshare-rp2350-usb-a-wiring.png" alt="ITE EC wiring on Waveshare RP2350-USB-A: common GND on the left, GP6 for EC SCL and GP7 for EC SDA on the right" width="360">

The photo marks the default **ITE EC** connections. It is not a battery pinout
and does not show the GP9 CLOCK connection used by Battery Analyzer. GPIO
locations and board labels differ on other Pico variants.

</details>

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

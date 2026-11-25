# SPDX-License-Identifier: GPL-2.0-or-later
"""TI 4CC host interface and external flash access over the Pico I2C bridge."""
from dataclasses import dataclass
import time

from .ec_transport import ECTransport
from .transport import TransportError
from .pd_models import HOST_ADDRESSES


class PDError(RuntimeError):
    pass


@dataclass(frozen=True)
class PDIdentity:
    vendor: bytes
    device: bytes
    version: bytes
    uid: bytes
    mode: str

    @property
    def fingerprint(self):
        return self.vendor, self.device, self.uid

    @property
    def device_label(self):
        if all(32 <= byte < 127 for byte in self.device):
            return self.device.decode("ascii").strip()
        return f"0x{int.from_bytes(self.device, 'little'):08X}"

    @property
    def version_label(self):
        return f"0x{int.from_bytes(self.version, 'little'):08X}"


@dataclass(frozen=True)
class PDConnection:
    identity: PDIdentity
    address: int


class PDTransport(ECTransport):
    def __init__(self, port, pins=(3, 2), address=0x38, timeout=3):
        automatic = address is None
        if not automatic and not 8 <= address <= 0x77:
            raise ValueError("Select a 7-bit I2C address between 0x08 and 0x77")
        if pins[0] == pins[1] or any(p not in (*range(23), 26, 27, 28) for p in pins):
            raise ValueError("Select two different Pico GPIOs")
        self.address = HOST_ADDRESSES[0] if automatic else address
        self._read_ready = False
        super().__init__(port, timeout)
        try:
            self.capabilities()
            self.command("ENDSESSION" if self.supports("SESSION") else "RELEASE")
            self.pins(*pins)
            self.command("I2CTIMING 5")
            if automatic:
                self.discover_address()
        except Exception:
            self.close()
            raise

    def discover_address(self):
        """Read host identity registers before issuing any flash command.

        Firmware may override the published I2C addresses. Device IDs are not
        filtered; discovery checks the host interface mode and protocol version.
        """
        addresses = dict.fromkeys((*HOST_ADDRESSES, *range(8, 0x78)))
        for address in addresses:
            self.address = address
            try:
                mode = self.read_register(0x03, 4)
                if not all(32 <= byte < 127 for byte in mode) or not mode.strip():
                    continue
                if self.read_register(0x02, 4) != b"\x01\x00\x00\x00":
                    continue
                PDDevice(self).identify()
                return address
            except TransportError as exc:
                if not self._synchronized or str(exc) not in ("ERR ADDRESS_NACK", "ERR DATA_NACK"):
                    raise
            except PDError:
                continue
        raise PDError("No PD host interface found. Check SDA, SCL, common ground and target power.")

    def read_register(self, register, count):
        if not 1 <= count <= 63:
            raise ValueError("Register reads require 1 to 63 bytes")
        self.write(self.address, bytes([register]))
        raw = self.read(self.address, count + 1)
        if not count <= raw[0] <= 64:
            raise PDError(f"Register 0x{register:02X} returned length {raw[0]}, expected at least {count}")
        return raw[1:]

    def write_register(self, register, data):
        if not 1 <= len(data) <= 62:
            raise ValueError("Register writes require 1 to 62 bytes")
        self.write(self.address, bytes([register, len(data)]) + data)

    def task(self, name, data=b"", count=1, timeout=3):
        self._read_ready = False
        code = name.encode("ascii")
        if len(code) != 4:
            raise ValueError("Expected a four-character task")
        if self.supports("PD4CC1"):
            if len(data) > 64 or not 0 <= count <= 64:
                raise ValueError("4CC transfers require at most 64 bytes")
            answer = self.command(f"PDTASK {self.address:02X} {name} {data.hex().upper() if data else '-'} {count}")
            if not count and answer == "PDTASK":
                return b""
            if not answer.startswith("PDTASK "):
                raise PDError("Invalid Pico PD task response")
            result = bytes.fromhex(answer[7:])
            if len(result) != count:
                raise PDError("Incomplete Pico PD task response")
            return result
        pending = self.read_register(0x08, 4)
        if pending not in (bytes(4), b"!CMD"):
            raise PDError(f"Controller command interface is busy: {pending.hex().upper()}")
        if data:
            self.write_register(0x09, data)
        self.write_register(0x08, code)
        deadline = time.monotonic() + timeout
        while True:
            state = self.read_register(0x08, 4)
            if state == bytes(4):
                break
            if state == b"!CMD":
                raise PDError(f"Controller does not accept the {name} command")
            if time.monotonic() >= deadline:
                raise PDError(f"{name} timed out; reconnect before another flash operation")
            time.sleep(.005)
        return self.read_register(0x09, count) if count else b""

    def flash_read_block(self, address):
        if self.supports("PD4CC1"):
            return self.task("FLrd", address.to_bytes(4, "little"), 16)
        if not self._read_ready or not self._tagged:
            data = self.task("FLrd", address.to_bytes(4, "little"), 16)
            self._read_ready = True
            return data
        # Pipeline only one read task. No erase/program command is ever queued.
        # Data is discarded if the completion poll reports the task still busy.
        payload = (bytes([9, 4]) + address.to_bytes(4, "little")).hex().upper()
        commands = [f"WRITE {self.address:02X} {payload}",
                    f"WRITE {self.address:02X} 0804464C7264",
                    f"WRITE {self.address:02X} 08", f"READ {self.address:02X} 5",
                    f"WRITE {self.address:02X} 09", f"READ {self.address:02X} 17"]
        tags = []
        for _ in commands:
            self._sequence = (self._sequence + 1) & 0xFFFFFFFF
            tags.append(f"@{self._sequence:08X} ")
        replies = []
        try:
            self.port.write("".join(tag + cmd + "\n" for tag, cmd in zip(tags, commands)).encode("ascii"))
            deadline = time.monotonic() + 5
            for tag in tags:
                while True:
                    if time.monotonic() >= deadline:
                        raise TransportError("PD read timed out; reconnect before continuing")
                    raw = self.port.readline()
                    if not raw or not raw.endswith(b"\n"):
                        raise TransportError("Incomplete PD read response; reconnect before continuing")
                    reply = raw.decode("ascii").strip()
                    if reply.startswith(tag):
                        replies.append(reply[len(tag):])
                        break
        except Exception:
            self._synchronized = False
            self._read_ready = False
            raise
        for index, reply in enumerate(replies):
            if reply.startswith("ERR "):
                self._read_ready = False
                raise TransportError(reply)
            if index not in (3, 5) and reply != "OK":
                self._read_ready = False
                raise TransportError("Invalid PD read acknowledgement")
        try:
            if not replies[3].startswith("DATA ") or not replies[5].startswith("DATA "):
                raise ValueError("Invalid data response")
            state = bytes.fromhex(replies[3].removeprefix("DATA "))
            raw = bytes.fromhex(replies[5].removeprefix("DATA "))
            if len(state) != 5 or state[0] != 4 or len(raw) != 17 or not 16 <= raw[0] <= 64:
                raise ValueError("Invalid register length")
        except ValueError as exc:
            self._read_ready = False
            raise PDError("Invalid PD flash read response") from exc
        if state[1:] == b"!CMD":
            self._read_ready = False
            raise PDError("Controller does not accept the FLrd command")
        if state[1:] != bytes(4):
            self._read_ready = False
            deadline = time.monotonic() + 3
            while self.read_register(0x08, 4) != bytes(4):
                if time.monotonic() >= deadline:
                    raise PDError("FLrd timed out; reconnect before continuing")
                time.sleep(.005)
            raw = bytes([64]) + self.read_register(0x09, 16)
            self._read_ready = True
        return raw[1:]


class PDDevice:
    SECTOR_SIZE = 4096
    READ_SIZE = 16
    WRITE_SIZE = 32

    def __init__(self, bus):
        self.bus = bus
        self.read_retries = 0
        self.read_size = 256 if hasattr(bus, "supports") and bus.supports("PD4CC1") else self.READ_SIZE
        self.write_size = 64 if self.read_size == 256 else self.WRITE_SIZE

    def identify(self):
        mode = self.bus.read_register(0x03, 4)
        if not all(32 <= byte < 127 for byte in mode):
            raise PDError("No valid 4CC host interface response; check address, SDA, SCL and GND")
        return PDIdentity(self.bus.read_register(0x00, 4), self.bus.read_register(0x01, 4),
                          self.bus.read_register(0x0F, 4), self.bus.read_register(0x05, 16),
                          mode.decode("ascii").strip())

    @staticmethod
    def validate_range(size, start=0):
        if size <= 0 or size % 4096 or start < 0 or start % 4096 or start + size > 2**32:
            raise ValueError("Flash range must contain complete 4 KiB sectors within the 32-bit address space")

    def read_block(self, address):
        if not 0 <= address <= 2**32 - self.read_size:
            raise ValueError("Flash address is outside the 32-bit address space")
        for attempt in range(4):
            try:
                if self.read_size == 256:
                    answer = self.bus.command(f"PDREAD {self.bus.address:02X} {address:08X} 256")
                    prefix = f"PDREAD {address:08X} "
                    if not answer.startswith(prefix):
                        raise PDError("Invalid Pico PD flash response")
                    data = bytes.fromhex(answer[len(prefix):])
                    if len(data) != 256:
                        raise PDError("Incomplete Pico PD flash response")
                    return data
                if hasattr(self.bus, "flash_read_block"):
                    return self.bus.flash_read_block(address)
                return self.bus.task("FLrd", address.to_bytes(4, "little"), self.READ_SIZE)
            except TransportError as exc:
                transient = str(exc) in ("ERR SDA_LOW_BEFORE_START", "ERR SCL_LOW_TIMEOUT",
                                         "ERR ADDRESS_NACK", "ERR DATA_NACK")
                if not transient or attempt == 3 or not getattr(self.bus, "_synchronized", True):
                    raise
                self.read_retries += 1
                time.sleep(.05 * (attempt + 1))

    def read_flash(self, size, progress=lambda done, total: None, start=0):
        self.validate_range(size, start)
        data = bytearray()
        for offset in range(0, size, self.read_size):
            data.extend(self.read_block(start + offset))
            if len(data) % 1024 == 0 or len(data) == size:
                progress(len(data), size)
        return bytes(data)

    def _checked_task(self, name, data, timeout=3):
        status = self.bus.task(name, data, 1, timeout)
        if status != b"\x00":
            raise PDError(f"{name} failed with status 0x{status[0]:02X}")

    def erase_flash(self, size, progress=lambda done, total: None, start=0):
        self.validate_range(size, start)
        for offset in range(0, size, self.SECTOR_SIZE):
            self._checked_task("FLem", (start + offset).to_bytes(4, "little") + b"\x01", 10)
            progress(offset + self.SECTOR_SIZE, size)

    def write_flash(self, data, progress=lambda done, total: None, start=0):
        self.validate_range(len(data), start)
        # Set each page address explicitly: never depend on a stale write cursor.
        for page in range(0, len(data), 256):
            if data[page:page + 256] == b"\xff" * 256:
                progress(page + 256, len(data))
                continue
            self._checked_task("FLad", (start + page).to_bytes(4, "little"))
            for offset in range(page, min(page + 256, len(data)), self.write_size):
                block = data[offset:offset + self.write_size]
                self._checked_task("FLwd", block)
            progress(min(page + 256, len(data)), len(data))

    def verify_flash(self, expected, progress=lambda done, total: None, start=0):
        self.validate_range(len(expected), start)
        for offset in range(0, len(expected), self.read_size):
            actual = self.read_block(start + offset)
            if actual != expected[offset:offset + len(actual)]:
                raise PDError(f"Verification failed at flash address 0x{start + offset:08X}")
            if (offset + len(actual)) % 1024 == 0 or offset + len(actual) == len(expected):
                progress(offset + len(actual), len(expected))

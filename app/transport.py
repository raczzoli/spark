# SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
# SPDX-License-Identifier: GPL-2.0-or-later

"""USB CDC framing and discovery shared by device command adapters."""
import serial
import time
import secrets
from serial.tools import list_ports


class TransportError(RuntimeError):
    pass


def ports():
    found = list(list_ports.comports())
    found.sort(key=lambda p: (p.vid != 0x2E8A, p.vid is None, p.device))
    return [(p.device, p.description) for p in found]


class PicoTransport:
    COMMAND_TIMEOUTS = {}
    GREETINGS = (b"OK PICO_ITE_EC_PROGRAMMER 2", b"OK PICO_EC_PROBE 1 PROBE_ONLY")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.close()
        except TransportError:
            if exc_type is None:
                raise

    def __init__(self, port, timeout=2):
        self.port = serial.Serial(port, 115200, timeout=timeout, write_timeout=timeout)
        self._caps = None
        self._tagged = False
        self._sequence = secrets.randbits(32)
        self._synchronized = True
        try:
            self.port.reset_input_buffer()
            self._handshake(port, timeout)
            self.port.timeout = timeout
        except Exception:
            self.port.close()
            raise

    def _handshake(self, port, timeout):
        # USB enumeration/open and CDC readiness need not finish together.
        # Retry metadata only, on the same handle and within the original budget.
        # Never replay a target operation or send a leading newline that could
        # complete an interrupted target command in the firmware's input buffer.
        deadline = time.monotonic() + timeout
        pending = b""
        for _ in range(3):
            if time.monotonic() >= deadline:
                break
            self.port.write(b"HELLO\n")
            attempt_deadline = min(deadline, time.monotonic() + timeout / 3)
            while True:
                remaining = attempt_deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.port.timeout = remaining
                chunk = self.port.readline()
                if not chunk:
                    break
                pending += chunk
                while b"\n" in pending:
                    response, pending = pending.split(b"\n", 1)
                    if response.rstrip(b"\r") in self.GREETINGS:
                        return
                if len(pending) > 4096:
                    raise TransportError("Invalid oversized Pico handshake response")
        raise TransportError(f"Pico on {port} did not answer HELLO within {timeout:g}s. "
                             "The device may be starting, busy, or running incompatible firmware.")

    def close(self):
        """Close USB only; target cleanup belongs to the active adapter."""
        self.port.close()

    def command(self, text):
        if not self._synchronized:
            raise TransportError("USB session is out of sync; reconnect before another operation")
        if not text.strip() or "\n" in text or "\r" in text:
            raise ValueError("Expected one USB command")
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        tag = f"@{self._sequence:08X} " if self._tagged else ""
        previous_timeout = self.port.timeout
        timeout = max(previous_timeout or 0, self.COMMAND_TIMEOUTS.get(text.split()[0], 5))
        deadline = time.monotonic() + timeout
        try:
            self.port.write((tag + text + "\n").encode("ascii"))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportError("Timeout USB CDC; command outcome is unknown")
                self.port.timeout = remaining
                response = self.port.readline()
                if not response or not response.endswith(b"\n"):
                    raise TransportError("Timeout USB CDC or incomplete response; reconnect")
                answer = response.decode("ascii").strip()
                # A delayed reply to a retried HELLO can precede CAPS. Once
                # tagging is negotiated, existing tag matching rejects it too.
                if text == "CAPS" and answer.encode("ascii") in self.GREETINGS:
                    continue
                if tag:
                    if not answer.startswith(tag):
                        continue
                    answer = answer[len(tag):]
                break
        except (serial.SerialException, OSError) as exc:
            self._synchronized = False
            raise TransportError(f"USB disconnected or serial error: {exc}") from exc
        except (TransportError, UnicodeError) as exc:
            self._synchronized = False
            raise TransportError(str(exc)) from exc
        finally:
            self.port.timeout = previous_timeout
        if answer.startswith("ERR "):
            raise TransportError(answer)
        return answer

    def capabilities(self):
        if self._caps is None:
            try:
                answer = self.command("CAPS")
            except TransportError as exc:
                if str(exc) != "ERR COMMAND":
                    raise
                self._caps = frozenset()
            else:
                if not answer.startswith("CAPS "):
                    self._synchronized = False
                    raise TransportError(f"Invalid capabilities response: {answer}")
                self._caps = frozenset(answer.split()[1:])
                self._tagged = "TAGGED" in self._caps
        return self._caps

    def supports(self, capability):
        return capability in self.capabilities()

    def firmware_info(self):
        return self.command("INFO") if self.supports("INFO") else "INFO legacy firmware"

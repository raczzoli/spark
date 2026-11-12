# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline connector references; never infer a pinout from a BMS family."""
import json
import re
from functools import lru_cache
from pathlib import Path

ROLE_LABELS = {"ground": "B−", "positive": "B+", "data": "DATA", "clock": "CLOCK",
               "temperature": "TEMP", "present": "PRESENT", "unknown": "?",
               "unused": "NC", "gap": "GAP"}
ROLE_COLORS = {"ground": "#a1afbf", "positive": "#f08087", "data": "#5ed8bd",
               "clock": "#76b8ff", "temperature": "#efc16f", "present": "#c2a4fa",
               "unknown": "#8993a2", "unused": "#8993a2", "gap": "#546174"}


def normalized(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


@lru_cache(maxsize=1)
def catalog():
    data = json.loads((Path(__file__).parent / "assets/battery_catalog.json").read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError("Unsupported battery catalog format")
    return tuple(data["entries"])


def search(query=""):
    terms = [normalized(word) for word in query.split() if normalized(word)]
    found = []
    for entry in catalog():
        text = normalized(" ".join([entry["manufacturer"], entry["model"], *entry.get("aliases", [])]))
        if all(term in text for term in terms):
            found.append(entry)
    key = normalized(query)
    return sorted(found, key=lambda e: (normalized(e["model"]) != key,
                  e["verification"] != "communication_verified", e["manufacturer"], e["model"]))


def connection_for(pin, entry, sda=7, scl=9):
    role = pin["role"]
    if pin.get("uncertain"):
        return "Unconfirmed · check source", "Do not connect until identified"
    if role == "data":
        return f"Pico GP{sda}", "SMBus data"
    if role == "clock":
        return f"Pico GP{scl}", "SMBus clock"
    if role == "ground":
        return "Pico GND", "Common ground; use a confirmed B− contact"
    if role == "positive":
        return "Leave disconnected", "Battery power · never connect to a Pico GPIO"
    if role == "present" and entry.get("present_to_ground"):
        return "Battery B− / GND", "System-present link documented for this variant"
    if role == "present":
        return "Check model instructions", "Enable circuitry varies; do not ground an unidentified contact"
    if role == "temperature":
        return "Leave disconnected", "Not needed for SMBus reading"
    if role in ("unused", "gap"):
        return "No connection", "Unused contact" if role == "unused" else "Connector key / gap"
    return "Unidentified", "Do not connect this contact"


def has_bus_pinout(entry):
    roles = {p["role"] for p in entry["pins"] if not p.get("uncertain")}
    return {"data", "clock", "ground"}.issubset(roles)


def pico_physical(gpio):
    """Only for the standard 40-pin Pico/Pico W/Pico 2 footprint."""
    return {0:1,1:2,2:4,3:5,4:6,5:7,6:9,7:10,8:11,9:12,10:14,11:15,
            12:16,13:17,14:19,15:20,16:21,17:22,18:24,19:25,20:26,
            21:27,22:29,26:31,27:32,28:34}.get(gpio)

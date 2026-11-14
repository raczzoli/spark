"""Build the factual connector catalog from cached public reference pages.

Research-only dependency: beautifulsoup4. The application reads the bundled JSON
and never downloads pinouts or executes content from a source site.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
WIKI = "https://loetlabor-jena.de/doku.php?id=projekte:pinout:laptopbatteries:start"
PACK = "https://powercartel.com/projects/packprobe/battery-connection/"


def pin(text):
    original = text.strip()
    value = original.upper().replace("−", "-").replace("–", "-").replace("—", "-")
    role = "unknown"
    if value in ("-", "--", "GND", "BAT-", "B-"):
        role = "ground"
    elif value in ("+", "++", "V+", "+V", "BAT+", "B+"):
        role = "positive"
    elif value in ("D", "SDA", "SMBD", "DATA", "SMBDATA"):
        role = "data"
    elif value in ("C", "SCL", "SMBC", "CLOCK", "CLK", "SMBCLK"):
        role = "clock"
    elif value in ("T", "TEMP", "TEMPERATURE", "THERMISTOR") or "TEMP" in value:
        role = "temperature"
    elif "SYSPRES" in value or "SYSTEM" in value or value in ("SP", "EN", "SYS", "E", "BE", "ENA"):
        role = "present"
    elif value in ("EMPTY", "GAP", "KEY"):
        role = "gap"
    elif value == "NC":
        role = "unused"
    return {"role": role, "label": original or "?", "uncertain": "?" in original}


def entry(maker, model, aliases, pins, url, orientation, notes="", inferred=False):
    key = re.sub(r"[^a-z0-9]+", "-", f"{maker}-{model}".lower()).strip("-")
    brand=maker.upper() if maker.upper() in ("HP","IBM","MSI","LG","NEC") else maker.title().replace("Ibm", "IBM")
    return {"id": key + "-" + hashlib.sha256((url + str(pins)).encode()).hexdigest()[:6],
            "manufacturer": brand, "model": model, "aliases": aliases,
            "pins": [dict(number=i + 1, **pin(p)) for i, p in enumerate(pins)],
            "orientation": orientation, "notes": notes, "pin_count_inferred": inferred,
            "verification": "documented", "sources": [{"url": url}], "present_to_ground": False}


def wiki_entries(path):
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    for row in soup.select("table tr")[1:]:
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 16:
            continue
        name, maker, notebook, remark = cells[:4]
        if not name:
            name = notebook
        if not name or name == "?":
            continue
        names = [x.strip() for x in name.split(",") if x.strip()]
        pins = cells[4:14]
        while pins and pins[-1].upper() in ("", "X"):
            pins.pop()
        if len(pins) < 3:
            continue
        yield entry("Unspecified" if maker == "?" else maker, names[0], names[1:] + ([] if notebook == "?" else [notebook]),
                    pins, WIKI,
                    "Source view: battery in its installed laptop orientation, with the laptop resting on a table; contacts numbered left to right. Confirm against the connector before wiring.",
                    " ".join(x for x in (remark, "Contact count follows the last described contact; trailing table padding is omitted.") if x and x != "?"), True)


def pack_entries(path):
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    content = soup.select_one(".entry-content") or soup
    maker = "Unspecified"
    for heading in content.find_all(["h3", "h4"]):
        if heading.name == "h3":
            maker = heading.get_text(" ", strip=True)
            continue
        title = heading.get_text(" ", strip=True)
        chunks = []
        for node in heading.next_siblings:
            if getattr(node, "name", None) in ("h3", "h4", "h2"):
                break
            if hasattr(node, "get_text"):
                chunks.append(node.get_text(" ", strip=True))
        text = " ".join(chunks)
        sequences = re.findall(r"(?:[–—−-]|\+\+)\s*[,\.]\s*[^.\n]+", text)
        for sequence in sequences:
            sequence = sequence.split("NOTE")[0].strip().rstrip(".")
            sequence=re.sub(r"^([–—−-])\s*\.\s*",r"\1, ",sequence)
            tokens = [p.strip() for p in sequence.split(",")]
            if not 4 <= len(tokens) <= 12 or not any("++" in p for p in tokens):
                continue
            if any(len(p) > 35 for p in tokens):
                continue
            names = [x.strip() for x in re.split(r",|\(|\)", title) if x.strip()]
            view = ("Looking at the connector from the narrow side of the pack, with the open edge of the contact slots facing up; left to right."
                    if "narrow side" in text else "Connector viewed from the narrow side, bottom surface of the pack facing down; left to right." if "bottom surface" in text else "Source order, left to right. Open the source reference to match the connector view before wiring.")
            record=entry(maker, names[0], names[1:], tokens, PACK, view)
            if names[0]=='IBM-42T4619':record['aliases'].extend(['L11P6R01','45N1037'])
            if names[0]=='9T48V':record['aliases'].append('T54FJ')
            if names[0]=="TD06":
                record['notes']="Source could not read this pack; a later owner comment disputes the data/clock order. Bus contacts require confirmation before connecting."
                for p in record['pins']:
                    if p['role'] in ('data','clock'):p['uncertain']=True
            elif names[0]=="AA-PL2NC8B":
                record['notes']="Source reports an address acknowledgement, but no successful SBS data reading for this pack. Pinout documentation does not establish protocol compatibility."
            yield record
            break


def reviewed_entries(path):
    """Import reviewed facts; preserve the source's view and count limitations."""
    for item in json.loads(path.read_text(encoding="utf-8")):
        record = entry(item["maker"], item["model"], item["aliases"], item["pins"], item["url"],
                       item.get("orientation", "Numbering follows the linked source. Match the B−/B+ landmarks and the battery-versus-cable view before wiring."),
                       item["notes"], item.get("pin_count_inferred", False))
        record["present_to_ground"] = item.get("present_to_ground", False)
        if item.get("reviewed"):
            record["sources"][0]["reviewed"] = item["reviewed"]
        yield record


def model_entries(path, connectors):
    """Add identities without transferring a similar model's connector wiring."""
    def maker_key(value):
        key = re.sub(r"[^A-Z0-9]", "", value.upper())
        return "LENOVO" if key in ("IBM", "IBMLENOVO", "LENOVOIBM") else key

    def name_key(value):
        return re.sub(r"[^A-Z0-9]", "", value.upper())

    existing = {(maker_key(e["manufacturer"]), name_key(name))
                for e in connectors for name in (e["model"], *e.get("aliases", []))}
    data = json.loads(path.read_text(encoding="utf8"))
    if data.get("schema") != 1:
        raise ValueError("Unsupported battery model identity schema")
    for item in data["entries"]:
        maker, model = item["manufacturer"], item["model"]
        key = maker_key(maker), name_key(model)
        aliases = [a for a in item.get("aliases", [])
                   if (maker_key(maker), name_key(a)) not in existing]
        promoted_alias = key in existing
        if promoted_alias:
            if not aliases:
                continue
            # A shared identity listing does not establish the same connector.
            model, aliases = aliases[0], aliases[1:]
        record = entry(maker, model, aliases, [], item["sources"][0]["url"],
                       "No connector pinout is available for this model. Identify the battery contacts independently before connecting it.",
                       item["notes"] + (f" Listed alongside {item['model']}; its connector wiring is not transferred to this reference." if promoted_alias else ""))
        # Source aliases identify the model; they never authorize a pin assignment.
        record.update(manufacturer=maker, verification="model_listed", sources=item["sources"],
                      identity_kind=item.get("identity_kind", "model"))
        yield record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / "build/battery-sources")
    args = parser.parse_args()
    records = list(wiki_entries(args.cache / "wiki.html")) + list(pack_entries(args.cache / "packprobe.html"))
    acer = entry("Acer", "AC14B8K", [], ["-", "-", "D", "C", "T", "SP", "+", "+"],
                 "https://www.laptopu.ro/community/pinouts-for-acer-batteries/acer-ac14b8k-battery-pinout/",
                 "Order from the two negative contacts (black wires) toward the two positive contacts. Match these landmarks; the cable and battery views are mirrored.",
                 "SDA, SCL and ground communication verified on an AC14B8K on 2026-11-12. Other connector revisions must be matched separately.")
    acer.update(verification="communication_verified", present_to_ground=True)
    records.insert(0, acer)
    for filename in ("battery_reviewed.json", "battery_forum_reviewed.json"):
        records.extend(reviewed_entries(ROOT / "devtools" / filename))
    records.extend(model_entries(ROOT / "devtools/battery_models.json", records))
    seen, unique = set(), []
    for record in records:
        key = (record["manufacturer"].lower(), record["model"].lower(), tuple(p["label"] for p in record["pins"]))
        if key not in seen:
            seen.add(key)
            unique.append(record)
    output = ROOT / "app/assets/battery_catalog.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema": 1, "updated": "2026-11-13", "entries": unique}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    connectors = sum(bool(e["pins"]) for e in unique)
    print(f"Catalog: {len(unique)} entries ({connectors} connector references, {len(unique)-connectors} model-only), "
          f"{sum(1 + len(e['aliases']) for e in unique)} searchable names")


if __name__ == "__main__":
    main()

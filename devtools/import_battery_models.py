"""Build model identities from cached public manufacturer/supplier catalogs.

This research utility uses PyMuPDF for PDF tables. It never imports connector
assignments, cell part numbers, laptop compatibility lists or controller support.
The application reads the resulting JSON offline.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
UPDATED = "2026-11-13"
LENOVO_URL = "https://www.lenovo.com/content/dam/lenovo/site-design/esg-document-library/global/battery-msds/BatteryInformationFinder.xlsx"
CREESON_URL = "https://www.laptopu.ro/wp-content/uploads/wpforo/default_attachments/1612006850-laptopS-PINOUT.pdf"
HP_PDF_URL = "https://h20195.www2.hp.com/v2/getpdf.aspx/c07284208.pdf"
HP_INDEX_URL = "https://h20195.www2.hp.com/v2/library.aspx?doctype=103"
DELL_URL = "https://i.dell.com/sites/csdocuments/Legal_Docs/en/BYDSDS20210101.pdf"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MISSING = {"", "0", "N/A", "NA", "NONE", "NOT AVAILABLE", "NOT FOUND", "NULL"}


def normalized(value):
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def identifier(value):
    value = clean(value)
    if value.upper() in MISSING or not re.search(r"\d", value):
        return ""
    if not 3 <= len(value) <= 65 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_./() -]*", value):
        return ""
    return value.upper()


def workbook_rows(path, sheet_name):
    """Read values/identifiers from XLSX without executing workbook formulas."""
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")):
                shared.append("".join(node.text or "" for node in item.iter("{" + NS["s"] + "}t")))
        relationships = {node.attrib["Id"]: node.attrib["Target"] for node in
                         ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next(node for node in workbook.find("s:sheets", NS) if node.attrib["name"] == sheet_name)
        target = relationships[sheet.attrib["{" + REL + "}id"]]
        target = target.lstrip("/") if target.startswith("/") else "xl/" + target
        rows = ET.fromstring(archive.read(target)).find("s:sheetData", NS)
        headers = None
        output = []
        for row in rows:
            cells = {}
            for cell in row:
                value_node = cell.find("s:v", NS)
                if cell.attrib.get("t") == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter("{" + NS["s"] + "}t"))
                elif value_node is None:
                    continue
                else:
                    value = value_node.text or ""
                    if cell.attrib.get("t") == "s":
                        value = shared[int(value)]
                column = re.sub(r"\d", "", cell.attrib["r"])
                cells[column] = clean(value)
            if headers is None:
                headers = cells
                required = {"ASSM PN", "FRU PN", "Battery Model", "SDS Link", "UN38.3 Link"}
                if not required.issubset(set(headers.values())):
                    raise ValueError("Lenovo BatteryData headers changed; review the source before importing")
                continue
            output.append({**{headers.get(column, column): value for column, value in cells.items()},
                           "_row": int(row.attrib["r"])})
        return output


class Models:
    def __init__(self):
        self.entries = {}

    def add(self, maker, model, aliases, source, notes, kind="model"):
        model = identifier(model)
        if not model:
            return
        key = normalized(maker), normalized(model)
        entry = self.entries.setdefault(key, {"manufacturer": maker, "model": model,
            "aliases": [], "sources": [], "notes": notes, "identity_kind": kind})
        seen = {normalized(entry["model"]), *map(normalized, entry["aliases"])}
        for alias in aliases:
            value = identifier(alias)
            if value and normalized(value) not in seen:
                seen.add(normalized(value))
                entry["aliases"].append(value)
        if source not in entry["sources"]:
            entry["sources"].append(source)

    def contains_identifier(self, maker, value):
        key = normalized(value)
        return any(normalized(e["manufacturer"]) == normalized(maker) and key in
                   {normalized(e["model"]), *map(normalized, e["aliases"])} for e in self.entries.values())


def lenovo_models(models, rows):
    notebook_rows = [row for row in rows if any("notebook" in row.get(field, "").lower()
                                              for field in ("SDS Link", "UN38.3 Link"))]
    # A named battery model is preferable to a second entry containing just its ASM.
    for row in sorted(notebook_rows, key=lambda row: not bool(identifier(row.get("Battery Model")))):
        asm, fru = identifier(row.get("ASSM PN")), identifier(row.get("FRU PN"))
        model = identifier(row.get("Battery Model"))
        kind = "model"
        if not model:
            model = asm or fru
            kind = "part_number"
            if model and models.contains_identifier("Lenovo", model):
                continue
        if not model or model.startswith(("CR20", "CR16", "LR44")):
            continue
        source = {"url": LENOVO_URL, "sheet": "BatteryData", "row": row["_row"]}
        models.add("Lenovo", model, [asm, fru], source,
                   "Listed in Lenovo's notebook battery register. ASM and FRU numbers are identification aliases; connector wiring and controller support have not been established.", kind)


def pdf_tables(path):
    import pymupdf
    with pymupdf.open(path) as document:
        for index, page in enumerate(document):
            for table in page.find_tables().tables:
                yield index + 1, table.extract()


def hp_part(value):
    """Normalize only the documented HP part/regulatory-number formats."""
    token = re.sub(r"\s+", "", str(value or "")).upper()
    if token.endswith("-"):
        token = token[:-1]  # PDF text order can put a printed hyphen on the last line.
    if re.fullmatch(r"(?:HSTNN|TPN)-?[A-Z0-9]{3,6}", token):
        prefix = "HSTNN" if token.startswith("HSTNN") else "TPN"
        return prefix + "-" + token[len(prefix):].lstrip("-")
    plain = token.replace("-", "")
    if re.fullmatch(r"[A-Z0-9]{9}", plain) and re.search(r"\d", plain):
        return plain[:6] + "-" + plain[6:]
    return ""


def hp_pdf_models(models, path):
    current_model = ""
    current_rmn = ""
    for page, rows in pdf_tables(path):
        for row in rows:
            if len(row) != 6 or clean(row[0]).replace(" ", "").lower() == "batteryname":
                continue
            model = re.sub(r"\s+", "", row[0] or "").upper()
            if model:
                if not re.fullmatch(r"[A-Z]{2}\d{5}(?:XL)?", model):
                    current_model = current_rmn = ""
                    continue
                current_model, current_rmn = model, ""
            if not current_model:
                continue
            rmn = hp_part(row[1])
            if rmn:
                current_rmn = rmn
            customer = hp_part(row[2])
            models.add("HP", current_model, [current_rmn, customer],
                       {"url": HP_PDF_URL + "#page=" + str(page)},
                       "Battery name and regulatory/customer part numbers published in HP's supplier SDS. This identifies the pack; it does not document its connector.")


def hp_document_models(models, path):
    items = json.loads(path.read_text(encoding="utf8"))
    for item in items:
        if "battery-notebook" not in item.get("doctype", "").lower():
            continue
        part = hp_part(item.get("title"))
        if not part or models.contains_identifier("HP", part):
            continue
        object_name = item.get("objectName", "")
        if not re.fullmatch(r"c\d{8}", object_name):
            continue
        models.add("HP", part, [], {"url": "https://h20195.www2.hp.com/v2/GetDocument.aspx?docname=" + object_name},
                   "Battery part number listed in HP's Notebook and Tablet battery SDS library. A laptop compatibility listing is not a battery connector reference.", "part_number")


def forum_models(models, path):
    """Reviewed names only; an unanswered pinout request supplies no wiring."""
    data = json.loads(path.read_text(encoding="utf8"))
    if data.get("schema") != 1:
        raise ValueError("Unsupported forum identity schema")
    for entry in data["entries"]:
        maker, model = entry["manufacturer"], entry["model"]
        if models.contains_identifier(maker, model):
            continue
        for source in entry["sources"]:
            models.add(maker, model, entry.get("aliases", []), source,
                       entry["notes"], "forum_reference")


BRANDS = {"HP": "HP", "COMPAQ": "Compaq", "DELL": "Dell", "ACER": "Acer", "ASUS": "Asus",
          "APPLE": "Apple", "IBM": "Lenovo", "LENOVO": "Lenovo", "TOSHIBA": "Toshiba",
          "SAMSUNG": "Samsung", "SONY": "Sony", "GATEWAY": "Gateway", "UNIWILL": "Uniwill",
          "MITAC": "Mitac", "FUJITSU": "Fujitsu", "FUJITSU-SIEMENS": "Fujitsu",
          "BENQ": "BenQ", "HASEE": "Hasee", "HAIER": "Haier", "CLEVO": "Clevo", "FIC": "FIC",
          "ECS": "ECS", "MSI": "MSI", "NEC": "NEC", "FOUNDER": "Founder", "TONGFANG": "Tongfang",
          "HEDY": "Hedy", "THUNIS": "Thunis", "BOE": "BOE", "GREATWALL": "Great Wall",
          "TWINHEAD": "Twinhead", "TAMRON": "Tamron", "AMOL": "Amol", "VIOOO": "Viooo",
          "VIEWSONICL": "ViewSonic", "WINBOOK": "Winbook", "COMPOWER": "Compower",
          "NETBOX": "Netbox", "NETBOOK": "Unspecified", "DAREGLOBAL": "Dareglobal",
          "PHILIP": "Unspecified", "LG": "LG", "PANASONIC": "Panasonic", "HITACHI": "Hitachi"}


def creeson_models(models, path):
    for page, rows in pdf_tables(path):
        if page < 3:
            continue
        for row in rows:
            if len(row) != 7:
                continue
            maker_key = re.sub(r"\s+", "", row[1] or "").upper()
            maker = BRANDS.get(maker_key)
            raw_model = row[2] or ""
            # Do not join wrapped codes/underscores or ambiguous multi-model cells.
            if not maker or "\n" in raw_model or "/" in raw_model:
                continue
            model = identifier(raw_model)
            if not model or (model.isdigit() and len(model) < 6):
                continue
            related = clean(row[3])
            aliases = [related] if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{4,35}", related) else []
            models.add(maker, model, aliases, {"url": CREESON_URL + "#page=" + str(page)},
                       "Supplier battery-catalog reference. Related part/model names are search aliases; the source's wiring has not been reviewed for this record and is not imported.", "supplier_reference")


def dell_models(models, path):
    for page, rows in pdf_tables(path):
        if page > 1:
            break
        for row in rows:
            if len(row) != 4:
                continue
            model, part = clean(row[0]), clean(row[1])
            if not re.fullmatch(r"[A-Z0-9]{5}", model) or not re.fullmatch(r"[A-Z0-9]{5}", part):
                continue
            models.add("Dell", model, [part], {"url": DELL_URL + "#page=1"},
                       "Battery EE specification and Dell part number published in Dell's BYD SDS. Connector layout and controller features are not provided.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / "build/battery-model-sources")
    args = parser.parse_args()
    models = Models()
    lenovo_models(models, workbook_rows(args.cache / "lenovo.xlsx", "BatteryData"))
    hp_pdf_models(models, args.cache / "hp-wistron.pdf")
    hp_document_models(models, args.cache / "hp-notebook-documents.json")
    forum_path = ROOT / "devtools/battery_forum_models.json"
    forum_models(models, forum_path)
    creeson_models(models, args.cache / "creeson.pdf")
    dell_models(models, args.cache / "dell-byd.pdf")
    entries = sorted(models.entries.values(), key=lambda e: (e["manufacturer"].casefold(), e["model"].casefold()))
    source_files = {"lenovo.xlsx": LENOVO_URL, "hp-wistron.pdf": HP_PDF_URL,
                    "hp-notebook-documents.json": HP_INDEX_URL, "creeson.pdf": CREESON_URL,
                    "dell-byd.pdf": DELL_URL}
    data = {"schema": 1, "updated": UPDATED,
            "source_files": {name: {"url": url, "sha256": hashlib.sha256((args.cache / name).read_bytes()).hexdigest()}
                             for name, url in source_files.items()},
            "entries": entries}
    data["source_files"]["battery_forum_models.json"] = {
        "url": "https://www.laptopu.ro/community/", "sha256": hashlib.sha256(forum_path.read_bytes()).hexdigest()}
    output = ROOT / "devtools/battery_models.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"identities": len(entries), "names": sum(1 + len(e["aliases"]) for e in entries),
                      "brands": dict(Counter(e["manufacturer"] for e in entries))}, ensure_ascii=True))


if __name__ == "__main__":
    main()

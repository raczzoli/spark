# SPDX-License-Identifier: GPL-2.0-or-later
"""Local PD backup and physical flash validation, using the production driver."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pd import PDTransport, PDDevice


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "sector-cycle", "full-cycle", "verify"))
    parser.add_argument("--port", required=True)
    parser.add_argument("--address", type=lambda text: int(text, 0), default=0x38)
    parser.add_argument("--sda", type=int, default=3)
    parser.add_argument("--scl", type=int, default=2)
    parser.add_argument("--size-kib", type=int, default=256)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "action": args.action, "stages": []}

    def save():
        args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def stage(name, operation):
        entry = {"name": name, "started_seconds": round(time.monotonic() - started, 2)}
        report["stages"].append(entry)
        save()
        print(name, flush=True)
        result = operation()
        entry["completed_seconds"] = round(time.monotonic() - started, 2)
        save()
        return result

    def progress(done, total):
        if done % 16384 == 0 or done == total:
            print(f'{report["stages"][-1]["name"]}: {done//1024}/{total//1024} KiB ({time.monotonic()-started:.1f}s)', flush=True)

    try:
        with PDTransport(args.port, (args.sda, args.scl), args.address) as bus:
            pd = PDDevice(bus)
            identity = pd.identify()
            report["identity"] = {k: v.hex() if isinstance(v, bytes) else v for k, v in vars(identity).items()}
            size = args.size_kib * 1024
            pd.validate_range(size)
            if args.action == "backup":
                hashes = []
                for number in (1, 2):
                    partial = args.output.with_suffix(f".read{number}.partial")
                    final = args.output.with_suffix(".bin" if number == 1 else ".second.bin")
                    def read_to_file():
                        with partial.open("xb") as stream:
                            for offset in range(0, size, 4096):
                                data = pd.read_flash(4096, start=offset)
                                stream.write(data)
                                stream.flush()
                                progress(offset + 4096, size)
                        if final.exists():
                            raise FileExistsError(final)
                        partial.rename(final)
                        return final.read_bytes()
                    data = stage(f"Read {number}", read_to_file)
                    hashes.append(digest(data))
                    report.setdefault("backups", []).append({"path": str(final.resolve()), "sha256": hashes[-1], "size": len(data)})
                    save()
                if hashes[0] != hashes[1] or len(set(data)) < 2:
                    raise RuntimeError("Complete backup reads differ or contain no nonuniform data")
                report["verified_matching_reads"] = True
            else:
                if args.original is None:
                    raise ValueError("Provide --original with a verified backup image")
                original = args.original.read_bytes()
                manifest = json.loads(args.original.with_suffix(".json").read_text(encoding="utf-8"))
                if (not manifest.get("verified_matching_reads") or len(original) != size
                        or digest(original) != manifest["backups"][0]["sha256"]
                        or identity.uid.hex() != manifest["identity"]["uid"]):
                    raise ValueError("Backup verification, size or connected UID does not match")
                report["original_path"] = str(args.original.resolve())
                report["original_sha256"] = digest(original)
                if args.action == "sector-cycle":
                    start = size - 4096
                    report["sector_start"] = start
                    saved = original[start:start + 4096]
                    stage("Verify original sector", lambda: pd.verify_flash(saved, start=start))
                    pattern = bytes(((i * 73) ^ (i >> 3) ^ 0xA5) & 255 for i in range(4096))
                    try:
                        stage("Erase sector", lambda: pd.erase_flash(4096, start=start))
                        stage("Verify blank sector", lambda: pd.verify_flash(b"\xff" * 4096, start=start))
                        stage("Program pattern", lambda: pd.write_flash(pattern, start=start))
                        stage("Verify pattern", lambda: pd.verify_flash(pattern, start=start))
                    finally:
                        stage("Erase sector for restoration", lambda: pd.erase_flash(4096, start=start))
                        stage("Restore original sector", lambda: pd.write_flash(saved, start=start))
                        stage("Verify original sector restored", lambda: pd.verify_flash(saved, start=start))
                elif args.action == "full-cycle":
                    try:
                        stage("Erase complete flash", lambda: pd.erase_flash(size, progress))
                        stage("Verify complete flash blank", lambda: pd.verify_flash(b"\xff" * size, progress))
                    finally:
                        stage("Restore complete original", lambda: pd.write_flash(original, progress))
                        stage("Verify complete original restored", lambda: pd.verify_flash(original, progress))
                    report["original_restored"] = True
                else:
                    stage("Verify complete original", lambda: pd.verify_flash(original, progress))
                    report["original_restored"] = True
            report["read_retries"] = pd.read_retries
            report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        save()
        print("REPORT", args.output.with_suffix(".json").resolve(), flush=True)


if __name__ == "__main__":
    main()

"""Read Mach-O/ar metadata without running target code; standard library only."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import plistlib
import struct

TARGETS = {"ios_arm64": (0x0100000C, 2), "ios_arm64_simulator": (0x0100000C, 7),
           "ios_x86_64_simulator": (0x01000007, 7)}


def native_records(data: bytes, name: str):
    """Yield objects inside thin/fat Mach-O files and BSD/GNU ar archives."""
    if data.startswith(b"!<arch>\n"):
        offset = 8
        while offset + 60 <= len(data):
            header = data[offset:offset + 60]
            if header[58:] != b"`\n":
                raise ValueError(f"Invalid archive header: {name}")
            length = int(header[48:58])
            member = header[:16].decode("ascii", "replace").strip()
            body = data[offset + 60:offset + 60 + length]
            if member.startswith("#1/"):
                count = int(member[3:])
                member, body = body[:count].rstrip(b"\0").decode("utf-8", "replace"), body[count:]
            yield from native_records(body, f"{name}({member})")
            offset += 60 + length + length % 2
        return
    fat = {b"\xca\xfe\xba\xbe": (">", False), b"\xbe\xba\xfe\xca": ("<", False),
           b"\xca\xfe\xba\xbf": (">", True), b"\xbf\xba\xfe\xca": ("<", True)}
    if data[:4] in fat:
        endian, wide = fat[data[:4]]
        count = struct.unpack_from(endian + "I", data, 4)[0]
        size = 32 if wide else 20
        for index in range(count):
            pos = 8 + index * size
            if wide:
                cpu, subtype, offset, length, align, reserved = struct.unpack_from(endian + "IIQQII", data, pos)
            else:
                cpu, subtype, offset, length, align = struct.unpack_from(endian + "IIIII", data, pos)
            yield from native_records(data[offset:offset + length], f"{name}[{cpu:#x}]")
        return
    magic = data[:4]
    if magic not in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce"}:
        return
    endian = "<" if magic[0] in {0xCF, 0xCE} else ">"
    cpu, subtype, kind, count = struct.unpack_from(endian + "IIII", data, 4)
    offset = 32 if magic in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"} else 28
    platform = minimum = None
    for _ in range(count):
        command, size = struct.unpack_from(endian + "II", data, offset)
        if size < 8 or offset + size > len(data):
            raise ValueError(f"Invalid Mach-O load command: {name}")
        if command == 0x32:  # LC_BUILD_VERSION
            platform, minimum = struct.unpack_from(endian + "II", data, offset + 8)
        elif command in {0x24, 0x25}:  # legacy LC_VERSION_MIN_MACOSX/IPHONEOS
            minimum = struct.unpack_from(endian + "I", data, offset + 8)[0]
            platform = 1 if command == 0x24 else (7 if cpu == 0x01000007 else 2)
        offset += size
    yield {"name": name, "cpu": cpu, "kind": kind, "platform": platform, "minimum": minimum}


def validate(records, target, maximum=None):
    cpu, platform = TARGETS[target]
    selected = [r for r in records if r["cpu"] == cpu]
    if not selected:
        raise ValueError(f"No {target} Mach-O objects found")
    failures = []
    for record in selected:
        if record["platform"] not in {None, platform}:
            failures.append(f'{record["name"]}: platform {record["platform"]}, expected {platform}')
        if maximum is not None and record["minimum"] is not None and record["minimum"] > maximum:
            failures.append(f'{record["name"]}: minimum newer than requested iOS')
    if failures:
        raise ValueError("\n".join(failures[:20]))
    return selected


def version(value):
    if value is None:
        return "unspecified"
    return f"{value >> 16}.{(value >> 8) & 255}.{value & 255}"


def runtime(path, target):
    metadata = plistlib.loads((path / "Info.plist").read_bytes())
    cpu, platform = TARGETS[target]
    arch = "arm64" if cpu == 0x0100000C else "x86_64"
    matches = [x for x in metadata["AvailableLibraries"] if x["SupportedPlatform"] == "ios"
               and arch in x["SupportedArchitectures"]
               and (x.get("SupportedPlatformVariant") == "simulator") == (platform == 7)]
    if len(matches) != 1:
        raise ValueError(f"Expected one matching runtime slice, found {len(matches)}")
    entry = matches[0]
    framework = path / entry["LibraryIdentifier"] / entry["LibraryPath"]
    if not (framework / "Headers/Python.h").is_file():
        raise ValueError("Runtime Python.h missing")
    if not (path / "lib/python3.15/encodings/__init__.py").is_file():
        raise ValueError("Common Python 3.15 standard library missing")
    records = validate(list(native_records((framework / "Python").read_bytes(), "Python.framework/Python")), target)
    return {"runtime": str(path), "target": target, "slice": entry["LibraryIdentifier"],
            "minimum_ios": [version(r["minimum"]) for r in records], "audit_passed": True,
            "runtime_execution_tested_by_this_audit": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["runtime"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--target", choices=TARGETS, required=True)
    args = parser.parse_args()
    print(json.dumps(runtime(args.path, args.target), indent=2))

"""Read Mach-O/ar metadata without running target code; standard library only."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import plistlib
import re
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


def runtime(path, target, maximum=None):
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
    header = (framework / "Headers/patchlevel.h").read_text()
    major = re.search(r"#define\s+PY_MAJOR_VERSION\s+(\d+)", header).group(1)
    minor = re.search(r"#define\s+PY_MINOR_VERSION\s+(\d+)", header).group(1)
    python_version = f"{major}.{minor}"
    if not (path / f"lib/python{python_version}/encodings/__init__.py").is_file():
        raise ValueError(f"Common Python {python_version} standard library missing")
    records = validate(list(native_records((framework / "Python").read_bytes(), "Python.framework/Python")), target, maximum)
    extensions = path / entry["LibraryIdentifier"] / f"lib-{arch}/python{python_version}/lib-dynload"
    extension_files = sorted(extensions.glob("*.so"))
    if not extension_files:
        raise ValueError(f"Pinned runtime native extensions missing: {extensions}")
    extension_minimums = Counter()
    for extension in extension_files:
        selected = validate(list(native_records(extension.read_bytes(), extension.name)), target, maximum)
        extension_minimums.update(version(r["minimum"]) for r in selected)
    return {"runtime": str(path), "target": target, "python_version": python_version, "slice": entry["LibraryIdentifier"],
            "minimum_ios": [version(r["minimum"]) for r in records], "audit_passed": True,
            "native_extension_count": len(extension_files), "native_extension_minimums": dict(extension_minimums),
            "runtime_execution_tested_by_this_audit": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["runtime"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--max-ios", help="Reject runtime/native extensions requiring a newer iOS version")
    args = parser.parse_args()
    maximum = None
    if args.max_ios:
        parts = [int(x) for x in args.max_ios.split(".")]
        parts += [0] * (3 - len(parts))
        maximum = (parts[0] << 16) | (parts[1] << 8) | parts[2]
    print(json.dumps(runtime(args.path, args.target, maximum), indent=2))

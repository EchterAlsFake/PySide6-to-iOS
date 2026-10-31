"""Audit one matching PySide6/shiboken6 iOS pair; does not install or execute it."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
from pathlib import PurePosixPath
import plistlib
import re
import zipfile

spec = importlib.util.spec_from_file_location("ios_audit", Path(__file__).with_name("inspect-ios.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def check(directory, target, maximum, python_version="3.15"):
    python_tag = "cp" + python_version.replace(".", "")
    output = []
    for package in ["pyside6", "shiboken6"]:
        matches = [p for p in directory.glob("*.whl") if p.name.lower().startswith(package + "-")
                   and p.name.endswith(f"-{python_tag}-{python_tag}-{target}.whl")]
        if len(matches) != 1:
            raise ValueError(f"Expected one {package} wheel for CPython {python_version} / {target}, found {matches}")
        path = matches[0]
        if not re.search(r"-6\.12\.0-.*-" + python_tag + "-" + python_tag + "-", path.name, re.I):
            raise ValueError(f"Expected Qt/PySide 6.12.0 / CPython {python_version}: {path.name}")
        count = 0
        minimums = Counter()
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"ZIP CRC error: {bad}")
            metadata_name = next(n for n in archive.namelist() if n.endswith(".dist-info/WHEEL"))
            metadata = archive.read(metadata_name).decode()
            if f"Tag: {python_tag}-{python_tag}-{target}" not in metadata:
                raise ValueError("Internal WHEEL tag does not match filename")
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                parts = PurePosixPath(name).parts
                skip = False
                for index, part in enumerate(parts[:-1]):
                    if not part.endswith(".xcframework"):
                        continue
                    prefix = "/".join(parts[:index + 1])
                    xcinfo = plistlib.loads(archive.read(prefix + "/Info.plist"))
                    cpu, platform = audit.TARGETS[target]
                    arch = "arm64" if cpu == 0x0100000C else "x86_64"
                    selected_slices = {x["LibraryIdentifier"] for x in xcinfo["AvailableLibraries"]
                        if x["SupportedPlatform"] == "ios" and arch in x["SupportedArchitectures"]
                        and (x.get("SupportedPlatformVariant") == "simulator") == (platform == 7)}
                    if parts[index + 1] not in selected_slices:
                        skip = True
                        break
                if skip:
                    continue
                # Peek first; avoids reading all non-native QML/docs/resources into memory.
                with archive.open(name) as stream:
                    magic = stream.read(8)
                if magic.startswith(b"\x7fELF"):
                    raise ValueError(f"Non-iOS ELF binary inside target wheel: {name}")
                if magic[:4] not in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"} and magic != b"!<arch>\n":
                    continue
                records = list(audit.native_records(archive.read(name), name))
                if not records:  # Empty static import/resource archives contain no executable code.
                    continue
                try:
                    chosen = audit.validate(records, target, maximum)
                except ValueError as error:
                    raise ValueError(f"{path.name}: {name}: {error}") from error
                count += len(chosen)
                minimums.update(audit.version(r["minimum"]) for r in chosen)
        if not count:
            raise ValueError(f"No target code found in {path.name}")
        output.append({"wheel": path.name, "target_objects": count, "minimum_ios": dict(minimums),
                       "crc_and_target_audit_passed": True})
    return {"target": target, "wheels": output, "runtime_execution_tested_by_this_audit": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--target", choices=audit.TARGETS, required=True)
    parser.add_argument("--python-version", choices=["3.10", "3.11", "3.12", "3.13", "3.14", "3.15"], default="3.15")
    parser.add_argument("--max-ios", help="Reject native deployment targets newer than this version")
    args = parser.parse_args()
    maximum = None
    if args.max_ios:
        parts = [int(x) for x in args.max_ios.split(".")]
        parts += [0] * (3 - len(parts))
        maximum = (parts[0] << 16) | (parts[1] << 8) | parts[2]
    print(json.dumps(check(args.directory, args.target, maximum, args.python_version), indent=2))

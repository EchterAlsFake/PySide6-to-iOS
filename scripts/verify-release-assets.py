"""Check downloaded release files against SHA256SUMS without executing artifacts.

By default checks the listed files present in the directory. --all requires
every listed file; --target requires the matching PySide6/shiboken6 wheel pair.
Verify SHA256SUMS.asc with GPG separately when checking publisher identity.
"""
import argparse
import hashlib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--all", action="store_true", dest="require_all")
    parser.add_argument("--target", choices=["ios_arm64", "ios_arm64_simulator", "ios_x86_64_simulator"])
    parser.add_argument("--python-version", choices=["3.10", "3.11", "3.12", "3.13", "3.14", "3.15"],
                        help="Select a wheel pair in a multi-version release")
    args = parser.parse_args()
    directory = args.directory.resolve()
    entries = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.removeprefix("*")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise SystemExit("Invalid SHA-256 entry")
        if Path(name).name != name or name in {".", ".."} or name in entries:
            raise SystemExit(f"Invalid or duplicate asset name: {name}")
        entries[name] = digest
    required = set(entries) if args.require_all else set()
    if args.target:
        suffix = "-" + args.target + ".whl"
        if args.python_version:
            tag = "cp" + args.python_version.replace(".", "")
            suffix = f"-{tag}-{tag}-{args.target}.whl"
        for package in ["pyside6", "shiboken6"]:
            matches = [name for name in entries if name.startswith(package + "-")
                       and name.endswith(suffix)]
            if len(matches) != 1:
                raise SystemExit(f"Expected one {package} wheel for {args.target} in SHA256SUMS")
            required.update(matches)
    checked = 0
    for name, expected in entries.items():
        path = directory / name
        if not path.exists():
            if name in required:
                raise SystemExit(f"Missing required asset: {name}")
            continue
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"Expected an ordinary release file: {name}")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise SystemExit(f"SHA-256 mismatch: {name}")
        checked += 1
        print(f"OK {name}")
    if not checked:
        raise SystemExit("No release assets were checked")
    print(f"Verified {checked} downloaded assets; {len(entries) - checked} listed assets were not downloaded.")


if __name__ == "__main__":
    main()

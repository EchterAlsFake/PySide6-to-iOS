"""Apply pinned iOS static-link and Python compatibility fixes to PySide6 6.12.0.

Use --python to select the deployment virtualenv. This changes only its iOS
Xcode-project generator. The full-matrix wheels supply the required archives.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Python in the deployment virtualenv")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    versions = json.loads((here / "versions.json").read_text())
    infos = [versions["ios_deploy_patch"], *versions.get("ios_deploy_additional_patches", [])]
    output = subprocess.check_output([args.python, "-c",
        "import json,pathlib,PySide6; print(json.dumps([PySide6.__version__,str(pathlib.Path(PySide6.__file__).parent/'scripts')]))"], text=True)
    version, directory = json.loads(output)
    if version != "6.12.0":
        raise SystemExit(f"This patch requires PySide6 6.12.0; found {version}")
    pending = []
    for info in infos:
        patch = here / "patches" / info["file"]
        if hashlib.sha256(patch.read_bytes()).hexdigest() != info["sha256"]:
            raise SystemExit(f"Deployment patch checksum mismatch: {patch}")
        base = ["patch", "-p1", "--force", "--silent", "-i", str(patch)]
        reverse = subprocess.run([*base, "--dry-run", "--reverse"], cwd=directory,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if reverse.returncode == 0:
            print(f"Already applied: {patch.name}")
            continue
        check = subprocess.run([*base, "--dry-run", "--forward"], cwd=directory,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if check.returncode:
            raise SystemExit("Deployment patch conflicts; installed files were left unchanged.\n" + check.stdout.decode())
        pending.append(base)
    for base in pending:
        subprocess.run([*base, "--forward"], cwd=directory, check=True)
    print(f"Deployment compatibility patches ready: {directory}")


if __name__ == "__main__":
    main()

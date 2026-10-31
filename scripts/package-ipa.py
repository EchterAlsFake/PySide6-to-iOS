"""Package a device app for re-signing with iLoader or SideStore.

Works on a separate copy. Does not modify the jailbroken-phone build or install
anything. The result has ad-hoc signatures and must be provisioned/re-signed by
the sideloader before a stock iPhone can run it.
"""
from pathlib import Path
import argparse
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
import zipfile

guide = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--app", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--bundle-id", help="Optional distinct test identifier")
parser.add_argument("--display-name", help="Optional distinct test display name")
parser.add_argument("--share-documents", action="store_true",
                    help="Expose the app's Documents folder in Files for test reports")
args = parser.parse_args()
source = args.app.resolve()
output = args.output.resolve()
staging = output.parent / (output.stem + "-staging")
if output.exists() or staging.exists():
    raise SystemExit("Output or staging directory already exists; choose a new --output")
assert source.is_dir() and (source / "Info.plist").is_file()
payload = staging / "Payload"
payload.mkdir(parents=True)
app = payload / source.name
subprocess.run(["/usr/bin/ditto", "--norsrc", "--noextattr", str(source), str(app)], check=True)
removed = []
# The wheel's Qt/lib tree is a build kit, not the application's embedded dylibs.
# Keep QML/resources; runtime shared libraries must already be in app/Frameworks.
qt_build_lib = app / "packages/PySide6/Qt/lib"
if qt_build_lib.exists():
    removed.append(str(qt_build_lib.relative_to(app)))
    shutil.rmtree(qt_build_lib)
for path in sorted(app.rglob("*"), key=lambda p: len(p.parts), reverse=True):
    if path.is_dir() and path.name in {"__pycache__", "_CodeSignature"}:
        removed.append(str(path.relative_to(app)))
        shutil.rmtree(path)
    elif path.is_file() and (path.suffix in {".o", ".a", ".prl", ".cmake"}
                            or path.name in {"embedded.mobileprovision", ".DS_Store"}):
        removed.append(str(path.relative_to(app)))
        path.unlink()
info = plistlib.loads((app / "Info.plist").read_bytes())
if args.bundle_id:
    info["CFBundleIdentifier"] = args.bundle_id
if args.display_name:
    info["CFBundleDisplayName"] = args.display_name
scene = info.setdefault("UIApplicationSceneManifest", {})
scene.setdefault("UIApplicationSupportsMultipleScenes", False)
configurations = scene.setdefault("UISceneConfigurations", {})
application_scenes = configurations.setdefault("UIWindowSceneSessionRoleApplication", [
    {"UISceneConfigurationName": "Default Configuration"}])
for configuration in application_scenes:
    # The generated plist may already have a manifest but omit Qt's delegate.
    configuration.setdefault("UISceneDelegateClassName", "QIOSWindowSceneDelegate")
info.setdefault("UILaunchScreen", {})
if args.share_documents:
    info["UIFileSharingEnabled"] = True
    info["LSSupportsOpeningDocumentsInPlace"] = True
(app / "Info.plist").write_bytes(plistlib.dumps(info))
empty = staging / "empty.entitlements.plist"
empty.write_bytes(plistlib.dumps({}))
frameworks = sorted((app / "Frameworks").glob("*.framework"))
normalized_frameworks = []
for framework in frameworks:
    metadata_path = framework / "Info.plist"
    metadata = plistlib.loads(metadata_path.read_bytes())
    if metadata.get("CFBundlePackageType") != "FMWK":
        metadata["CFBundlePackageType"] = "FMWK"
        normalized_frameworks.append(framework.name)
    metadata_path.write_bytes(plistlib.dumps(metadata))
signatures = []
for target in [*frameworks, app]:
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none",
                    "--entitlements", str(empty), "--generate-entitlement-der", str(target)], check=True)
    result = subprocess.run(["/usr/bin/codesign", "-d", "--entitlements", "-", "--xml", str(target)],
                            capture_output=True, check=True)
    entitlements = plistlib.loads(result.stdout) if result.stdout.strip() else {}
    assert entitlements == {}, (target, entitlements)
    signatures.append(str(target.relative_to(payload)))
subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], check=True)

# Ensure runtime executable code is entirely inside the expected signed bundles.
executables = {app / info["CFBundleExecutable"]}
for framework in frameworks:
    metadata = plistlib.loads((framework / "Info.plist").read_bytes())
    executables.add(framework / metadata["CFBundleExecutable"])
native_code = []
for path in app.rglob("*"):
    if not path.is_file() or path.is_symlink():
        continue
    with path.open("rb") as stream:
        header = stream.read(32)
    if header[:4] == b"\xcf\xfa\xed\xfe":
        assert path in executables, f"Unexpected Mach-O outside signed framework: {path}"
        cpu, subtype, filetype = struct.unpack_from("<III", header, 4)
        assert cpu == 0x0100000C, (path, "not arm64")
        assert filetype in {2, 6}, (path, "not an executable or dynamic library")
        with path.open("rb") as stream:
            header = stream.read(32)
            platform_found = False
            for _ in range(struct.unpack_from("<I", header, 16)[0]):
                cmd, size = struct.unpack("<II", stream.read(8))
                body = stream.read(size - 8)
                if cmd == 0x32:
                    platform, minimum = struct.unpack_from("<II", body)
                    assert platform == 2, (path, "not device iOS")
                    bits = [int(x) for x in info["MinimumOSVersion"].split(".")]
                    bits += [0] * (3 - len(bits))
                    advertised = (bits[0] << 16) | (bits[1] << 8) | bits[2]
                    assert minimum <= advertised, (path, "native minimum exceeds app minimum")
                    platform_found = True
            assert platform_found, (path, "requires LC_BUILD_VERSION for this audited workflow")
        native_code.append(str(path.relative_to(app)))
assert len(native_code) == len(frameworks) + 1
for marker in app.rglob("*.fwork"):
    relative = marker.read_text().strip()
    assert not Path(relative).is_absolute(), marker
    assert (app / relative).is_file(), (marker, relative)
subprocess.run(["/usr/bin/ditto", "-c", "-k", "--keepParent", "--norsrc", "--noextattr",
                str(payload), str(output)], check=True)
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert names and all(name == "Payload/" or name.startswith("Payload/") for name in names)
    assert f"Payload/{app.name}/Info.plist" in names
    assert not any(name.endswith("embedded.mobileprovision") for name in names)
    assert not any(name.endswith((".o", ".a", ".prl", ".cmake")) for name in names)
    entries = len(names)
with output.open("rb") as stream:
    sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
report = {"ipa": str(output), "bytes": output.stat().st_size, "sha256": sha256,
          "bundle_id": info["CFBundleIdentifier"], "minimum_ios": info["MinimumOSVersion"],
          "architecture": "arm64", "framework_count": len(frameworks), "zip_entries": entries,
          "signing": "Apple codesign ad-hoc; requires sideloader re-signing and provisioning",
          "entitlements": {}, "private_gpu_entitlement_removed": True,
          "nested_signature_verification_passed": True, "zip_crc_verification_passed": True,
          "native_extension_framework_markers_valid": True,
          "framework_bundle_types_normalized": normalized_frameworks,
          "stock_device_runtime_tested": False, "source_app_unchanged": True,
          "removed_build_only_entries": removed}
output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
output.with_suffix(".ipa.sha256").write_text(f"{sha256}  {output.name}\n")
print(json.dumps({k:v for k,v in report.items() if k != "removed_build_only_entries"}, indent=2))

import hashlib
import json
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "site" / "assets" / "vendor" / "mathjax-3.2.2"


def test_vendored_mathjax_matches_recorded_digests():
    manifest = json.loads((VENDOR / "VENDOR.json").read_text())
    assert manifest["version"] == "3.2.2" and manifest["integrity"].startswith("sha512-")
    on_disk = {p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob("*") if p.is_file() and p.name not in {"VENDOR.json", ".DS_Store"}}
    assert on_disk == set(manifest["files"])
    for rel, digest in manifest["files"].items():
        assert "sha256:" + hashlib.sha256((VENDOR / rel).read_bytes()).hexdigest() == digest, rel

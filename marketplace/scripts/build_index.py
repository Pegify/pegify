#!/usr/bin/env python3
"""Build dist/v1/index.json from all marketplace/packages/*/manifest.yaml files."""
import json
import shutil
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
PACKAGES_DIR = REPO_ROOT / "marketplace" / "packages"
OUT_DIR = REPO_ROOT / "dist" / "v1"
OUT_DIR.mkdir(parents=True, exist_ok=True)

packages = []
for manifest_path in sorted(PACKAGES_DIR.glob("*/manifest.yaml")):
    with open(manifest_path) as f:
        m = yaml.safe_load(f)
    name = manifest_path.parent.name
    base = f"https://pegify.github.io/pegify/v1/packages/{name}"
    packages.append({
        "name": m["name"],
        "version": m["version"],
        "kind": m["kind"],
        "description": m.get("description", ""),
        "author": m.get("author", ""),
        "manifest_url": f"{base}/manifest.yaml",
    })
    out_pkg = OUT_DIR / "packages" / name
    out_pkg.mkdir(parents=True, exist_ok=True)
    shutil.copy(manifest_path, out_pkg / "manifest.yaml")
    prompt = manifest_path.parent / "prompt.md"
    if prompt.exists():
        shutil.copy(prompt, out_pkg / "prompt.md")

index = {"packages": packages}
out_path = OUT_DIR / "index.json"
out_path.write_text(json.dumps(index, indent=2))
print(f"Built index with {len(packages)} packages → {out_path}")

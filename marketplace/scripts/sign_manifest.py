#!/usr/bin/env python3
"""Sign a manifest.yaml in-place using Ed25519.

Usage: REGISTRY_SIGNING_KEY=<base64-priv> python marketplace/scripts/sign_manifest.py marketplace/packages/tdd/manifest.yaml
"""
import base64
import os
import sys
from pathlib import Path
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _body_yaml(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return yaml.dump(body, default_flow_style=False, sort_keys=True)


priv_b64 = os.environ.get("REGISTRY_SIGNING_KEY", "").strip()
if not priv_b64:
    sys.exit("Set REGISTRY_SIGNING_KEY env var to base64-encoded private key")

priv_bytes = base64.b64decode(priv_b64)
priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)

for path_arg in sys.argv[1:]:
    p = Path(path_arg)
    manifest = yaml.safe_load(p.read_text())
    body = _body_yaml(manifest)
    sig = priv.sign(body.encode())
    manifest["signature"] = base64.b64encode(sig).decode()
    p.write_text(yaml.dump(manifest, default_flow_style=False, sort_keys=True))
    print(f"Signed: {p}")

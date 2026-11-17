"""Freeze repository source for repeatable tests while other work continues.

Copies source only. Never copies a .env file, credentials, uploads, Git internals,
virtual environments or database state. The disposable runner supplies test config.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "scratch" / "payroll-verification-20261115"


def main():
    label = sys.argv[1]
    if not label.replace("-", "").isalnum():
        raise ValueError("Use an alphanumeric snapshot label")
    destination = STATE / label
    destination.mkdir(exist_ok=False)
    files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT).decode().split("\0")
    excluded = {"verification", "scratch", "uploads", ".git", ".agents", ".codex", ".aws", "node_modules"}
    manifest = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "files": {}}
    for name in sorted(set(files)):
        path = Path(name)
        if not name or path.parts[0] in excluded or path.parts[0].startswith(".venv"):
            continue
        if path.name == ".env" or path.name.startswith(".env.") and path.name not in {".env.example", ".env.template"}:
            continue
        if "credentials" in path.name.lower() or path.name in {"query", "qc"}:
            continue
        source = ROOT / path
        if not source.is_file() or source.is_symlink():
            continue
        data = source.read_bytes()
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest["files"][name] = hashlib.sha256(data).hexdigest()
    manifest["source_digest"] = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    (destination / "verification-source-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"snapshot": str(destination), "files": len(manifest["files"]), "source_digest": manifest["source_digest"]}, indent=2))


if __name__ == "__main__":
    main()

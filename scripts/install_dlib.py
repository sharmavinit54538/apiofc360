"""Provisions dlib using prebuilt binary wheels when available, with optimized parallel fallback."""

from __future__ import annotations

import io
import json
import os
import platform
import re
import subprocess
import sys
import urllib.request
import zipfile

DLIB_VERSION = "20.0.1"


def install_prebuilt_dlib() -> bool:
    """Attempt to install precompiled dlib binary wheel from PyPI dlib-bin."""
    v = sys.version_info
    py_tag = f"cp{v.major}{v.minor}"

    mach = platform.machine().lower()
    if mach in ("x86_64", "amd64"):
        arch_tag = "x86_64"
    elif mach in ("aarch64", "arm64"):
        arch_tag = "aarch64"
    else:
        print(f"[install_dlib] Unsupported platform architecture: {mach}")
        return False

    print(f"[install_dlib] Checking for prebuilt binary wheel: {py_tag}-{arch_tag}...")
    try:
        url = "https://pypi.org/pypi/dlib-bin/json"
        req = urllib.request.Request(url, headers={"User-Agent": "DockerBuild/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        releases = data.get("releases", {}).get(DLIB_VERSION, [])

        matched = None
        for file_info in releases:
            fn = file_info.get("filename", "")
            if py_tag in fn and arch_tag in fn and "manylinux" in fn:
                matched = file_info
                break

        if not matched:
            print(f"[install_dlib] No prebuilt manylinux wheel found on PyPI for {py_tag}-{arch_tag}")
            return False

        wheel_url = matched["url"]
        orig_filename = matched["filename"]
        target_filename = orig_filename.replace("dlib_bin", "dlib")
        print(f"[install_dlib] Downloading prebuilt wheel: {orig_filename} ({matched.get('size', 0):,} bytes)...")

        req_w = urllib.request.Request(wheel_url, headers={"User-Agent": "DockerBuild/1.0"})
        with urllib.request.urlopen(req_w, timeout=60) as resp_w:
            wheel_bytes = resp_w.read()

        print("[install_dlib] Repackaging wheel metadata to satisfy standard 'dlib' dependency...")
        in_zip = zipfile.ZipFile(io.BytesIO(wheel_bytes))
        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as out_zip:
            for item in in_zip.infolist():
                content = in_zip.read(item.filename)
                new_name = item.filename.replace("dlib_bin", "dlib")
                if item.filename.endswith("METADATA"):
                    content = re.sub(
                        r"(?m)^Name:\s*dlib-bin",
                        "Name: dlib",
                        content.decode("utf-8"),
                    ).encode("utf-8")
                elif item.filename.endswith("RECORD"):
                    lines = []
                    for line in content.decode("utf-8").splitlines():
                        parts = line.split(",")
                        parts[0] = parts[0].replace("dlib_bin", "dlib")
                        lines.append(",".join(parts))
                    content = "\n".join(lines).encode("utf-8")
                out_zip.writestr(new_name, content)

        tmp_dir = "/tmp" if os.name != "nt" else os.environ.get("TEMP", ".")
        os.makedirs(tmp_dir, exist_ok=True)
        wheel_path = os.path.join(tmp_dir, target_filename)
        with open(wheel_path, "wb") as f:
            f.write(out_buf.getvalue())

        print(f"[install_dlib] Installing {wheel_path} via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-deps", wheel_path])
        print(f"[install_dlib] SUCCESS: Installed dlib {DLIB_VERSION} from prebuilt binary wheel!")
        return True
    except Exception as exc:
        print(f"[install_dlib] Prebuilt installation could not be completed ({exc}). Falling back to compilation...")
        return False


def compile_dlib() -> None:
    """Fallback: compile dlib from source with optimal parallel flags."""
    cpu_count = os.cpu_count() or 1
    parallel_jobs = min(max(cpu_count, 1), 4)
    print(f"[install_dlib] Compiling dlib {DLIB_VERSION} from source with {parallel_jobs} parallel workers...")

    env = os.environ.copy()
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(parallel_jobs)
    env["DLIB_NO_GUI_SUPPORT"] = "1"
    env["DLIB_USE_CUDA"] = "0"

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        f"dlib=={DLIB_VERSION}",
        "--config-settings",
        f"cmake.define.CMAKE_BUILD_PARALLEL_LEVEL={parallel_jobs}",
        "--config-settings",
        "cmake.define.DLIB_NO_GUI_SUPPORT=ON",
        "--config-settings",
        "cmake.define.DLIB_USE_CUDA=OFF",
    ]
    subprocess.check_call(cmd, env=env)
    print(f"[install_dlib] SUCCESS: Compiled and installed dlib {DLIB_VERSION} from source!")


if __name__ == "__main__":
    success = install_prebuilt_dlib()
    if not success:
        compile_dlib()

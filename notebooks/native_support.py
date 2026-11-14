"""Locate an installed libpostal library, not a worker checkout, for uvx's native binding."""

from __future__ import annotations

import ctypes.util
import os
import shlex
import shutil
import subprocess
from pathlib import Path


class NativeEnvironment:
    """Set compiler search paths for an existing installation and restore them at cleanup."""

    def __init__(self):
        self.previous = {name: os.environ.get(name) for name in ("CFLAGS", "LDFLAGS")}
        prefix = os.environ.get("LIBPOSTAL_PREFIX")
        provider = "system installation"
        if not prefix and shutil.which("brew"):
            result = subprocess.run(["brew", "--prefix", "libpostal"], capture_output=True, text=True)
            if result.returncode == 0:
                prefix = result.stdout.strip()
                provider = "Homebrew installation"
        self.info = {"provider": provider, "model_data_version": "not discovered"}
        if prefix:
            root = Path(prefix).expanduser()
            if (
                not (root / "include/libpostal/libpostal.h").exists()
                and not (root / "include/libpostal.h").exists()
            ):
                raise RuntimeError("LIBPOSTAL_PREFIX must contain libpostal headers; see README native setup")
            for name, flag in [("CFLAGS", "-I"), ("LDFLAGS", "-L")]:
                directory = root / ("include" if name == "CFLAGS" else "lib")
                os.environ[name] = " ".join(
                    filter(None, [self.previous[name], flag + shlex.quote(str(directory))])
                )
            version_file = root / "share/libpostal/data_version"
            if version_file.exists():
                self.info["model_data_version"] = version_file.read_text().strip()
        elif not ctypes.util.find_library("postal"):
            raise RuntimeError(
                "Install native libpostal and its data models first; see README. uvx cannot provide them."
            )

    def close(self):
        """Restore only compiler variables owned by this notebook setup."""
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

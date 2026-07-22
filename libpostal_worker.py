# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.17.0",
#     "postal>=1.1",
# ]
# ///
"""Repo-root launch shim for the libpostal VGI worker.

The worker itself -- the ``postal`` catalog, the :class:`LibpostalWorker` class,
and :func:`main` -- lives in the wheel-importable :mod:`vgi_libpostal.worker`
module. This thin script re-exports them so the historical launch path keeps
working unchanged::

    uv run --no-sync libpostal_worker.py            # serve over stdio
    uv run --no-sync libpostal_worker.py --http     # serve over HTTP
    uv run --no-sync libpostal_worker.py --unix S   # serve over an AF_UNIX socket

The Makefile, ``ci/run-integration.sh`` and the pytest suite all invoke the
worker through this file; the Docker image instead installs the wheel and uses
the ``vgi-libpostal-worker`` console script / ``vgi-serve`` entry points, which
resolve to the very same :mod:`vgi_libpostal.worker` objects.

IMPORTANT -- launching this worker
----------------------------------
The ``postal`` (pypostal) binding is a C extension that must be **compiled
against libpostal**. A bare ``uv run libpostal_worker.py`` would rebuild it in a
fresh ephemeral environment on every launch (slow, and requires CFLAGS/LDFLAGS
pointing at the libpostal install each time). Run it from the already-built
project ``.venv`` instead -- ``uv run --no-sync libpostal_worker.py`` -- which
reuses the ``.venv`` where ``postal`` is already built. (The PEP 723 header
above is kept for documentation / portability; the tested path is the prebuilt
venv. See README / CLAUDE.md.)
"""

from __future__ import annotations

from vgi_libpostal.worker import LibpostalWorker, main

__all__ = ["LibpostalWorker", "main"]


if __name__ == "__main__":
    main()

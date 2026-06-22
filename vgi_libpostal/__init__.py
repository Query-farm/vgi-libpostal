"""International address parsing + normalization as a VGI worker.

Brings `libpostal <https://github.com/openvenues/libpostal>`_ -- the
statistical international address parser + normaliser -- into DuckDB/SQL via the
``postal`` (pypostal) binding. The implementation is split so each concern stays
focused:

- ``addresses`` -- pure parse / expand logic over the ``postal`` binding; no
  Arrow or VGI dependency, directly unit-testable.
- ``scalars``   -- per-row VGI scalar functions: ``parse_address`` (MAP),
  ``expand_address`` (VARCHAR[]), and the ``address_*`` component extractors.
- ``tables``    -- set-returning table functions: ``parse_address_components``
  (long format) and ``address_labels`` (discovery).

``libpostal_worker.py`` at the repo root assembles these into the ``postal``
catalog and runs the worker over stdio (or HTTP).

The libpostal C library and its ~2 GB of data models must be installed
separately (``brew install libpostal``); they are NOT pip-installable and NOT
bundled. See the README for the full install story.
"""

from __future__ import annotations

__version__ = "0.1.0"

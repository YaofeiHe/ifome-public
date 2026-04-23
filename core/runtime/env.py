"""Minimal local environment-file loader for development."""

from __future__ import annotations

import os
from pathlib import Path


def _candidate_root_dirs() -> tuple[Path, ...]:
    """Return possible project roots, preferring an explicit override."""

    candidates: list[Path] = []
    override = os.getenv("IFOME_PROJECT_ROOT")
    if override:
        candidates.append(Path(override).expanduser().resolve())
    candidates.append(Path(__file__).resolve().parents[2])
    return tuple(candidates)


def load_local_env() -> None:
    """
    Load repo-local `.env.local` or `.env` files into `os.environ`.

    The loader is intentionally tiny so the project does not need an extra
    dependency before the first local API run. Existing environment variables
    always win, which keeps shell-provided secrets authoritative.
    """

    for root_dir in _candidate_root_dirs():
        for file_name in (".env.local", ".env"):
            file_path = root_dir / file_name
            if not file_path.exists():
                continue

            for raw_line in file_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value

"""Tests for the unified CLI and public sync workflow."""

from __future__ import annotations

from argparse import Namespace
import os
from pathlib import Path
import threading

from core.cli import _run_install_boss, _run_sync_public, _watch_stdin_for_stop_command
from core.runtime.env import load_local_env


def test_load_local_env_reads_project_root_override(tmp_path: Path, monkeypatch) -> None:
    """Environment loading should honor IFOME_PROJECT_ROOT when provided."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".env.local").write_text("TEST_OVERRIDE_KEY=expected\n", encoding="utf-8")

    monkeypatch.delenv("TEST_OVERRIDE_KEY", raising=False)
    monkeypatch.setenv("IFOME_PROJECT_ROOT", str(project_root))

    load_local_env()

    assert "TEST_OVERRIDE_KEY" in os.environ
    assert os.environ["TEST_OVERRIDE_KEY"] == "expected"


def test_sync_public_copies_manifest_files_and_prunes_stale(tmp_path: Path) -> None:
    """The public sync command should only copy allowlisted files and prune stale ones."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (project_root / "apps" / "web").mkdir(parents=True)
    (project_root / "apps" / "api" / "src").mkdir(parents=True)
    (project_root / "apps" / "web" / "package.json").write_text("{}", encoding="utf-8")
    (project_root / "apps" / "api" / "src" / "main.py").write_text("app = object()\n", encoding="utf-8")
    (project_root / "README.md").write_text("public\n", encoding="utf-8")
    (project_root / "core").mkdir()
    (project_root / "core" / "logic.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project_root / ".env.local").write_text("SECRET=value\n", encoding="utf-8")
    (project_root / "apps" / "web" / "node_modules").mkdir(parents=True)
    (project_root / "apps" / "web" / "node_modules" / "dep.js").write_text(
        "console.log('private');\n",
        encoding="utf-8",
    )

    manifest_path = project_root / "public_sync_manifest.txt"
    manifest_path.write_text("README.md\ncore/**/*.py\napps/web/**/*.js\n", encoding="utf-8")

    target_dir = tmp_path / "public-repo"
    args = Namespace(
        target=str(target_dir),
        project_dir=str(project_root),
        manifest=str(manifest_path),
    )

    result = _run_sync_public(args)

    assert result == 0
    assert (target_dir / "README.md").read_text(encoding="utf-8") == "public\n"
    assert (target_dir / "core" / "logic.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (target_dir / ".env.local").exists()
    assert not (target_dir / "apps" / "web" / "node_modules" / "dep.js").exists()

    manifest_path.write_text("README.md\n", encoding="utf-8")
    _run_sync_public(args)

    assert (target_dir / "README.md").exists()
    assert not (target_dir / "core" / "logic.py").exists()


def test_watch_stdin_for_stop_command_triggers_shutdown(monkeypatch) -> None:
    """Typing `ifome stop` in the same terminal should trigger a shutdown request."""

    calls: list[tuple[str, int]] = []
    event = threading.Event()

    class FakeStdin:
        def isatty(self) -> bool:
            return True

        def __iter__(self):
            yield "ifome stop\n"

    monkeypatch.setattr("sys.stdin", FakeStdin())
    monkeypatch.setattr(
        "core.cli._request_runtime_shutdown",
        lambda host, api_port: (calls.append((host, api_port)), event.set()),
    )

    thread = _watch_stdin_for_stop_command("127.0.0.1", 8000)

    assert thread is not None
    assert event.wait(timeout=2)
    assert calls == [("127.0.0.1", 8000)]


def test_install_boss_runs_optional_dependency_setup(monkeypatch) -> None:
    """The Boss installer should install the optional CLI and browser runtime."""

    commands: list[list[str]] = []

    monkeypatch.setattr(
        "core.cli._run_checked_command",
        lambda command, cwd, env: commands.append(command),
    )
    monkeypatch.setattr("core.cli._resolve_executable_near_python", lambda name: "patchright")

    result = _run_install_boss(Namespace(skip_browser_install=False))

    assert result == 0
    assert commands[0][-3:] == ["pip", "install", "boss-agent-cli[mcp]"]
    assert commands[1] == ["patchright", "install", "chromium"]

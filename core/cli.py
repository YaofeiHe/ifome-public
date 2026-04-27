"""Unified CLI for local startup and public-repo sync workflows."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import base64
from importlib import resources
from pathlib import Path


PUBLIC_SYNC_STATE = ".ifome_public_sync_state.json"
SYNC_EXCLUDED_PARTS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "data",
    "dist",
    "build",
    "ifome_job_agent.egg-info",
    "node_modules",
}


def _project_root_from_cwd(start: Path | None = None) -> Path | None:
    """Find a source checkout root by walking upward from the current directory."""

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (
            (candidate / "pyproject.toml").exists()
            and (candidate / "apps" / "web" / "package.json").exists()
            and (candidate / "apps" / "api" / "src" / "main.py").exists()
        ):
            return candidate
    return None


def _default_runtime_root() -> Path:
    """Return the writable runtime root for bundled assets and logs."""

    return Path.home() / ".ifome"


def _iter_web_source_files(source_dir: Path) -> list[Path]:
    """List copyable frontend files, excluding build outputs and installed deps."""

    results: list[Path] = []
    for file_path in source_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in {"node_modules", ".next"} for part in file_path.parts):
            continue
        results.append(file_path)
    return sorted(results)


def _sync_tree(source_dir: Path, target_dir: Path) -> None:
    """Copy a source tree into a runtime directory and prune stale files."""

    target_dir.mkdir(parents=True, exist_ok=True)
    expected_rel_paths: set[str] = set()
    for file_path in _iter_web_source_files(source_dir):
        relative = file_path.relative_to(source_dir)
        expected_rel_paths.add(relative.as_posix())
        output_path = target_dir / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, output_path)

    for existing in sorted(target_dir.rglob("*"), reverse=True):
        if any(part in {"node_modules", ".next"} for part in existing.parts):
            continue
        if existing.is_dir():
            if existing != target_dir and not any(existing.iterdir()):
                existing.rmdir()
            continue
        relative = existing.relative_to(target_dir).as_posix()
        if relative in expected_rel_paths:
            continue
        existing.unlink()


def _resolve_web_dir(project_root: Path | None) -> tuple[Path, Path | None]:
    """
    Resolve the runnable frontend directory.

    Preference order:
    1. Source checkout `apps/web`
    2. Bundled package assets copied into `~/.ifome/runtime/web`
    """

    if project_root is not None:
        return project_root / "apps" / "web", project_root

    package_dir = Path(str(resources.files("apps.web")))
    runtime_root = _default_runtime_root() / "runtime" / "web"
    _sync_tree(package_dir, runtime_root)
    return runtime_root, None


def _stream_process_output(name: str, process: subprocess.Popen[str]) -> threading.Thread:
    """Continuously print one child process output with a readable prefix."""

    def _reader() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            print(f"[{name}] {line.rstrip()}", flush=True)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread


def _wait_until_ready(url: str, timeout_seconds: int = 60) -> bool:
    """Poll one local URL until it responds or a timeout is reached."""

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except Exception:
            time.sleep(1)
            continue
    return False


def _run_checked_command(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    """Run one setup command and stream its output to the current terminal."""

    subprocess.run(command, cwd=cwd, env=env, check=True)


def _ensure_web_dependencies(web_dir: Path, env: dict[str, str]) -> None:
    """Install frontend dependencies once if `node_modules` is missing."""

    if shutil.which("npm") is None:
        raise RuntimeError("未检测到 npm，请先安装 Node.js 和 npm。")
    if (web_dir / "node_modules").exists():
        return
    print("[setup] 首次启动前端，正在执行 npm install ...", flush=True)
    _run_checked_command(["npm", "install"], cwd=web_dir, env=env)


def _terminate_process(process: subprocess.Popen[str]) -> None:
    """Stop one child process gracefully, then force kill if needed."""

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_start(args: argparse.Namespace) -> int:
    """Start backend and frontend together, stream logs, and open the browser."""

    project_root = (
        Path(args.project_dir).expanduser().resolve()
        if args.project_dir
        else _project_root_from_cwd()
    )
    web_dir, detected_project_root = _resolve_web_dir(project_root)
    effective_project_root = project_root or detected_project_root

    if shutil.which("npm") is None:
        raise RuntimeError("未检测到 npm，请先安装 Node.js 和 npm。")

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault(
        "NEXT_PUBLIC_API_BASE_URL",
        f"http://{args.host}:{args.api_port}",
    )
    if effective_project_root is not None:
        env["IFOME_PROJECT_ROOT"] = str(effective_project_root)

    _ensure_web_dependencies(web_dir, env)

    backend_command = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.api.src.main:app",
        "--host",
        args.host,
        "--port",
        str(args.api_port),
    ]
    web_command = [
        "npm",
        "run",
        "dev",
        "--",
        "--hostname",
        args.host,
        "--port",
        str(args.web_port),
    ]

    backend_cwd = effective_project_root or Path.cwd()
    web_cwd = web_dir
    print(f"[ifome] API: http://{args.host}:{args.api_port}", flush=True)
    print(f"[ifome] Web: http://{args.host}:{args.web_port}", flush=True)
    if effective_project_root is not None:
        print(f"[ifome] Project root: {effective_project_root}", flush=True)
    print(f"[ifome] Web runtime dir: {web_dir}", flush=True)

    backend = subprocess.Popen(
        backend_command,
        cwd=backend_cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    web = subprocess.Popen(
        web_command,
        cwd=web_cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    _stream_process_output("api", backend)
    _stream_process_output("web", web)

    if args.open_browser:
        frontend_url = f"http://{args.host}:{args.web_port}"

        def _open_when_ready() -> None:
            if _wait_until_ready(frontend_url, timeout_seconds=90):
                webbrowser.open(frontend_url)

        threading.Thread(target=_open_when_ready, daemon=True).start()

    processes = [backend, web]

    def _shutdown(*_unused: object) -> None:
        for process in processes:
            _terminate_process(process)

    previous_sigint = signal.signal(signal.SIGINT, _shutdown)
    previous_sigterm = signal.signal(signal.SIGTERM, _shutdown)
    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is None:
                    continue
                for sibling in processes:
                    if sibling is not process:
                        _terminate_process(sibling)
                return code
            time.sleep(1)
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)


def _load_manifest_patterns(manifest_path: Path) -> list[str]:
    """Parse one allowlist manifest file into shell-style glob patterns."""

    patterns: list[str] = []
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _iter_manifest_files(project_root: Path, patterns: list[str]) -> list[Path]:
    """Resolve manifest patterns into a stable list of files under the project root."""

    matched: set[Path] = set()
    for pattern in patterns:
        for file_path in project_root.glob(pattern):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(project_root)
            if any(part in SYNC_EXCLUDED_PARTS for part in relative.parts):
                continue
            if file_path.suffix in {".pyc", ".sqlite3"}:
                continue
            matched.add(file_path)
    return sorted(matched)


def _run_sync_public(args: argparse.Namespace) -> int:
    """Copy only manifest-listed public files into another repository directory."""

    project_root = (
        Path(args.project_dir).expanduser().resolve()
        if args.project_dir
        else _project_root_from_cwd()
    )
    if project_root is None:
        raise RuntimeError("未找到项目根目录，请在 ifome 仓库内执行，或传入 --project-dir。")

    manifest_path = (
        Path(args.manifest).expanduser().resolve()
        if args.manifest
        else project_root / "public_sync_manifest.txt"
    )
    if not manifest_path.exists():
        raise RuntimeError(f"未找到同步清单：{manifest_path}")

    target_dir = Path(args.target).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    patterns = _load_manifest_patterns(manifest_path)
    source_files = _iter_manifest_files(project_root, patterns)
    synced_rel_paths = [file_path.relative_to(project_root).as_posix() for file_path in source_files]

    for source_file in source_files:
        relative = source_file.relative_to(project_root)
        output_path = target_dir / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, output_path)

    state_path = target_dir / PUBLIC_SYNC_STATE
    previous_files: set[str] = set()
    if state_path.exists():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            previous_files = set(payload.get("synced_files", []))
        except json.JSONDecodeError:
            previous_files = set()

    current_files = set(synced_rel_paths)
    stale_files = previous_files - current_files
    for relative in sorted(stale_files):
        stale_path = target_dir / relative
        if stale_path.exists():
            stale_path.unlink()

    for directory in sorted(target_dir.rglob("*"), reverse=True):
        if directory.is_dir() and directory != target_dir and not any(directory.iterdir()):
            directory.rmdir()

    state_path.write_text(
        json.dumps({"synced_files": synced_rel_paths}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[ifome] 已同步 {len(synced_rel_paths)} 个公共文件到 {target_dir}", flush=True)
    return 0


def _run_git_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one git command inside the exported public repository."""

    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"git command failed with exit {completed.returncode}: "
            f"{details or 'no git output'}"
        )
    return completed


def _resolve_github_token(args: argparse.Namespace) -> str | None:
    """Load one GitHub token from CLI args, env vars, or the default home file."""

    if os.getenv("GH_TOKEN"):
        return os.getenv("GH_TOKEN")
    file_candidates: list[Path] = []
    if getattr(args, "github_token_file", None):
        file_candidates.append(Path(args.github_token_file).expanduser())
    env_file = os.getenv("GITHUB_TOKEN_FILE")
    if env_file:
        file_candidates.append(Path(env_file).expanduser())
    file_candidates.append(Path.home() / "GITHUB_TOKEN")
    for candidate in file_candidates:
        if not candidate.exists():
            continue
        return candidate.read_text(encoding="utf-8").strip()
    return None


def _run_push_public(args: argparse.Namespace) -> int:
    """Sync the public tree, commit changes, and push them to the target repo."""

    sync_args = argparse.Namespace(
        target=args.target,
        project_dir=args.project_dir,
        manifest=args.manifest,
    )
    _run_sync_public(sync_args)

    target_dir = Path(args.target).expanduser().resolve()
    git_dir = target_dir / ".git"
    if not git_dir.exists():
        raise RuntimeError("目标目录还不是 Git 仓库，请先在公共仓库目录初始化并绑定远端。")

    state_file = target_dir / PUBLIC_SYNC_STATE
    if state_file.exists():
        state_file.unlink()

    _run_git_command(["git", "add", "-A"], cwd=target_dir)
    status = _run_git_command(["git", "status", "--short"], cwd=target_dir)
    if not status.stdout.strip():
        print("[ifome] 公共仓库没有需要提交的变更。", flush=True)
        return 0

    if args.commit_message:
        commit_message = args.commit_message
    else:
        commit_message = f"Sync public snapshot {time.strftime('%Y-%m-%d %H:%M:%S')}"

    _run_git_command(["git", "commit", "-m", commit_message], cwd=target_dir)
    token = _resolve_github_token(args)
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        push_result = _run_git_command(
            ["git", "-c", f"http.extraHeader=AUTHORIZATION: basic {basic}", "push"],
            cwd=target_dir,
        )
    else:
        push_result = _run_git_command(["git", "push"], cwd=target_dir)
    if push_result.stdout.strip():
        print(push_result.stdout.strip(), flush=True)
    if push_result.stderr.strip():
        print(push_result.stderr.strip(), flush=True)
    print(f"[ifome] 已提交并推送公共仓库：{target_dir}", flush=True)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the shared CLI parser."""

    parser = argparse.ArgumentParser(prog="ifome")
    subparsers = parser.add_subparsers(dest="subcommand")

    start_parser = subparsers.add_parser("start", help="启动前端和后端")
    start_parser.add_argument("--host", default="127.0.0.1")
    start_parser.add_argument("--api-port", type=int, default=8000)
    start_parser.add_argument("--web-port", type=int, default=3000)
    start_parser.add_argument("--project-dir", default=None)
    start_parser.add_argument(
        "--no-browser",
        dest="open_browser",
        action="store_false",
        help="启动后不自动打开浏览器",
    )
    start_parser.set_defaults(handler=_run_start, open_browser=True)

    sync_parser = subparsers.add_parser(
        "sync-public",
        help="按清单同步可公开文件到另一个目录",
    )
    sync_parser.add_argument("--target", required=True, help="目标 GitHub 仓库目录")
    sync_parser.add_argument("--project-dir", default=None)
    sync_parser.add_argument("--manifest", default=None)
    sync_parser.set_defaults(handler=_run_sync_public)

    push_parser = subparsers.add_parser(
        "push-public",
        help="按清单同步公共文件，并提交推送到目标 Git 仓库",
    )
    push_parser.add_argument("--target", required=True, help="目标 GitHub 仓库本地目录")
    push_parser.add_argument("--project-dir", default=None)
    push_parser.add_argument("--manifest", default=None)
    push_parser.add_argument("--commit-message", default=None)
    push_parser.add_argument(
        "--github-token-file",
        default=None,
        help="GitHub token 文件路径；未传时会依次尝试 GH_TOKEN、GITHUB_TOKEN_FILE、~/GITHUB_TOKEN",
    )
    push_parser.set_defaults(handler=_run_push_public)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint used by the console script."""

    parser = _build_parser()
    raw_args = argv if argv is not None else sys.argv[1:]
    if not raw_args or raw_args[0].startswith("-"):
        args = parser.parse_args(["start", *raw_args])
    else:
        args = parser.parse_args(raw_args)
        if args.subcommand is None:
            args = parser.parse_args(["start", *raw_args])
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"[ifome] {exc}", file=sys.stderr, flush=True)
        return 1

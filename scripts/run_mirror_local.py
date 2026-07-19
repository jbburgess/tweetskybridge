"""Local alternative to the `run-mirror.yml` GitHub Actions workflow.

Runs `main.main()` in-process and optionally commits and pushes
`id_map.json` when it changes. Supports a single one-shot run (the
default, suitable for invocation by OS cron / Task Scheduler) or a
long-running loop that re-executes on a fixed interval.

Examples:
    # One-shot, no git side effects (safe for experimentation)
    python scripts/run_mirror_local.py --once --no-commit --no-push -v

    # One-shot, commit + push (mirrors the GitHub Actions workflow)
    python scripts/run_mirror_local.py

    # Loop every 10 minutes, commit locally but don't push
    python scripts/run_mirror_local.py --loop --interval 600 --no-push
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = SCRIPT_DIR.parent
STATE_FILE = "id_map.json"
DEFAULT_INTERVAL = 600  # seconds
DEFAULT_COMMIT_MESSAGE = "chore: update id map"

log = logging.getLogger("run_mirror_local")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Local alternative to the run-mirror.yml workflow: runs main.py "
            "and optionally commits/pushes id_map.json updates."
        ),
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Run a single iteration and exit (default).",
    )
    mode.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously, sleeping --interval seconds between iterations.",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between iterations in --loop mode (default: {DEFAULT_INTERVAL}).",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Skip committing id_map.json changes.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip pushing commits to the remote.",
    )
    parser.add_argument(
        "--commit-author",
        default=None,
        metavar='"Name <email>"',
        help=(
            "Override the commit author for this invocation only "
            "(passed via `git -c`; does not modify your git config). "
            "Defaults to your local git config."
        ),
    )
    parser.add_argument(
        "--commit-message",
        default=DEFAULT_COMMIT_MESSAGE,
        help=f"Commit message (default: {DEFAULT_COMMIT_MESSAGE!r}).",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote to push to (default: origin).",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Git branch to push to (default: current branch).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Path to the repository root (default: parent of this script).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )

    return parser.parse_args(argv)


def parse_author(author: str) -> tuple[str, str]:
    """Parse a 'Name <email>' string into (name, email).

    Raises ValueError if the input does not contain a valid <email> segment.
    """
    author = author.strip()
    if "<" not in author or not author.endswith(">"):
        raise ValueError(
            f"--commit-author must be in the form 'Name <email>', got: {author!r}"
        )
    name, _, rest = author.partition("<")
    email = rest[:-1].strip()
    name = name.strip()
    if not name or not email:
        raise ValueError(
            f"--commit-author must include both a name and an email, got: {author!r}"
        )
    return name, email


def _git(args: list[str], *, cwd: Path, check: bool = True,
         capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def current_branch(repo_root: Path) -> str:
    result = _git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        capture_output=True,
    )
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        raise RuntimeError(
            "Could not determine current git branch (detached HEAD?). "
            "Pass --branch explicitly."
        )
    return branch


def state_file_changed(repo_root: Path) -> bool:
    """Return True if id_map.json has unstaged or staged changes vs HEAD."""
    # Unstaged changes
    unstaged = _git(
        ["diff", "--quiet", "--", STATE_FILE],
        cwd=repo_root,
        check=False,
    )
    if unstaged.returncode != 0:
        return True
    # Staged changes (in case a prior run added but didn't commit)
    staged = _git(
        ["diff", "--cached", "--quiet", "--", STATE_FILE],
        cwd=repo_root,
        check=False,
    )
    return staged.returncode != 0


def maybe_commit_and_push(args: argparse.Namespace) -> None:
    repo_root: Path = args.repo_root

    if args.no_commit:
        log.info("Commit disabled (--no-commit); skipping git operations.")
        return

    if not (repo_root / STATE_FILE).exists():
        log.warning("State file %s not found at %s; skipping commit.",
                    STATE_FILE, repo_root)
        return

    if not state_file_changed(repo_root):
        log.info("No changes to %s, skipping commit.", STATE_FILE)
        return

    git_prefix: list[str] = []
    if args.commit_author:
        name, email = parse_author(args.commit_author)
        git_prefix = ["-c", f"user.name={name}", "-c", f"user.email={email}"]

    _git(["add", "--", STATE_FILE], cwd=repo_root)
    _git(
        [*git_prefix, "commit", "-m", args.commit_message],
        cwd=repo_root,
    )
    log.info("Committed updated %s.", STATE_FILE)

    if args.no_push:
        log.info("Push disabled (--no-push); leaving commit local.")
        return

    branch = args.branch or current_branch(repo_root)
    _git(["push", args.remote, f"HEAD:{branch}"], cwd=repo_root)
    log.info("Pushed to %s %s.", args.remote, branch)


def run_once(args: argparse.Namespace) -> None:
    # Import lazily so --help works without requiring the project's deps.
    import main as mirror_main  # noqa: WPS433 (intentional late import)

    mirror_main.main()
    maybe_commit_and_push(args)


def run_loop(args: argparse.Namespace) -> None:
    log.info("Entering loop mode; interval=%ds. Press Ctrl-C to stop.",
             args.interval)
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            raise
        except Exception:
            log.exception("Iteration failed; will retry after interval.")
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            raise


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    # Validate --commit-author early so loop mode doesn't discover the error
    # only after the first iteration.
    if args.commit_author:
        try:
            parse_author(args.commit_author)
        except ValueError as exc:
            log.error("%s", exc)
            return 2

    # Make repo root importable so `import main` resolves to the project's
    # main.py rather than something on the default sys.path.
    repo_root: Path = args.repo_root.resolve()
    args.repo_root = repo_root
    sys.path.insert(0, str(repo_root))

    try:
        if args.loop:
            run_loop(args)
        else:
            run_once(args)
    except KeyboardInterrupt:
        log.info("Interrupted; exiting.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

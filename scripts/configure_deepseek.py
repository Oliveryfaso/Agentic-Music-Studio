#!/usr/bin/env python3
"""Store an opt-in backend Secret locally, without command-line or browser input."""

import argparse
import getpass
import os
import re
import stat
import sys
import tempfile
import warnings
from pathlib import Path


def secret_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    if not root.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must be absolute.")
    return root / "motif-forge" / "deepseek.env"


def check_directory(directory: Path, create: bool = False) -> None:
    if directory.is_symlink():
        raise ValueError("Private configuration directory must not be a symlink.")
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Configuration directory must belong to the user and have mode 0700.")


def check_target(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Secret target must be a regular local file, not a link.")
    if path.exists() and path.stat().st_uid != os.getuid():
        raise ValueError("Secret file must belong to the current user.")


def valid_key(key: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_.-]{16,256}", key) is not None


def save_key(path: Path, key: str) -> None:
    check_directory(path.parent, create=True)
    check_target(path)
    if not valid_key(key):
        raise ValueError(
            "Invalid Key format; use 16-256 letters, digits, dots, dashes or underscores."
        )
    fd, temporary = tempfile.mkstemp(prefix=".deepseek-secret-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) != 0o600:
                raise ValueError("This filesystem cannot store a private Secret.")
            stream.write("DEEPSEEK_API_KEY=" + key + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_file(path: Path) -> None:
    check_directory(path.parent)
    check_target(path)
    if not path.exists() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("Private Secret file is missing or not mode 0600; configure it again.")
    value = path.read_text(encoding="utf-8")
    prefix = "DEEPSEEK_API_KEY="
    if (
        not value.startswith(prefix)
        or not value.endswith("\n")
        or not valid_key(value[len(prefix) : -1])
    ):
        raise ValueError("Invalid Secret file; configure it again.")


def clear_key(path: Path) -> None:
    if not path.parent.exists() and not path.parent.is_symlink():
        return
    check_directory(path.parent)
    check_target(path)
    if path.exists():
        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--clear", action="store_true", help="Remove the local Secret file")
    group.add_argument(
        "--check", action="store_true", help="Check local file safety; no remote request"
    )
    group.add_argument("--path", action="store_true", help="Print only the private file path")
    args = parser.parse_args()
    try:
        target = secret_path()
        if args.path:
            print(target)
        elif args.clear:
            clear_key(target)
            print(
                "Local Key file removed. Restart the same Motif instance WITHOUT --enable-deepseek "
                "to remove the Key from running services. Revoke it at DeepSeek if needed."
            )
        elif args.check:
            validate_file(target)
        else:
            if not sys.stdin.isatty():
                raise ValueError("Run in an interactive terminal; Key input must be hidden.")
            check_target(target)
            check_directory(target.parent, create=True)
            if target.exists() and input("Replace existing local Key? [y/N] ").lower() != "y":
                return 0
            print(
                "External generation may cost money and send music context to DeepSeek. "
                "This command stores a local Secret only; it sends nothing."
            )
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                key = getpass.getpass("DeepSeek API Key (hidden): ")
            save_key(target, key)
            print(
                "Saved locally, NOT active yet. Restart the same Motif instance with "
                "--enable-deepseek, then open Settings. No connection check or generation was sent."
            )
    except (ValueError, OSError, UnicodeError, getpass.GetPassWarning):
        print(
            "Configuration failed. Check the Key format, local file ownership/0600 permissions "
            "and that the target is not a symlink. No Key is printed.",
            file=sys.stderr,
        )
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Configuration cancelled; no new Key was saved.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

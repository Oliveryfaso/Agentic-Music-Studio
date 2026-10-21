"""Lock a launcher-owned FD; the parent shell keeps the kernel lock alive."""

from __future__ import annotations

import fcntl
import os
import stat
import sys


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"acquire", "release"}:
        print("RUNTIME_LOCK_ARGUMENTS_INVALID", file=sys.stderr)
        return 64
    try:
        held = os.fstat(9)
        named = os.stat(sys.argv[2], follow_symlinks=False)
        if (
            (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)
            or not stat.S_ISREG(named.st_mode)
            or named.st_uid != os.getuid()
            or stat.S_IMODE(named.st_mode) != 0o600
            or named.st_nlink != 1
        ):
            raise ValueError("invalid lock identity")
        operation = (
            fcntl.LOCK_EX | fcntl.LOCK_NB if sys.argv[1] == "acquire" else fcntl.LOCK_UN
        )
        fcntl.flock(9, operation)
    except BlockingIOError:
        print(
            "RUNTIME_OPERATION_BUSY: launch or stop in progress; retry when it finishes.",
            file=sys.stderr,
        )
        return 75
    except (OSError, ValueError):
        print("RUNTIME_LOCK_INVALID: no resources were changed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

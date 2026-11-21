"""実行部。外部コマンドと OS への問い合わせはここだけで行う。"""

import os
import subprocess
from datetime import datetime, timezone

from tojimari import packages

RPM_TIMEOUT = 30
DNF_TIMEOUT = 60


class CommandError(Exception):
    """外部コマンドを実行できなかった、または失敗した。"""

    def __init__(self, kind, returncode=None, stderr_tail=""):
        super().__init__(kind)
        self.kind = kind  # "not_found" | "timeout" | "exit_status" | "os_error"
        self.returncode = returncode  # kind が "exit_status" のときだけ入る
        self.stderr_tail = stderr_tail  # 標準エラー出力の末尾（最大 5 行）


def _tail(data) -> str:
    if not data:
        return ""
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    lines = data.splitlines()
    return "\n".join(lines[-5:])


def run_command(argv: list[str], timeout: float) -> str:
    """argv を実行し、標準出力を文字列で返す。終了コードが 0 でなければ CommandError。"""
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise CommandError("not_found") from None
    except subprocess.TimeoutExpired as exc:
        raise CommandError("timeout", stderr_tail=_tail(exc.stderr)) from None
    except OSError:
        raise CommandError("os_error") from None
    if proc.returncode != 0:
        raise CommandError(
            "exit_status", returncode=proc.returncode, stderr_tail=_tail(proc.stderr)
        )
    return proc.stdout.decode("utf-8", errors="replace")


class System:
    """実機への問い合わせをまとめたもの。テストではこのクラスごと差し替える。"""

    def rpm_list(self) -> str:
        return run_command(packages.RPM_LIST_ARGV, RPM_TIMEOUT)

    def dnf_from_repo(self, names) -> str:
        return run_command(packages.dnf_from_repo_argv(list(names)), DNF_TIMEOUT)

    def running_kernel(self):
        try:
            return os.uname().release
        except (OSError, AttributeError):
            return None

    def is_root(self) -> bool:
        return os.geteuid() == 0

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

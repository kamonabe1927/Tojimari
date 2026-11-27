"""実行部。外部コマンドと OS への問い合わせはここだけで行う。"""

import os
import sqlite3
import subprocess
import urllib.parse
from datetime import datetime, timezone
from typing import NamedTuple

from tojimari import history, packages, processes

RPM_TIMEOUT = 30
DNF_TIMEOUT = 60


class CommandError(Exception):
    """外部コマンドを実行できなかった、または失敗した。"""

    def __init__(self, kind, returncode=None, stderr_tail="", timeout=None):
        super().__init__(kind)
        self.kind = kind  # "not_found" | "timeout" | "exit_status" | "os_error"
        self.returncode = returncode  # kind が "exit_status" のときだけ入る
        self.stderr_tail = stderr_tail  # 標準エラー出力の末尾（最大 5 行）
        self.timeout = timeout  # kind が "timeout" のときだけ入る（秒）


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
        raise CommandError(
            "timeout", stderr_tail=_tail(exc.stderr), timeout=timeout
        ) from None
    except OSError:
        raise CommandError("os_error") from None
    if proc.returncode != 0:
        raise CommandError(
            "exit_status", returncode=proc.returncode, stderr_tail=_tail(proc.stderr)
        )
    return proc.stdout.decode("utf-8", errors="replace")


_SQLITE_MAGIC = b"SQLite format 3\x00"
_URI_WAL = "?mode=ro"
_URI_IMMUTABLE = "?mode=ro&immutable=1"


class _DbSnapshot(NamedTuple):
    main: tuple  # (大きさ, 更新時刻 ns, 先頭 100 バイト)
    journal: tuple | None  # 無ければ None。あれば (大きさ, 更新時刻 ns, b"")
    wal: tuple | None  # 無ければ None。あれば (大きさ, 更新時刻 ns, 先頭 32 バイト)
    shm: bool  # あるかどうか


def _aux_state(path: str, head_len: int) -> tuple | None:
    """補助ファイル 1 つの様子。無ければ None。読むだけ。"""
    try:
        st = os.stat(path)
        head = b""
        with open(path, "rb") as f:
            if head_len:
                head = f.read(head_len)
    except FileNotFoundError:
        return None
    except PermissionError:
        raise history.HistoryError("permission") from None
    except OSError:
        raise history.HistoryError("os_error") from None
    return (st.st_size, st.st_mtime_ns, head)


def _db_snapshot(path: str) -> _DbSnapshot:
    """データベースの様子（本体と補助ファイル）。読むだけ。"""
    try:
        st = os.stat(path)
        with open(path, "rb") as f:
            head = f.read(100)
    except FileNotFoundError:
        raise history.HistoryError("not_found") from None
    except PermissionError:
        raise history.HistoryError("permission") from None
    except OSError:
        raise history.HistoryError("os_error") from None
    return _DbSnapshot(
        (st.st_size, st.st_mtime_ns, head),
        _aux_state(path + "-journal", 0),
        _aux_state(path + "-wal", 32),
        _aux_state(path + "-shm", 0) is not None,
    )


def _is_wal(head: bytes) -> bool:
    return len(head) >= 20 and head[:16] == _SQLITE_MAGIC and head[19] == 2


def read_history_db(path: str, query):
    """path のデータベースを読み取り専用で開き、query(execute) の結果を返す。
    WAL 方式なら mode=ro（-wal の記録も読む。-shm と -wal が無いときは開かない）、
    そうでなければ mode=ro&immutable=1 で開く。
    開けない、確かめに通らない、問い合わせが失敗したときは history.HistoryError。"""
    before = _db_snapshot(path)
    if before.journal is not None and before.journal[0] > 0:
        raise history.HistoryError("busy")
    if _is_wal(before.main[2]):
        if not before.shm:
            raise history.HistoryError("no_shm")
        if before.wal is None:
            raise history.HistoryError("no_wal")
        suffix = _URI_WAL
    else:
        if before.wal is not None and before.wal[0] > 0:
            raise history.HistoryError("busy")
        suffix = _URI_IMMUTABLE

    uri = "file:" + urllib.parse.quote(path) + suffix
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=0)
        result = query(lambda sql: conn.execute(sql).fetchall())
    except sqlite3.Error:
        raise history.HistoryError("query_failed") from None
    finally:
        if conn is not None:
            conn.close()

    if _db_snapshot(path) != before:
        raise history.HistoryError("changed")
    return result


def _os_error_kind(exc: OSError) -> str:
    if isinstance(exc, (FileNotFoundError, ProcessLookupError)):
        return "gone"
    if isinstance(exc, PermissionError):
        return "permission"
    return "other"


def _read_text(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def scan_processes(proc_dir="/proc", root_dir="/") -> processes.ProcessScan:
    """proc_dir を 1 回見回し、生の値を返す。読むだけ（cmdline と environ は読まない）。
    見回せなければ processes.ScanError。"""
    try:
        own = os.stat(root_dir)
        names = os.listdir(proc_dir)
    except OSError:
        raise processes.ScanError("見回せない") from None
    infos = []
    for name in sorted((n for n in names if n.isascii() and n.isdigit()), key=int):
        base = os.path.join(proc_dir, name)
        stat_text = _read_text(os.path.join(base, "stat"))
        exe = exe_error = None
        try:
            exe = os.readlink(os.path.join(base, "exe"))
        except OSError as exc:
            exe_error = _os_error_kind(exc)
        root = root_error = None
        try:
            st = os.stat(os.path.join(base, "root"))
            root = (st.st_dev, st.st_ino)
        except OSError as exc:
            root_error = _os_error_kind(exc)
        cgroup = _read_text(os.path.join(base, "cgroup"))
        infos.append(
            processes.ProcessInfo(
                int(name), stat_text, exe, exe_error, root, root_error, cgroup
            )
        )
    return processes.ProcessScan(os.getpid(), (own.st_dev, own.st_ino), infos)


class System:
    """実機への問い合わせをまとめたもの。テストではこのクラスごと差し替える。"""

    def rpm_list(self) -> str:
        return run_command(packages.RPM_LIST_ARGV, RPM_TIMEOUT)

    def rpm_files(self) -> str:
        return run_command(packages.RPM_FILES_ARGV, RPM_TIMEOUT)

    def process_scan(self) -> processes.ProcessScan:
        return scan_processes()

    def dnf_from_repo(self, names) -> str:
        return run_command(packages.dnf_from_repo_argv(list(names)), DNF_TIMEOUT)

    def dnf_userinstalled(self) -> str:
        return run_command(packages.DNF_USERINSTALLED_ARGV, DNF_TIMEOUT)

    def history_first_names(self) -> frozenset[str]:
        return read_history_db(history.DB_PATH, history.query_first_transaction)

    def dnf_security_upgrades(self, severity=None) -> str:
        return run_command(packages.dnf_security_upgrades_argv(severity), DNF_TIMEOUT)

    def history_last_upgrade(self):
        return read_history_db(history.DB_PATH, history.query_last_upgrade)

    def running_kernel(self):
        try:
            return os.uname().release
        except (OSError, AttributeError):
            return None

    def is_root(self) -> bool:
        return os.geteuid() == 0

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

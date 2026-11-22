"""解釈部。/proc の見回しの生の値から、印のもとになるプロセスを決める。
何も実行せず、ファイルも読まない。"""

from dataclasses import dataclass

from tojimari import packages

PF_KTHREAD = 0x00200000
_DELETED_SUFFIX = " (deleted)"


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    stat: str | None  # /proc/<pid>/stat の中身。読めなければ None
    exe: str | None  # os.readlink("/proc/<pid>/exe") の値
    exe_error: str | None  # None | "gone" | "permission" | "other"
    root: tuple[int, int] | None  # os.stat("/proc/<pid>/root") の (st_dev, st_ino)
    root_error: str | None  # None | "gone" | "permission" | "other"
    cgroup: str | None  # /proc/<pid>/cgroup の中身。読めなければ None


@dataclass(frozen=True)
class ProcessScan:
    self_pid: int
    own_root: tuple[int, int]
    processes: list[ProcessInfo]


class ScanError(Exception):
    """/proc を見回せなかった。"""


def parse_stat(text: str | None) -> tuple[str, int, int] | None:
    """(状態, ppid, flags)。形が合わなければ None。
    プロセス名は括弧で囲まれ、空白や括弧を含みうるので、最後の ')' より後ろを読む。"""
    if not text:
        return None
    end = text.rfind(")")
    if end < 0 or "(" not in text[:end]:
        return None
    rest = text[end + 1 :].split()
    if len(rest) < 7:
        return None
    state = rest[0]
    try:
        ppid = int(rest[1])
        flags = int(rest[6])
    except ValueError:
        return None
    return (state, ppid, flags)


def is_system_service(cgroup_text: str | None) -> bool:
    if not cgroup_text:
        return False
    path = None
    for line in cgroup_text.split("\n"):
        if line.startswith("0::"):
            path = line[3:]
            break
    if path is None:
        return False
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] == "user.slice":
        return False
    if any(p.startswith("user@") and p.endswith(".service") for p in parts):
        return False
    return any(p.endswith(".service") for p in parts)


def strip_deleted(path: str) -> str:
    if path.endswith(_DELETED_SUFFIX):
        return path[: -len(_DELETED_SUFFIX)]
    return path


def _descendants_of(self_pid: int, ppids: dict[int, int]) -> set[int]:
    result = set()
    limit = len(ppids)
    for pid in ppids:
        cur = pid
        for _ in range(limit + 1):
            if cur == self_pid:
                result.add(pid)
                break
            nxt = ppids.get(cur)
            if nxt is None or nxt == 0:
                break
            cur = nxt
    return result


def classify(scan: ProcessScan) -> tuple[list[tuple[str, bool]], int]:
    """(候補の (パス, サービスか) の並び, unreadable の数)。"""
    parsed = {p.pid: parse_stat(p.stat) for p in scan.processes}
    ppids = {pid: st[1] for pid, st in parsed.items() if st is not None}
    excluded = _descendants_of(scan.self_pid, ppids)
    excluded.add(scan.self_pid)

    candidates: list[tuple[str, bool]] = []
    unreadable = 0
    for p in scan.processes:
        if p.pid in excluded:
            continue
        st = parsed[p.pid]
        if st is not None:
            state, _ppid, flags = st
            if flags & PF_KTHREAD or state in ("Z", "X"):
                continue
        if p.exe_error == "gone":
            continue
        if p.exe_error is not None or p.exe is None:
            unreadable += 1
            continue
        if p.root_error == "gone":
            continue
        if p.root_error is not None or p.root is None:
            unreadable += 1
            continue
        if p.root != scan.own_root:
            continue
        candidates.append((strip_deleted(p.exe), is_system_service(p.cgroup)))
    return candidates, unreadable


def build_marks(candidates, file_map) -> dict[tuple, bool]:
    """版のキー → サービスか。キーがあれば running は真。"""
    marks: dict[tuple, bool] = {}
    for path, service in candidates:
        for key in file_map.get(path, ()):
            marks[key] = marks.get(key, False) or service
    return marks


def apply_marks(focus: dict, user_installed: dict, marks: dict | None) -> None:
    entries = []
    for pkg in focus.get("packages", []):
        entries.extend(pkg.get("installed", []))
    entries.extend(user_installed.get("packages", []))
    for v in entries:
        if marks is None:
            v["running"] = None
            v["systemd_service"] = None
            continue
        key = packages.version_key(
            v["name"], v["epoch"], v["version"], v["release"], v["arch"]
        )
        v["running"] = key in marks
        v["systemd_service"] = marks.get(key, False)

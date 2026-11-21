"""重点リストの定義と、レポート（JSON と同じ形の dict）の組み立て。"""

from datetime import timezone

from tojimari import notices, packages
from tojimari.runner import CommandError

FOCUS_PACKAGES = [
    ("kernel", "土台。動いている版と入っている版の両方を表示する"),
    ("openssh-server", "外から届く入口"),
    ("openssh", "外から届く入口"),
    ("openssl-libs", "多くのソフトが使う暗号ライブラリ（openssl コマンドではなくライブラリ本体）"),
    ("glibc", "ほぼすべてのソフトが使う土台"),
    ("sudo", "権限昇格につながる"),
    ("systemd", "土台。権限の強い処理を担う"),
    ("polkit", "権限昇格につながる"),
]

_NO_MATCH_REASON = "dnf の出力に該当する版が無かった"


class CheckError(Exception):
    """出力そのものができない（終了コード 1 にする）。"""


def _command_reason(tool: str, timeout: int, err: CommandError) -> str:
    if err.kind == "not_found":
        return f"{tool} コマンドが見つからない"
    if err.kind == "timeout":
        return f"{tool} が {timeout} 秒で終わらなかった"
    if err.kind == "exit_status":
        return f"{tool} が終了コード {err.returncode} で終わった"
    return f"{tool} を実行できなかった"


def _rpm_failure_message(err: CommandError) -> str:
    if err.kind == "not_found":
        msg = "rpm コマンドが見つかりません"
    elif err.kind == "timeout":
        msg = "rpm の問い合わせが 30 秒で終わりませんでした"
    elif err.kind == "exit_status":
        msg = f"rpm の問い合わせが終了コード {err.returncode} で失敗しました"
    else:
        msg = "rpm を実行できませんでした"
    if err.stderr_tail:
        msg += "\n" + err.stderr_tail
    return msg


def _iso_utc(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_focus_packages(installed, from_repo_map, running_kernel) -> dict:
    """from_repo_map が None のときは、dnf から取れなかったものとして扱う。"""
    matched_any = False
    entries = []
    for name, reason in FOCUS_PACKAGES:
        versions = sorted(
            (p for p in installed if p.name == name),
            key=lambda p: (p.version, p.release, p.arch),
        )
        items = []
        for pkg in versions:
            key = packages.version_key(
                pkg.name, pkg.epoch, pkg.version, pkg.release, pkg.arch
            )
            from_repo = None
            if from_repo_map is not None and key in from_repo_map:
                matched_any = True
                from_repo = from_repo_map[key]
            item = packages.version_entry(pkg, from_repo)
            if name == "kernel":
                item["is_running_kernel"] = (
                    running_kernel is not None
                    and f"{pkg.version}-{pkg.release}.{pkg.arch}" == running_kernel
                )
            items.append(item)
        entries.append(
            {
                "name": name,
                "reason": reason,
                "status": "installed" if items else "not_installed",
                "installed": items,
            }
        )
    any_installed = any(e["installed"] for e in entries)
    if from_repo_map is None:
        available = False
    elif any_installed and not matched_any:
        available = False
    else:
        available = True
    return {"packages": entries, "from_repo_available": available}


def collect(system) -> dict:
    try:
        installed = packages.parse_rpm_list(system.rpm_list())
    except CommandError as err:
        raise CheckError(_rpm_failure_message(err)) from None
    except packages.ParseError:
        raise CheckError("rpm の出力を読み取れませんでした") from None

    names = [name for name, _ in FOCUS_PACKAGES]
    from_repo_map = None
    problem = None
    try:
        from_repo_map = packages.parse_dnf_from_repo(system.dnf_from_repo(names))
    except CommandError as err:
        problem = _command_reason("dnf", 60, err)

    running_kernel = system.running_kernel()
    is_root = system.is_root()
    now = system.now()

    focus = build_focus_packages(installed, from_repo_map, running_kernel)
    if problem is None and not focus["from_repo_available"]:
        problem = _NO_MATCH_REASON

    kernel_entries = next(
        e["installed"] for e in focus["packages"] if e["name"] == "kernel"
    )
    running_found = any(v["is_running_kernel"] for v in kernel_entries)

    return {
        "format": "tojimari-check",
        "schema_version": 1,
        "generated_at": _iso_utc(now),
        "run": {"is_root": is_root},
        "system": {"running_kernel": running_kernel},
        "checks": {"focus_packages": focus},
        "notices": notices.build_notices(is_root, problem, running_found),
    }

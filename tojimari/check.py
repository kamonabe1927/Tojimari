"""重点リストの定義と、レポート（JSON と同じ形の dict）の組み立て。"""

from datetime import timezone

from tojimari import history, notices, packages
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
_NO_ROWS_REASON = "dnf の出力に読み取れる行が無かった"
_NO_RPM_MATCH_REASON = "dnf の出力が rpm の記録と突き合わなかった"


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


def os_names_from_repo(userinstalled: dict) -> frozenset[str]:
    """代わりの判定。from_repo が "anaconda" の行を 1 つでも持つ名前の集まり。"""
    return frozenset(k[0] for k, repo in userinstalled.items() if repo == "anaconda")


def build_user_installed(installed, userinstalled, os_names, method) -> dict:
    """userinstalled が None なら unavailable。"""
    if userinstalled is None:
        return {"status": "unavailable", "method": None, "packages": []}
    names = {k[0] for k in userinstalled} - set(os_names)
    entries = []
    for pkg in installed:
        if pkg.name not in names:
            continue
        key = packages.version_key(
            pkg.name, pkg.epoch, pkg.version, pkg.release, pkg.arch
        )
        entries.append(packages.version_entry(pkg, userinstalled.get(key)))
    entries.sort(key=lambda e: (e["name"], e["version"], e["release"], e["arch"]))
    return {"status": "ok", "method": method, "packages": entries}


def _collect_user_installed(system, installed):
    """(user_installed, 履歴の問題, 一覧の問題) を返す。"""
    userinstalled = None
    list_problem = None
    try:
        userinstalled = packages.parse_dnf_from_repo(system.dnf_userinstalled())
    except CommandError as err:
        list_problem = _command_reason("dnf", 60, err)
    if userinstalled is not None:
        if not userinstalled:
            userinstalled = None
            list_problem = _NO_ROWS_REASON
        elif not ({k[0] for k in userinstalled} & {p.name for p in installed}):
            userinstalled = None
            list_problem = _NO_RPM_MATCH_REASON
    if userinstalled is None:
        return build_user_installed(installed, None, frozenset(), None), None, list_problem

    try:
        os_names = system.history_first_names()
        method = "history"
        history_problem = None
    except history.HistoryError as err:
        os_names = os_names_from_repo(userinstalled)
        method = "from_repo_fallback"
        history_problem = history.reason_text(err.kind)
    return (
        build_user_installed(installed, userinstalled, os_names, method),
        history_problem,
        None,
    )


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

    user_installed, history_problem, list_problem = _collect_user_installed(
        system, installed
    )

    return {
        "format": "tojimari-check",
        "schema_version": 1,
        "generated_at": _iso_utc(now),
        "run": {"is_root": is_root},
        "system": {"running_kernel": running_kernel},
        "checks": {"focus_packages": focus, "user_installed": user_installed},
        "notices": notices.build_notices(
            is_root, problem, running_found, history_problem, list_problem
        ),
    }

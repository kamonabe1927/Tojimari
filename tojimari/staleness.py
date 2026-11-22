"""古さ（checks.staleness）の組み立て。セキュリティ更新、再起動待ち、最後に更新した日。"""

from datetime import datetime, timezone

from tojimari import history, notices, packages, rpmver
from tojimari.runner import CommandError

SEVERITY_KEYS = ("critical", "important", "moderate", "low", "unspecified")

_DNF_TIMEOUT = 60
_DNF_PARSE_REASON = "dnf の出力を読み取れなかった"
_NO_RUNNING_KERNEL_REASON = "動いているカーネルを取得できなかった"
_NO_SAME_ARCH_REASON = (
    "rpm の記録に、動いているカーネルと同じアーキテクチャの kernel が無かった"
)
_RUNNING_NOT_FOUND_REASON = (
    "動いているカーネルが、rpm の記録にある kernel の版の中に見つからなかった"
)


def build_security_updates(security_names, severity_names) -> dict:
    """security_names が None なら unavailable。
    severity_names は {"critical": 名前の集まり, ...}（4 つ）。"""
    if security_names is None:
        return {
            "status": "unavailable",
            "total": None,
            "by_severity": None,
            "packages": [],
        }
    assigned = {}
    for key in SEVERITY_KEYS[:4]:
        for name in severity_names.get(key, ()):
            if name in security_names and name not in assigned:
                assigned[name] = key
    for name in security_names:
        assigned.setdefault(name, "unspecified")
    order = {key: i for i, key in enumerate(SEVERITY_KEYS)}
    entries = sorted(
        ({"name": n, "severity": s} for n, s in assigned.items()),
        key=lambda e: (order[e["severity"]], e["name"]),
    )
    by_severity = {key: 0 for key in SEVERITY_KEYS}
    for e in entries:
        by_severity[e["severity"]] += 1
    return {
        "status": "ok",
        "total": len(entries),
        "by_severity": by_severity,
        "packages": entries,
    }


def _kernel_string(pkg) -> str:
    return f"{pkg.version}-{pkg.release}.{pkg.arch}"


def build_reboot(installed, running_kernel) -> tuple[dict, str | None]:
    """(reboot, unknown のときの理由)。"""

    def unknown(latest, reason):
        return (
            {
                "status": "unknown",
                "running_kernel": running_kernel,
                "latest_kernel": latest,
            },
            reason,
        )

    if running_kernel is None:
        return unknown(None, _NO_RUNNING_KERNEL_REASON)
    same_arch = [
        p
        for p in installed
        if p.name == "kernel" and running_kernel.endswith("." + p.arch)
    ]
    if not same_arch:
        return unknown(None, _NO_SAME_ARCH_REASON)
    latest = same_arch[0]
    for pkg in same_arch[1:]:
        if rpmver.compare_evr(pkg, latest) > 0:
            latest = pkg
    latest_kernel = _kernel_string(latest)
    running = [p for p in same_arch if _kernel_string(p) == running_kernel]
    if not running:
        return unknown(latest_kernel, _RUNNING_NOT_FOUND_REASON)
    pending = rpmver.compare_evr(latest, running[0]) > 0
    return (
        {
            "status": "pending" if pending else "not_pending",
            "running_kernel": running_kernel,
            "latest_kernel": latest_kernel,
        },
        None,
    )


def build_last_update(timestamp, now) -> dict:
    """timestamp が None なら none。"""
    if timestamp is None:
        return {"status": "none", "at": None, "days_ago": None}
    at = datetime.fromtimestamp(timestamp, timezone.utc)
    days = max(0, (now.astimezone(timezone.utc) - at).days)
    return {
        "status": "ok",
        "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days_ago": days,
    }


def _collect_security(system):
    """(security_updates, 理由)。"""
    try:
        names = packages.parse_dnf_names(system.dnf_security_upgrades(None))
        by_severity = {}
        if names:
            for severity in packages.SEVERITIES:
                by_severity[severity.lower()] = packages.parse_dnf_names(
                    system.dnf_security_upgrades(severity)
                )
    except CommandError as err:
        return build_security_updates(None, {}), notices.command_reason(
            "dnf", _DNF_TIMEOUT, err
        )
    except packages.ParseError:
        return build_security_updates(None, {}), _DNF_PARSE_REASON
    return build_security_updates(names, by_severity), None


def _collect_last_update(system, now):
    try:
        timestamp = system.history_last_upgrade()
    except history.HistoryError as err:
        return (
            {"status": "unavailable", "at": None, "days_ago": None},
            history.reason_text(err.kind),
        )
    return build_last_update(timestamp, now), None


def collect(system, installed, running_kernel, now) -> tuple[dict, dict]:
    """(checks.staleness, 理由の dict)。理由のキーは security_updates、reboot、
    last_update。取れたものの値は None。3 つは別々に取る。"""
    security, security_problem = _collect_security(system)
    reboot, reboot_problem = build_reboot(installed, running_kernel)
    last_update, last_update_problem = _collect_last_update(system, now)
    return (
        {
            "security_updates": security,
            "reboot": reboot,
            "last_update": last_update,
        },
        {
            "security_updates": security_problem,
            "reboot": reboot_problem,
            "last_update": last_update_problem,
        },
    )

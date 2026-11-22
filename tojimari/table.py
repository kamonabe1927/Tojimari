"""レポートから人が読む表を作る。レポートだけを入力にする。"""

import unicodedata
from datetime import datetime

from tojimari import display

STATUS_LABEL = {"installed": "入っている", "not_installed": "入っていない"}
HEADERS = ["パッケージ", "状態", "バージョン", "アーキ", "入れた元"]
USER_INSTALLED_HEADERS = ["パッケージ", "バージョン", "アーキ", "入れた元"]
RUNNING_MARK = "<- 動いている"
PROCESS_MARK = "<- 今動いている"
SERVICE_MARK = "<- 今動いている（systemd のサービス）"


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F", "A") else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * (width - display_width(text))


def _format_time(generated_at: str) -> str:
    dt = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _mark_text(version: dict, kernel: bool = False) -> str:
    """版の要素に付ける印の文字列（無ければ空）。kernel の印を先にする。"""
    marks = []
    if kernel and version.get("is_running_kernel"):
        marks.append(RUNNING_MARK)
    if version.get("systemd_service"):
        marks.append(SERVICE_MARK)
    elif version.get("running"):
        marks.append(PROCESS_MARK)
    return "  ".join(marks)


def _focus_rows(focus: dict) -> list[tuple[list[str], str]]:
    """(5 列の文字列, 行の終わりに付ける印の文字列) の並び。"""
    rows = []
    for pkg in focus.get("packages", []):
        label = STATUS_LABEL.get(pkg["status"], pkg["status"])
        versions = pkg.get("installed", [])
        if not versions:
            rows.append(([pkg["name"], label, "-", "", ""], ""))
            continue
        for i, v in enumerate(versions):
            rows.append(
                (
                    [
                        pkg["name"] if i == 0 else "",
                        label if i == 0 else "",
                        v["evr"],
                        v["arch"],
                        v["from_repo"] if v.get("from_repo") is not None else "-",
                    ],
                    _mark_text(v, kernel=True),
                )
            )
    return rows


def _format_rows(headers: list[str], rows: list[list[str]]) -> list[str]:
    """見出しと行を、表示幅でそろえた行にする（見出しの行が先頭）。"""
    widths = [display_width(h) for h in headers]
    for cells in rows:
        for i, c in enumerate(cells):
            widths[i] = max(widths[i], display_width(c))
    out = ["  ".join(_pad(h, w) for h, w in zip(headers, widths)).rstrip()]
    for cells in rows:
        out.append("  ".join(_pad(c, w) for c, w in zip(cells, widths)).rstrip())
    return out


def _user_installed_lines(ui: dict) -> list[str]:
    title = "[後から入れたもの]"
    if ui.get("status") != "ok":
        return [title, "確認できませんでした"]
    pkgs = ui.get("packages", [])
    count = len({p["name"] for p in pkgs})
    method = ui.get("method")
    if method == "history":
        title += f"  dnf 履歴の 1 番の名前を除いた {count} 件"
    elif method == "from_repo_fallback":
        title += f"  入れた元が anaconda のものを除いた {count} 件（代わりの判定）"
    else:
        title += f"  {count} 件"
    if not pkgs:
        return [title, "該当なし"]
    rows = []
    marks = []
    prev = None
    for p in pkgs:
        marks.append(_mark_text(p))
        rows.append(
            [
                p["name"] if p["name"] != prev else "",
                p["evr"],
                p["arch"],
                p.get("from_repo") if p.get("from_repo") is not None else "-",
            ]
        )
        prev = p["name"]
    formatted = _format_rows(USER_INSTALLED_HEADERS, rows)
    lines = [formatted[0]]
    for line, mark in zip(formatted[1:], marks):
        lines.append(line + "  " + mark if mark else line)
    return [title, *lines]


SEVERITY_LABEL = {
    "critical": "Critical",
    "important": "Important",
    "moderate": "Moderate",
    "low": "Low",
    "unspecified": "重要度なし",
}
UNCONFIRMED = "確認できませんでした"
REBOOT_LABEL = {"pending": "再起動待ち", "not_pending": "再起動待ちではない"}


def _dash(value) -> str:
    return value if value is not None else "-"


def _security_rows(sec: dict) -> list[tuple[str, str]]:
    head = "セキュリティ更新"
    if sec.get("status") != "ok":
        return [(head, UNCONFIRMED)]
    total = sec.get("total")
    if not total:
        return [(head, "0 件")]
    by = sec.get("by_severity") or {}
    parts = [
        f"{SEVERITY_LABEL[key]} {by.get(key, 0)}"
        for key in ("critical", "important", "moderate", "low", "unspecified")
    ]
    rows = [(head, f"{total} 件（{'、'.join(parts)}）")]
    for p in sec.get("packages", []):
        rows.append(("  " + p["name"], SEVERITY_LABEL.get(p["severity"], p["severity"])))
    return rows


def _reboot_row(reboot: dict) -> tuple[str, str]:
    label = REBOOT_LABEL.get(reboot.get("status"), UNCONFIRMED)
    running = _dash(reboot.get("running_kernel"))
    latest = _dash(reboot.get("latest_kernel"))
    return (
        "再起動待ち",
        f"{label}（動いている {running}、入っている最新 {latest}）",
    )


def _last_update_row(last: dict) -> tuple[str, str]:
    head = "最後に更新した日"
    status = last.get("status")
    if status == "ok":
        return (head, f"{_format_time(last['at'])}（{last['days_ago']} 日前）")
    if status == "none":
        return (head, "更新の記録がありません")
    return (head, UNCONFIRMED)


def _staleness_lines(st: dict) -> list[str]:
    rows = []
    if "security_updates" in st:
        rows.extend(_security_rows(st["security_updates"]))
    if "reboot" in st:
        rows.append(_reboot_row(st["reboot"]))
    if "last_update" in st:
        rows.append(_last_update_row(st["last_update"]))
    width = max([display_width(h) for h, _ in rows], default=0)
    return ["[古さ]"] + [(_pad(h, width) + "    " + v).rstrip() for h, v in rows]


def render_table(report: dict) -> str:
    if report.get("format") != "tojimari-check":
        raise ValueError("format が tojimari-check ではない")
    if report.get("schema_version") != 1:
        raise ValueError("知らない schema_version")
    report = display.replace_controls_deep(report)

    notice_list = report.get("notices", [])
    guarantee = [n["message"] for n in notice_list if n["id"] == "not_a_guarantee"]
    others = [n["message"] for n in notice_list if n["id"] != "not_a_guarantee"]

    lines = [f"Tojimari check  {_format_time(report['generated_at'])}"]
    lines.extend(guarantee)

    focus = report.get("checks", {}).get("focus_packages")
    if focus is not None:
        lines.append("")
        lines.append("[重点リスト]")
        rows = _focus_rows(focus)
        formatted = _format_rows(HEADERS, [cells for cells, _ in rows])
        lines.append(formatted[0])
        for line, (_, mark) in zip(formatted[1:], rows):
            if mark:
                line += "  " + mark
            lines.append(line)
        kernel = report.get("system", {}).get("running_kernel")
        lines.append(f"動いているカーネル: {kernel if kernel is not None else '-'}")

    user_installed = report.get("checks", {}).get("user_installed")
    if user_installed is not None:
        lines.append("")
        lines.extend(_user_installed_lines(user_installed))

    staleness = report.get("checks", {}).get("staleness")
    if staleness is not None:
        lines.append("")
        lines.extend(_staleness_lines(staleness))

    if others:
        lines.append("")
        lines.append("[注意]")
        lines.extend(f"- {m}" for m in others)

    return "\n".join(lines) + "\n"

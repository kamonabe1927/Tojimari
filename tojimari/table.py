"""レポートから人が読む表を作る。レポートだけを入力にする。"""

import unicodedata
from datetime import datetime

STATUS_LABEL = {"installed": "入っている", "not_installed": "入っていない"}
HEADERS = ["パッケージ", "状態", "バージョン", "アーキ", "入れた元"]
USER_INSTALLED_HEADERS = ["パッケージ", "バージョン", "アーキ", "入れた元"]
RUNNING_MARK = "<- 動いている"


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F", "A") else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * (width - display_width(text))


def _format_time(generated_at: str) -> str:
    dt = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _focus_rows(focus: dict) -> list[tuple[list[str], bool]]:
    """(5 列の文字列, 動いている印を付けるか) の並び。"""
    rows = []
    for pkg in focus.get("packages", []):
        label = STATUS_LABEL.get(pkg["status"], pkg["status"])
        versions = pkg.get("installed", [])
        if not versions:
            rows.append(([pkg["name"], label, "-", "", ""], False))
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
                    bool(v.get("is_running_kernel")),
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
    prev = None
    for p in pkgs:
        rows.append(
            [
                p["name"] if p["name"] != prev else "",
                p["evr"],
                p["arch"],
                p.get("from_repo") if p.get("from_repo") is not None else "-",
            ]
        )
        prev = p["name"]
    return [title, *_format_rows(USER_INSTALLED_HEADERS, rows)]


def render_table(report: dict) -> str:
    if report.get("format") != "tojimari-check":
        raise ValueError("format が tojimari-check ではない")
    if report.get("schema_version") != 1:
        raise ValueError("知らない schema_version")

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
        for line, (_, running) in zip(formatted[1:], rows):
            if running:
                line += "  " + RUNNING_MARK
            lines.append(line)
        kernel = report.get("system", {}).get("running_kernel")
        lines.append(f"動いているカーネル: {kernel if kernel is not None else '-'}")

    user_installed = report.get("checks", {}).get("user_installed")
    if user_installed is not None:
        lines.append("")
        lines.extend(_user_installed_lines(user_installed))

    if others:
        lines.append("")
        lines.append("[注意]")
        lines.extend(f"- {m}" for m in others)

    return "\n".join(lines) + "\n"

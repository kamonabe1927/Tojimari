"""レポートから人が読む表を作る。レポートだけを入力にする。"""

import unicodedata
from datetime import datetime

STATUS_LABEL = {"installed": "入っている", "not_installed": "入っていない"}
HEADERS = ["パッケージ", "状態", "バージョン", "アーキ", "入れた元"]
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
        widths = [display_width(h) for h in HEADERS]
        for cells, _ in rows:
            for i, c in enumerate(cells):
                widths[i] = max(widths[i], display_width(c))
        lines.append(
            "  ".join(_pad(h, w) for h, w in zip(HEADERS, widths)).rstrip()
        )
        for cells, running in rows:
            line = "  ".join(_pad(c, w) for c, w in zip(cells, widths)).rstrip()
            if running:
                line += "  " + RUNNING_MARK
            lines.append(line)
        kernel = report.get("system", {}).get("running_kernel")
        lines.append(f"動いているカーネル: {kernel if kernel is not None else '-'}")

    if others:
        lines.append("")
        lines.append("[注意]")
        lines.extend(f"- {m}" for m in others)

    return "\n".join(lines) + "\n"

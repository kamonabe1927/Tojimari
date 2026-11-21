"""引数、出し分け、終了コード。"""

import argparse
import json
import sys

from tojimari import runner
from tojimari.check import CheckError, collect
from tojimari.table import render_table


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tojimari")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="現状を確認して表示する")
    check.add_argument("--json", action="store_true", help="JSON で出力する")
    return parser


def main(argv=None, system=None, stdout=None, stderr=None) -> int:
    args = _build_parser().parse_args(argv)
    if system is None:
        system = runner.System()
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr

    try:
        report = collect(system)
    except CheckError as err:
        stderr.write(f"tojimari: {err}\n")
        return 1

    if args.json:
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    else:
        output = render_table(report)
    stdout.write(output)
    return 0

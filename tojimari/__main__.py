"""python3 -B -m tojimari の入口。"""

import sys

from tojimari.cli import main


def _setup_streams() -> None:
    # sudo で言語の設定が変わっても日本語を出せるようにする
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    _setup_streams()
    sys.exit(main())

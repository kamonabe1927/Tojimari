"""外部コマンド由来の文字列を、表示の前に見える形にする。何も実行しない。"""

STDERR_LINE_LIMIT = 200


def _piece(c: str) -> str:
    o = ord(c)
    return f"\\x{o:02x}" if o < 0x20 or 0x7F <= o <= 0x9F else c


def replace_controls(text: str) -> str:
    """C0、DEL、C1 を `\\x` と 16 進 2 桁の形にする。ほかの文字は変えない。"""
    return "".join(_piece(c) for c in text)


def replace_controls_deep(value):
    """dict・list・tuple の中の文字列を置き換えた写しを返す。入力は書き換えない。"""
    if isinstance(value, dict):
        return {k: replace_controls_deep(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [replace_controls_deep(v) for v in value]
    if isinstance(value, str):
        return replace_controls(value)
    return value


def replace_and_clip(text: str, limit: int = STDERR_LINE_LIMIT) -> str:
    """1 行を置き換え、置き換えた後の文字数が limit を超えたら切って印を付ける。"""
    pieces = [_piece(c) for c in text]
    total = sum(len(p) for p in pieces)
    if total <= limit:
        return "".join(pieces)
    kept = []
    used = 0
    for p in pieces:
        if used + len(p) > limit:
            break
        kept.append(p)
        used += len(p)
    return "".join(kept) + f" ...（残り {total - used} 文字を省略）"

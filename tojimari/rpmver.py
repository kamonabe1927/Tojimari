"""rpm の版の比べ方（rpmvercmp の手順）。文字列の計算だけで、何も実行しない。"""


_DIGITS = "0123456789"
_ALPHA = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ALNUM = _DIGITS + _ALPHA


def _cmp(a, b) -> int:
    return (a > b) - (a < b)


def vercmp(a: str, b: str) -> int:
    """a が新しければ 1、同じなら 0、古ければ -1。"""
    if a == b:
        return 0
    i = j = 0
    la, lb = len(a), len(b)
    while i < la or j < lb:
        while i < la and a[i] not in _ALNUM and a[i] not in "~^":
            i += 1
        while j < lb and b[j] not in _ALNUM and b[j] not in "~^":
            j += 1

        ca = a[i] if i < la else ""
        cb = b[j] if j < lb else ""

        if ca == "~" or cb == "~":
            if ca != "~":
                return 1
            if cb != "~":
                return -1
            i += 1
            j += 1
            continue

        if ca == "^" or cb == "^":
            if ca == "":
                return -1
            if cb == "":
                return 1
            if ca != "^":
                return 1
            if cb != "^":
                return -1
            i += 1
            j += 1
            continue

        if ca == "" or cb == "":
            break

        is_num = ca in _DIGITS
        charset = _DIGITS if is_num else _ALPHA
        si, sj = i, j
        while i < la and a[i] in charset:
            i += 1
        while j < lb and b[j] in charset:
            j += 1
        seg_a = a[si:i]
        seg_b = b[sj:j]
        if seg_b == "":
            return 1 if is_num else -1
        if is_num:
            seg_a = seg_a.lstrip("0")
            seg_b = seg_b.lstrip("0")
            if len(seg_a) != len(seg_b):
                return 1 if len(seg_a) > len(seg_b) else -1
        result = _cmp(seg_a, seg_b)
        if result != 0:
            return result

    if i >= la and j >= lb:
        return 0
    return 1 if i < la else -1


def _epoch(value) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def compare_evr(a, b) -> int:
    """epoch、version、release の順に比べる。a、b は .epoch .version .release を持つもの。"""
    result = _cmp(_epoch(a.epoch), _epoch(b.epoch))
    if result != 0:
        return result
    result = vercmp(a.version, b.version)
    if result != 0:
        return result
    return vercmp(a.release, b.release)

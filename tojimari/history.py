"""読み取り部。dnf 履歴に投げる SQL の形と、返ってきた行の読み取り。
データベースは開かない。何も実行しない（開くのは runner.read_history_db だけ）。"""

DB_PATH = "/var/lib/dnf/history.sqlite"

# 使う列。テーブル名はこの固定の名前だけを SQL に入れる
REQUIRED_COLUMNS = {
    "trans": ("id",),
    "trans_item": ("trans_id", "item_id"),
    "rpm": ("item_id", "name"),
}

_TABLE_INFO_SQL = {
    "trans": 'PRAGMA table_info("trans")',
    "trans_item": 'PRAGMA table_info("trans_item")',
    "rpm": 'PRAGMA table_info("rpm")',
}
_FIRST_TRANSACTION_SQL = "SELECT COUNT(*) FROM trans WHERE id = 1"
_FIRST_NAMES_SQL = (
    "SELECT DISTINCT rpm.name FROM trans_item "
    "JOIN rpm ON rpm.item_id = trans_item.item_id "
    "WHERE trans_item.trans_id = 1"
)

_REASONS = {
    "not_found": "dnf 履歴のデータベースが見つからない",
    "permission": "dnf 履歴のデータベースを読む権限が無い",
    "os_error": "dnf 履歴のデータベースを開けなかった",
    "busy": (
        "dnf 履歴のデータベースに書きかけの記録があった"
        "（dnf が動いている途中の可能性がある）"
    ),
    "changed": "読んでいる間に dnf 履歴のデータベースが書き換わった",
    "query_failed": "dnf 履歴のデータベースへの問い合わせが失敗した",
    "missing_columns": "dnf 履歴のデータベースに、使う列が無かった",
    "no_first_transaction": "dnf 履歴に 1 番の処理が無かった",
    "no_rpm_items": "dnf 履歴の 1 番にパッケージが 1 件も無かった",
}
_UNKNOWN_REASON = "dnf 履歴を読み取れなかった"


class HistoryError(Exception):
    """dnf 履歴が取れなかった（代わりの判定に切り替える）。"""

    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


def reason_text(kind: str) -> str:
    return _REASONS.get(kind, _UNKNOWN_REASON)


def query_first_transaction(execute) -> frozenset[str]:
    """履歴の 1 番の処理に含まれたパッケージ名の集まりを返す。取れなければ HistoryError。"""
    for table, columns in REQUIRED_COLUMNS.items():
        rows = execute(_TABLE_INFO_SQL[table])
        found = {row[1] for row in rows}
        if not all(c in found for c in columns):
            raise HistoryError("missing_columns")

    count_rows = execute(_FIRST_TRANSACTION_SQL)
    if not count_rows or count_rows[0][0] == 0:
        raise HistoryError("no_first_transaction")

    names = set()
    for row in execute(_FIRST_NAMES_SQL):
        value = row[0]
        if isinstance(value, str) and value != "":
            names.add(value)
    if not names:
        raise HistoryError("no_rpm_items")
    return frozenset(names)

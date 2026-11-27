import sqlite3
import unittest

from tests import recorded
from tojimari import history
from tojimari.history import HistoryError


def run(conn):
    return history.query_first_transaction(lambda sql: conn.execute(sql).fetchall())


class QueryTest(unittest.TestCase):
    def test_first_names_only(self):
        conn = recorded.memory_history_db(
            {1: ["kernel", "bash", "sudo", "bash"], 2: ["git", "htop"]}
        )
        self.assertEqual(run(conn), frozenset({"kernel", "bash", "sudo"}))

    def test_missing_table(self):
        conn = sqlite3.connect(":memory:")
        self.assertEqual(self._kind(conn), "missing_columns")

    def test_missing_columns(self):
        for drop in (("rpm", "name"), ("trans_item", "item_id"), ("trans", "id")):
            with self.subTest(drop=drop):
                conn = recorded.memory_history_db({1: ["bash"]})
                conn.execute(f"ALTER TABLE {drop[0]} DROP COLUMN {drop[1]}")
                self.assertEqual(self._kind(conn), "missing_columns")

    def test_no_first_transaction(self):
        conn = recorded.memory_history_db({2: ["git"]})
        self.assertEqual(self._kind(conn), "no_first_transaction")

    def test_no_rpm_items(self):
        conn = recorded.memory_history_db({1: [], 2: ["git"]})
        self.assertEqual(self._kind(conn), "no_rpm_items")

    def test_bad_names_dropped(self):
        conn = recorded.memory_history_db({1: ["bash"]})
        conn.execute("INSERT INTO rpm VALUES (900, NULL, 0, '1', '1', 'x')")
        conn.execute("INSERT INTO rpm VALUES (901, '', 0, '1', '1', 'x')")
        conn.execute("INSERT INTO rpm VALUES (902, 123, 0, '1', '1', 'x')")
        for i in (900, 901, 902):
            conn.execute("INSERT INTO trans_item VALUES (?, 1, ?, '', 0, 0, 0)", (i, i))
        self.assertEqual(run(conn), frozenset({"bash"}))

    def test_only_bad_names(self):
        conn = recorded.memory_history_db({1: [""]})
        self.assertEqual(self._kind(conn), "no_rpm_items")

    def _kind(self, conn):
        with self.assertRaises(HistoryError) as cm:
            run(conn)
        return cm.exception.kind


D = 1  # 完了（trans.state）
UP = 6  # 版を上げる項目（trans_item.action）


def last_upgrade(transactions, mutate=None):
    conn = sqlite3.connect(":memory:")
    recorded.make_upgrade_history_db(conn, transactions)
    if mutate:
        mutate(conn)
    return history.query_last_upgrade(lambda sql: conn.execute(sql).fetchall())


class LastUpgradeTest(unittest.TestCase):
    def test_newest_by_time_not_id(self):
        r = last_upgrade({
            1: (100, 200, D, [1]),
            2: (1000, 3000, D, [UP, 7]),
            3: (500, 600, D, [UP]),
            4: (4000, 5000, D, [1]),
        })
        self.assertEqual(r, 3000)

    def test_not_done_ignored(self):
        r = last_upgrade({
            1: (100, 200, D, [UP]),
            2: (1000, 3000, 0, [UP]),
            3: (1000, 4000, 2, [UP]),
        })
        self.assertEqual(r, 200)

    def test_no_upgrade_items(self):
        for actions in ([1], [7], [8], [1, 7, 8], []):
            with self.subTest(actions=actions):
                self.assertIsNone(last_upgrade({1: (100, 200, D, actions)}))

    def test_no_transactions(self):
        self.assertIsNone(last_upgrade({}))

    def test_dt_end_fallbacks(self):
        for dt_end in (0, None, "abc", -5, 253402300800, 1.5):
            with self.subTest(dt_end=dt_end):
                self.assertEqual(last_upgrade({1: (123, dt_end, D, [UP])}), 123)

    def test_dt_end_preferred(self):
        self.assertEqual(last_upgrade({1: (123, 456, D, [UP])}), 456)

    def test_no_usable_time(self):
        for pair in ((0, 0), (None, None), ("x", "y"), (-1, 0)):
            with self.subTest(pair=pair):
                with self.assertRaises(HistoryError) as cm:
                    last_upgrade({1: (pair[0], pair[1], D, [UP])})
                self.assertEqual(cm.exception.kind, "no_usable_time")

    def test_unusable_row_dropped_when_other_usable(self):
        r = last_upgrade({1: (0, 0, D, [UP]), 2: (10, 20, D, [UP])})
        self.assertEqual(r, 20)

    def test_missing_columns(self):
        for table, col in (("trans", "state"), ("trans", "dt_end"),
                           ("trans", "dt_begin"), ("trans", "id"),
                           ("trans_item", "action"), ("trans_item", "trans_id")):
            with self.subTest(drop=(table, col)):
                with self.assertRaises(HistoryError) as cm:
                    last_upgrade(
                        {1: (1, 2, D, [UP])},
                        lambda c: c.execute(f"ALTER TABLE {table} DROP COLUMN {col}"),
                    )
                self.assertEqual(cm.exception.kind, "missing_columns")

    def test_missing_table(self):
        conn = sqlite3.connect(":memory:")
        with self.assertRaises(HistoryError) as cm:
            history.query_last_upgrade(lambda sql: conn.execute(sql).fetchall())
        self.assertEqual(cm.exception.kind, "missing_columns")

    def test_first_transaction_unchanged_by_upgrade_db(self):
        conn = recorded.memory_history_db({1: ["bash"], 2: ["git"]})
        self.assertEqual(run(conn), frozenset({"bash"}))


class ReasonTest(unittest.TestCase):
    def test_all_kinds(self):
        kinds = ["not_found", "permission", "os_error", "busy", "no_shm", "no_wal",
                 "changed", "query_failed", "missing_columns", "no_first_transaction",
                 "no_rpm_items", "no_usable_time"]
        for k in kinds:
            with self.subTest(kind=k):
                self.assertTrue(history.reason_text(k))
                self.assertNotEqual(history.reason_text(k), history.reason_text("zzz"))
        self.assertEqual(history.reason_text("zzz"), "dnf 履歴を読み取れなかった")


class ImportTest(unittest.TestCase):
    def test_no_forbidden_imports(self):
        import re
        with open(history.__file__, encoding="utf-8") as f:
            src = f.read()
        for mod in ("sqlite3", "os", "subprocess"):
            self.assertIsNone(
                re.search(rf"^\s*(import|from)\s+{mod}\b", src, re.M), mod
            )


if __name__ == "__main__":
    unittest.main()

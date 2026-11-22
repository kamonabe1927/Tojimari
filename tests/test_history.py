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


class ReasonTest(unittest.TestCase):
    def test_all_kinds(self):
        kinds = ["not_found", "permission", "os_error", "busy", "changed",
                 "query_failed", "missing_columns", "no_first_transaction",
                 "no_rpm_items"]
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

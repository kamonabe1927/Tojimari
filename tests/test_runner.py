import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from tests import recorded
from tojimari import history, runner
from tojimari.history import HistoryError
from tojimari.runner import CommandError, System, read_history_db, run_command


def py(code):
    return [sys.executable, "-c", code]


class RunCommandTest(unittest.TestCase):
    def test_stdout(self):
        self.assertEqual(run_command(py("print('a\\tb')"), 10), "a\tb\n")

    def test_stderr_not_mixed(self):
        out = run_command(
            py("import sys; sys.stderr.write('e'); sys.stdout.write('o')"), 10
        )
        self.assertEqual(out, "o")

    def test_utf8_replace(self):
        out = run_command(
            py("import sys; sys.stdout.buffer.write(b'a\\xffb')"), 10
        )
        self.assertEqual(out, "a�b")

    def test_exit_status(self):
        with self.assertRaises(CommandError) as cm:
            run_command(
                py("import sys; sys.stderr.write('1\\n2\\n3\\n4\\n5\\n6\\n7\\n'); sys.exit(3)"),
                10,
            )
        self.assertEqual(cm.exception.kind, "exit_status")
        self.assertEqual(cm.exception.returncode, 3)
        self.assertEqual(cm.exception.stderr_tail, "3\n4\n5\n6\n7")

    def test_not_found(self):
        with self.assertRaises(CommandError) as cm:
            run_command(["/nonexistent/tojimari-test-command"], 10)
        self.assertEqual(cm.exception.kind, "not_found")

    def test_timeout(self):
        with self.assertRaises(CommandError) as cm:
            run_command(py("import time; time.sleep(5)"), 0.3)
        self.assertEqual(cm.exception.kind, "timeout")

    def test_stdin_closed(self):
        out = run_command(py("import sys; print(repr(sys.stdin.read()))"), 10)
        self.assertEqual(out, "''\n")


class SystemTest(unittest.TestCase):
    def test_simple_queries(self):
        s = System()
        self.assertIsInstance(s.is_root(), bool)
        self.assertIsNotNone(s.now().tzinfo)
        self.assertIsInstance(s.running_kernel(), (str, type(None)))


def make_db(directory, name="history.sqlite", wal=False, transactions=None):
    path = os.path.join(directory, name)
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    recorded.make_history_db(
        conn, transactions if transactions is not None else {1: ["bash", "sudo"], 2: ["git"]}
    )
    conn.close()
    return path


def listing(directory):
    return sorted(os.listdir(directory))


def error_kind(case, path, query=history.query_first_transaction):
    with case.assertRaises(HistoryError) as cm:
        read_history_db(path, query)
    return cm.exception.kind


class ReadHistoryDbTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def test_read(self):
        path = make_db(self.dir)
        self.assertEqual(
            read_history_db(path, history.query_first_transaction),
            frozenset({"bash", "sudo"}),
        )

    def test_files_unchanged(self):
        for wal in (False, True):
            with self.subTest(wal=wal):
                d = os.path.join(self.dir, f"wal{wal}")
                os.mkdir(d)
                path = make_db(d, wal=wal)
                before = listing(d)
                with open(path, "rb") as f:
                    content = f.read()
                read_history_db(path, history.query_first_transaction)
                self.assertEqual(listing(d), before)
                with open(path, "rb") as f:
                    self.assertEqual(f.read(), content)

    def test_not_found_creates_nothing(self):
        path = os.path.join(self.dir, "history.sqlite")
        self.assertEqual(error_kind(self, path), "not_found")
        self.assertEqual(listing(self.dir), [])

    def test_busy(self):
        for suffix in ("-journal", "-wal"):
            with self.subTest(suffix=suffix):
                d = os.path.join(self.dir, suffix[1:])
                os.mkdir(d)
                path = make_db(d)
                with open(path + suffix, "wb") as f:
                    f.write(b"x" * 8)
                self.assertEqual(error_kind(self, path), "busy")

    def test_empty_aux_files_ok(self):
        path = make_db(self.dir)
        for suffix in ("-journal", "-wal"):
            open(path + suffix, "wb").close()
        self.assertEqual(
            read_history_db(path, history.query_first_transaction),
            frozenset({"bash", "sudo"}),
        )

    def test_not_a_database(self):
        path = os.path.join(self.dir, "history.sqlite")
        with open(path, "wb") as f:
            f.write(b"this is not a database" * 20)
        self.assertEqual(error_kind(self, path), "query_failed")

    def test_changed_during_read(self):
        path = make_db(self.dir)

        def query(execute):
            result = history.query_first_transaction(execute)
            with open(path, "ab") as f:
                f.write(b"0")
            return result

        self.assertEqual(error_kind(self, path, query), "changed")

    def test_permission_and_os_error(self):
        path = make_db(self.dir)
        for exc, kind in ((PermissionError(), "permission"), (OSError(), "os_error")):
            with self.subTest(kind=kind):
                with mock.patch("tojimari.runner.os.stat", side_effect=exc):
                    self.assertEqual(error_kind(self, path), kind)

    def test_aux_stat_os_error(self):
        path = make_db(self.dir)
        real = os.stat

        def fake(p, *a, **kw):
            if str(p).endswith("-wal"):
                raise OSError()
            return real(p, *a, **kw)

        with mock.patch("tojimari.runner.os.stat", side_effect=fake):
            self.assertEqual(error_kind(self, path), "os_error")

    def test_write_sql_fails(self):
        path = make_db(self.dir)
        before = listing(self.dir)
        seen = {}

        def query(execute):
            with self.assertRaises(sqlite3.Error):
                execute("CREATE TABLE evil (x)")
            with self.assertRaises(sqlite3.Error):
                execute("DELETE FROM trans")
            seen["ok"] = True
            return execute("SELECT COUNT(*) FROM trans")[0][0]

        self.assertEqual(read_history_db(path, query), 2)
        self.assertTrue(seen["ok"])
        self.assertEqual(listing(self.dir), before)

    def test_connection_closed_after(self):
        path = make_db(self.dir)
        holder = {}

        def ok(execute):
            holder["execute"] = execute
            return 1

        def raise_history(execute):
            holder["execute"] = execute
            raise HistoryError("no_rpm_items")

        def raise_sqlite(execute):
            holder["execute"] = execute
            execute("SELECT * FROM no_such_table")

        for query, kind in ((ok, None), (raise_history, "no_rpm_items"),
                            (raise_sqlite, "query_failed")):
            with self.subTest(query=query.__name__):
                if kind is None:
                    read_history_db(path, query)
                else:
                    self.assertEqual(error_kind(self, path, query), kind)
                with self.assertRaises(sqlite3.Error):
                    holder["execute"]("SELECT 1")

    def test_odd_directory_name(self):
        d = os.path.join(self.dir, "a b?c#d%e")
        os.mkdir(d)
        path = make_db(d)
        self.assertEqual(
            read_history_db(path, history.query_first_transaction),
            frozenset({"bash", "sudo"}),
        )

    def test_uri_has_both_options(self):
        path = make_db(self.dir)
        with mock.patch.object(runner.sqlite3, "connect", wraps=sqlite3.connect) as m:
            read_history_db(path, lambda execute: 1)
        uri = m.call_args.args[0]
        self.assertTrue(uri.endswith("?mode=ro&immutable=1"))
        self.assertTrue(m.call_args.kwargs.get("uri"))


class ReadLastUpgradeTest(unittest.TestCase):
    def test_read_and_directory_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.sqlite")
            conn = sqlite3.connect(path)
            recorded.make_upgrade_history_db(
                conn, {1: (10, 20, 1, [6, 7]), 2: (30, 40, 1, [1])}
            )
            conn.close()
            before = sorted(os.listdir(d))
            self.assertEqual(read_history_db(path, history.query_last_upgrade), 20)
            self.assertEqual(sorted(os.listdir(d)), before)

    def test_missing_columns_through_runner(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.sqlite")
            conn = sqlite3.connect(path)
            recorded.make_history_db(conn, {1: ["bash"]})
            conn.execute("ALTER TABLE trans DROP COLUMN state")
            conn.commit()
            conn.close()
            with self.assertRaises(HistoryError) as cm:
                read_history_db(path, history.query_last_upgrade)
            self.assertEqual(cm.exception.kind, "missing_columns")


class SystemHistoryTest(unittest.TestCase):
    def test_uses_fixed_path(self):
        with mock.patch.object(runner, "read_history_db", return_value=frozenset()) as m:
            System().history_first_names()
        m.assert_called_once_with(history.DB_PATH, history.query_first_transaction)

    def test_userinstalled_argv(self):
        with mock.patch.object(runner, "run_command", return_value="x") as m:
            self.assertEqual(System().dnf_userinstalled(), "x")
        m.assert_called_once_with(runner.packages.DNF_USERINSTALLED_ARGV, runner.DNF_TIMEOUT)


if __name__ == "__main__":
    unittest.main()

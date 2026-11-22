import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from tests import recorded
from tojimari import history, packages, processes, runner
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


class FakeProc:
    """一時ディレクトリに架空の /proc の木を作る。"""

    def __init__(self, case):
        self.dir = tempfile.mkdtemp()
        case.addCleanup(self._cleanup)
        self.root = os.path.join(self.dir, "myroot")
        self.other = os.path.join(self.dir, "otherroot")
        self.proc = os.path.join(self.dir, "proc")
        for d in (self.root, self.other, self.proc):
            os.mkdir(d)

    def _cleanup(self):
        import shutil

        shutil.rmtree(self.dir, ignore_errors=True)

    def add(self, name, stat="1 (x) S 0\n", exe="/usr/bin/example", root=None, cgroup="0::/\n"):
        d = os.path.join(self.proc, name)
        os.mkdir(d)
        if stat is not None:
            with open(os.path.join(d, "stat"), "w") as f:
                f.write(stat)
        if cgroup is not None:
            with open(os.path.join(d, "cgroup"), "w") as f:
                f.write(cgroup)
        if exe is not None:
            os.symlink(exe, os.path.join(d, "exe"))
        os.symlink(root or self.root, os.path.join(d, "root"))
        # 読んではいけないファイル
        for secret in ("cmdline", "environ"):
            with open(os.path.join(d, secret), "w") as f:
                f.write("dummy")
        return d

    def tree(self):
        out = []
        for base, dirs, files in os.walk(self.dir):
            out.extend(os.path.join(base, n) for n in dirs + files)
        return sorted(out)


class ScanProcessesTest(unittest.TestCase):
    def setUp(self):
        self.fp = FakeProc(self)

    def scan(self):
        return runner.scan_processes(self.fp.proc, self.fp.root)

    def test_reads_values(self):
        self.fp.add("12", stat="12 (a) S 1 0\n", exe="/opt/a/bin", cgroup="0::/system.slice/a.service\n")
        self.fp.add("7", exe="/opt/b/bin", root=self.fp.other)
        scan = self.scan()
        self.assertIsInstance(scan, processes.ProcessScan)
        self.assertEqual(scan.self_pid, os.getpid())
        st = os.stat(self.fp.root)
        self.assertEqual(scan.own_root, (st.st_dev, st.st_ino))
        self.assertEqual([p.pid for p in scan.processes], [7, 12])
        p7, p12 = scan.processes
        self.assertEqual(p12.stat, "12 (a) S 1 0\n")
        self.assertEqual(p12.exe, "/opt/a/bin")
        self.assertIsNone(p12.exe_error)
        self.assertEqual(p12.root, scan.own_root)
        self.assertIsNone(p12.root_error)
        self.assertEqual(p12.cgroup, "0::/system.slice/a.service\n")
        other = os.stat(self.fp.other)
        self.assertEqual(p7.root, (other.st_dev, other.st_ino))
        self.assertNotEqual(p7.root, scan.own_root)

    def test_non_numeric_names_skipped(self):
        self.fp.add("1")
        for name in ("self", "sys", "12a", "-3"):
            os.mkdir(os.path.join(self.fp.proc, name))
        with open(os.path.join(self.fp.proc, "version"), "w") as f:
            f.write("x")
        self.assertEqual([p.pid for p in self.scan().processes], [1])

    def test_exe_missing_is_gone(self):
        self.fp.add("5", exe=None)
        p = self.scan().processes[0]
        self.assertIsNone(p.exe)
        self.assertEqual(p.exe_error, "gone")

    def test_broken_root_link_is_gone(self):
        self.fp.add("5", root=os.path.join(self.fp.dir, "missing"))
        p = self.scan().processes[0]
        self.assertIsNone(p.root)
        self.assertEqual(p.root_error, "gone")

    def test_stat_and_cgroup_unreadable_are_none(self):
        self.fp.add("5", stat=None, cgroup=None)
        p = self.scan().processes[0]
        self.assertIsNone(p.stat)
        self.assertIsNone(p.cgroup)
        self.assertEqual(p.exe, "/usr/bin/example")

    def test_non_utf8_replaced(self):
        d = self.fp.add("5")
        with open(os.path.join(d, "stat"), "wb") as f:
            f.write(b"5 (\xff\xfe) S 1\n")
        self.assertIn("\ufffd", self.scan().processes[0].stat)

    def test_error_kinds(self):
        self.fp.add("5")
        real_readlink, real_stat = os.readlink, os.stat
        cases = [
            (FileNotFoundError(), "gone"),
            (ProcessLookupError(), "gone"),
            (PermissionError(), "permission"),
            (OSError(), "other"),
        ]
        for exc, kind in cases:
            with self.subTest(exc=type(exc).__name__):
                def fake_readlink(p, *a, **kw):
                    if str(p).endswith("/exe"):
                        raise exc
                    return real_readlink(p, *a, **kw)

                def fake_stat(p, *a, **kw):
                    if str(p).endswith("/root"):
                        raise exc
                    return real_stat(p, *a, **kw)

                with mock.patch("tojimari.runner.os.readlink", side_effect=fake_readlink), \
                        mock.patch("tojimari.runner.os.stat", side_effect=fake_stat):
                    p = self.scan().processes[0]
                self.assertEqual((p.exe, p.exe_error), (None, kind))
                self.assertEqual((p.root, p.root_error), (None, kind))

    def test_proc_dir_missing(self):
        with self.assertRaises(processes.ScanError):
            runner.scan_processes(os.path.join(self.fp.dir, "none"), self.fp.root)

    def test_root_dir_missing(self):
        with self.assertRaises(processes.ScanError):
            runner.scan_processes(self.fp.proc, os.path.join(self.fp.dir, "none"))

    def test_listdir_permission(self):
        with mock.patch("tojimari.runner.os.listdir", side_effect=PermissionError()):
            with self.assertRaises(processes.ScanError):
                self.scan()

    def test_does_not_read_cmdline_or_environ(self):
        self.fp.add("5")
        real_open = open
        opened = []

        def spy(path, *a, **kw):
            opened.append(str(path))
            return real_open(path, *a, **kw)

        with mock.patch("tojimari.runner.open", spy, create=True):
            self.scan()
        self.assertTrue(opened)
        self.assertFalse([p for p in opened if p.endswith(("cmdline", "environ"))])

    def test_writes_nothing(self):
        self.fp.add("5")
        self.fp.add("6", exe=None)
        before = self.fp.tree()
        self.scan()
        self.assertEqual(self.fp.tree(), before)

    def test_system_delegates(self):
        sentinel = object()
        with mock.patch("tojimari.runner.scan_processes", return_value=sentinel) as m:
            self.assertIs(System().process_scan(), sentinel)
        m.assert_called_once_with()

    def test_rpm_files_argv(self):
        with mock.patch("tojimari.runner.run_command", return_value="x") as m:
            self.assertEqual(System().rpm_files(), "x")
        m.assert_called_once_with(packages.RPM_FILES_ARGV, runner.RPM_TIMEOUT)

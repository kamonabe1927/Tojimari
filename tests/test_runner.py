import sys
import unittest

from tojimari.runner import CommandError, System, run_command


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


if __name__ == "__main__":
    unittest.main()

import io
import json
import unittest

from tests import recorded
from tests.recorded import FakeSystem
from tojimari import check, cli, history, table
from tojimari.runner import CommandError


def run(argv, system=None):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, system=system or FakeSystem(), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def test_table(self):
        code, out, err = run(["check"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertTrue(out.startswith("Tojimari check  "))
        self.assertEqual(out, table.render_table(check.collect(FakeSystem())))

    def test_json(self):
        code, out, err = run(["check", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out), check.collect(FakeSystem()))
        self.assertTrue(out.endswith("}\n"))
        self.assertIn("\n  \"format\"", out)

    def test_json_keeps_order_and_japanese(self):
        _, out, _ = run(["check", "--json"])
        self.assertLess(out.index('"format"'), out.index('"notices"'))
        self.assertIn("外から届く入口", out)
        self.assertNotIn("\\u", out)

    def test_rpm_failure(self):
        for argv in (["check"], ["check", "--json"]):
            with self.subTest(argv=argv):
                sysm = FakeSystem(rpm=CommandError("not_found"))
                code, out, err = run(argv, sysm)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith("tojimari: "))
                self.assertIn("rpm", err)

    def test_rpm_parse_failure(self):
        code, out, err = run(["check", "--json"], FakeSystem(rpm=recorded.RPM_MALFORMED))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("tojimari: ", err)

    def test_dnf_failure_still_zero(self):
        code, out, _ = run(["check", "--json"], FakeSystem(dnf=CommandError("timeout", timeout=60)))
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["checks"]["focus_packages"]["from_repo_available"])

    def test_json_has_user_installed(self):
        _, out, _ = run(["check", "--json"])
        data = json.loads(out)
        self.assertEqual(
            data["checks"]["user_installed"],
            check.collect(FakeSystem())["checks"]["user_installed"],
        )
        self.assertEqual(data["checks"]["user_installed"]["status"], "ok")

    def test_json_has_staleness(self):
        _, out, _ = run(["check", "--json"])
        data = json.loads(out)
        self.assertEqual(
            list(data["checks"]),
            ["focus_packages", "user_installed", "staleness", "running_processes"],
        )
        self.assertEqual(
            data["checks"]["staleness"],
            check.collect(FakeSystem())["checks"]["staleness"],
        )

    def test_table_has_staleness(self):
        _, out, _ = run(["check"])
        self.assertIn("[古さ]", out)

    def test_security_failure_still_zero(self):
        for argv in (["check"], ["check", "--json"]):
            code, out, _ = run(argv, FakeSystem(security={None: CommandError("timeout", timeout=60)}))
            self.assertEqual(code, 0)
            self.assertIn("確認できませんでした" if argv == ["check"] else "security_updates_unavailable", out)

    def test_last_update_failure_still_zero(self):
        from tojimari.history import HistoryError
        code, out, _ = run(["check", "--json"], FakeSystem(last_upgrade=HistoryError("busy")))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["checks"]["staleness"]["last_update"]["status"], "unavailable")

    def test_history_failure_still_zero(self):
        from tojimari.history import HistoryError
        code, out, _ = run(["check", "--json"], FakeSystem(history=HistoryError("busy")))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["checks"]["user_installed"]["method"], "from_repo_fallback")
        self.assertIn("history_fallback", [n["id"] for n in data["notices"]])

    def test_new_wal_reasons_in_table_and_json(self):
        from tojimari.history import HistoryError
        for kind in ("no_shm", "no_wal"):
            with self.subTest(kind=kind):
                text = history.reason_text(kind)
                code, out, _ = run(["check"], FakeSystem(history=HistoryError(kind)))
                self.assertEqual(code, 0)
                self.assertIn("[注意]", out)
                self.assertIn(text, out)
                for word in ("保証", "担保", "安全です", "守られています"):
                    self.assertNotIn(word, out)
                code, out, _ = run(["check", "--json"], FakeSystem(history=HistoryError(kind)))
                self.assertEqual(code, 0)
                data = json.loads(out)
                self.assertEqual(data["checks"]["user_installed"]["method"], "from_repo_fallback")
                n = [n for n in data["notices"] if n["id"] == "history_fallback"]
                self.assertEqual(len(n), 1)
                self.assertIn(text, n[0]["message"])

    def test_userinstalled_failure_still_zero(self):
        for argv in (["check"], ["check", "--json"]):
            code, out, _ = run(argv, FakeSystem(userinstalled=CommandError("timeout", timeout=60)))
            self.assertEqual(code, 0)
            self.assertIn("確認できませんでした" if argv == ["check"] else "user_installed_unavailable", out)

    @staticmethod
    def bad_chars(text):
        return [
            c for c in text if c != "\n" and (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F)
        ]

    def test_stderr_controls_replaced(self):
        tail = "error: \x1b[31mdb\r\x08\x9b\n" + "y" * 250
        for argv in (["check"], ["check", "--json"]):
            with self.subTest(argv=argv):
                err = CommandError("exit_status", returncode=1, stderr_tail=tail)
                code, out, errtext = run(argv, FakeSystem(rpm=err))
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertEqual(self.bad_chars(errtext), [])
                lines = errtext.split("\n")
                self.assertEqual(
                    lines[0], "tojimari: rpm の問い合わせが終了コード 1 で失敗しました"
                )
                self.assertEqual(lines[1], "error: \\x1b[31mdb\\x0d\\x08\\x9b")
                self.assertIn("...（残り 50 文字を省略）", lines[2])

    def noisy_system(self):
        return FakeSystem(
            kernel="6.12.0-55.el10.aarch64\x1b[2J",
            dnf=recorded.DNF_ALL.replace("baseos", "base\x1b[31mos"),
        )

    def test_json_not_rewritten(self):
        code, out, err = run(["check", "--json"], self.noisy_system())
        self.assertEqual(code, 0)
        want = json.dumps(check.collect(self.noisy_system()), ensure_ascii=False, indent=2) + "\n"
        self.assertEqual(out, want)
        self.assertEqual(json.loads(out)["system"]["running_kernel"],
                         "6.12.0-55.el10.aarch64\x1b[2J")

    def test_table_controls_replaced(self):
        code, out, err = run(["check"], self.noisy_system())
        self.assertEqual(code, 0)
        self.assertEqual(self.bad_chars(out), [])
        line = [l for l in out.split("\n") if l.startswith("動いているカーネル:")][0]
        self.assertIn("\\x1b[2J", line)

    def test_bad_args(self):
        for argv in ([], ["unknown"], ["check", "--unknown"]):
            with self.subTest(argv=argv):
                err = io.StringIO()
                import contextlib
                with contextlib.redirect_stderr(err):
                    with self.assertRaises(SystemExit) as cm:
                        cli.main(argv, system=FakeSystem(), stdout=io.StringIO(),
                                 stderr=io.StringIO())
                self.assertEqual(cm.exception.code, 2)
                self.assertIn("usage", err.getvalue())


if __name__ == "__main__":
    unittest.main()

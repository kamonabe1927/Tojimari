import re
import unittest
from datetime import datetime, timezone

from tests import recorded
from tests.recorded import FakeSystem
from tojimari import check, history
from tojimari.check import CheckError
from tojimari.runner import CommandError


def pkg(report, name):
    for p in report["checks"]["focus_packages"]["packages"]:
        if p["name"] == name:
            return p
    raise KeyError(name)


def notice_ids(report):
    return [n["id"] for n in report["notices"]]


class FocusTest(unittest.TestCase):
    def test_all_installed_order(self):
        r = check.collect(FakeSystem())
        names = [p["name"] for p in r["checks"]["focus_packages"]["packages"]]
        self.assertEqual(
            names,
            ["kernel", "openssh-server", "openssh", "openssl-libs", "glibc",
             "sudo", "systemd", "polkit"],
        )
        for p in r["checks"]["focus_packages"]["packages"]:
            self.assertEqual(p["status"], "installed")
            self.assertTrue(p["reason"])

    def test_partial(self):
        r = check.collect(FakeSystem(rpm=recorded.RPM_PARTIAL))
        for n in ("polkit", "openssh-server"):
            self.assertEqual(pkg(r, n)["status"], "not_installed")
            self.assertEqual(pkg(r, n)["installed"], [])
        self.assertEqual(pkg(r, "sudo")["status"], "installed")

    def test_kernel_running(self):
        r = check.collect(FakeSystem())
        flags = {v["release"]: v["is_running_kernel"] for v in pkg(r, "kernel")["installed"]}
        self.assertEqual(flags, {"50.el10": False, "55.el10": True})
        self.assertNotIn("running_kernel_not_found", notice_ids(r))
        self.assertEqual(r["system"]["running_kernel"], recorded.RUNNING_KERNEL)

    def test_kernel_no_match(self):
        r = check.collect(FakeSystem(kernel="6.12.0-99.el10.aarch64"))
        self.assertFalse(any(v["is_running_kernel"] for v in pkg(r, "kernel")["installed"]))
        self.assertIn("running_kernel_not_found", notice_ids(r))

    def test_kernel_none(self):
        r = check.collect(FakeSystem(kernel=None))
        self.assertIsNone(r["system"]["running_kernel"])
        self.assertFalse(any(v["is_running_kernel"] for v in pkg(r, "kernel")["installed"]))
        self.assertIn("running_kernel_not_found", notice_ids(r))

    def test_kernel_not_installed_notice(self):
        rpm = "sudo\t\t1.9.15\t8.p5.el10\taarch64\n"
        r = check.collect(FakeSystem(rpm=rpm))
        self.assertEqual(pkg(r, "kernel")["status"], "not_installed")
        self.assertIn("running_kernel_not_found", notice_ids(r))

    def test_kernel_core_excluded(self):
        r = check.collect(FakeSystem())
        self.assertEqual(
            {v["name"] for v in pkg(r, "kernel")["installed"]}, {"kernel"}
        )
        self.assertEqual(len(pkg(r, "kernel")["installed"]), 2)

    def test_version_sort(self):
        rpm = (
            "kernel\t\t6.12.0\t55.el10\taarch64\n"
            "kernel\t\t6.12.0\t50.el10\taarch64\n"
            "glibc\t\t2.39\t43.el10\tx86_64\n"
            "glibc\t\t2.39\t43.el10\ti686\n"
        )
        r = check.collect(FakeSystem(rpm=rpm))
        self.assertEqual([v["release"] for v in pkg(r, "kernel")["installed"]],
                         ["50.el10", "55.el10"])
        self.assertEqual([v["arch"] for v in pkg(r, "glibc")["installed"]],
                         ["i686", "x86_64"])

    def test_multi_arch(self):
        r = check.collect(FakeSystem(rpm=recorded.RPM_MULTI_ARCH))
        self.assertEqual(len(pkg(r, "glibc")["installed"]), 2)

    def test_epoch(self):
        r = check.collect(FakeSystem())
        v = pkg(r, "openssl-libs")["installed"][0]
        self.assertEqual(v["epoch"], "1")
        self.assertEqual(v["evr"], "1:3.5.1-3.el10")
        self.assertEqual(v["from_repo"], "baseos")
        self.assertIsNone(pkg(r, "glibc")["installed"][0]["epoch"])


class FromRepoTest(unittest.TestCase):
    def test_available(self):
        r = check.collect(FakeSystem())
        fp = r["checks"]["focus_packages"]
        self.assertTrue(fp["from_repo_available"])
        self.assertEqual(pkg(r, "sudo")["installed"][0]["from_repo"], "appstream")
        self.assertNotIn("from_repo_unavailable", notice_ids(r))

    def test_dnf_names_passed(self):
        s = FakeSystem()
        check.collect(s)
        self.assertEqual([n for n, _ in check.FOCUS_PACKAGES], s.dnf_names)

    def test_command_errors(self):
        cases = [
            (CommandError("not_found"), "dnf コマンドが見つからない"),
            (CommandError("timeout"), "dnf が 60 秒で終わらなかった"),
            (CommandError("exit_status", returncode=1), "dnf が終了コード 1 で終わった"),
            (CommandError("os_error"), "dnf を実行できなかった"),
        ]
        for err, reason in cases:
            with self.subTest(kind=err.kind):
                r = check.collect(FakeSystem(dnf=err))
                fp = r["checks"]["focus_packages"]
                self.assertFalse(fp["from_repo_available"])
                for p in fp["packages"]:
                    for v in p["installed"]:
                        self.assertIsNone(v["from_repo"])
                n = [n for n in r["notices"] if n["id"] == "from_repo_unavailable"]
                self.assertEqual(len(n), 1)
                self.assertIn(reason, n[0]["message"])

    def test_stderr_not_in_report(self):
        err = CommandError("exit_status", returncode=1, stderr_tail="SECRETLIKE-TEXT")
        r = check.collect(FakeSystem(dnf=err))
        self.assertNotIn("SECRETLIKE-TEXT", repr(r))

    def test_no_match(self):
        r = check.collect(FakeSystem(dnf=""))
        self.assertFalse(r["checks"]["focus_packages"]["from_repo_available"])
        n = [n for n in r["notices"] if n["id"] == "from_repo_unavailable"]
        self.assertIn("dnf の出力に該当する版が無かった", n[0]["message"])
        self.assertIsNone(pkg(r, "sudo")["installed"][0]["from_repo"])

    def test_partial_match(self):
        r = check.collect(FakeSystem(dnf=recorded.DNF_PARTIAL))
        fp = r["checks"]["focus_packages"]
        self.assertTrue(fp["from_repo_available"])
        self.assertNotIn("from_repo_unavailable", notice_ids(r))
        k = {v["release"]: v["from_repo"] for v in pkg(r, "kernel")["installed"]}
        self.assertEqual(k, {"50.el10": "baseos", "55.el10": None})
        self.assertIsNone(pkg(r, "sudo")["installed"][0]["from_repo"])
        self.assertEqual(pkg(r, "glibc")["installed"][0]["from_repo"], None)

    def test_nothing_installed_dnf_ok(self):
        rpm = "bash\t\t5.2.26\t6.el10\taarch64\n"
        r = check.collect(FakeSystem(rpm=rpm, dnf=""))
        self.assertTrue(r["checks"]["focus_packages"]["from_repo_available"])
        self.assertNotIn("from_repo_unavailable", notice_ids(r))


class NoticeTest(unittest.TestCase):
    def test_root(self):
        r = check.collect(FakeSystem(root=True))
        self.assertTrue(r["run"]["is_root"])
        self.assertNotIn("not_root", notice_ids(r))

    def test_not_root(self):
        r = check.collect(FakeSystem(root=False))
        self.assertFalse(r["run"]["is_root"])
        self.assertIn("not_root", notice_ids(r))

    def test_always_three_and_order(self):
        r = check.collect(FakeSystem())
        self.assertEqual(
            notice_ids(r), ["not_a_guarantee", "scope", "running_is_snapshot"]
        )

    def test_order_with_all(self):
        r = check.collect(
            FakeSystem(root=False, dnf=CommandError("not_found"), kernel=None)
        )
        self.assertEqual(
            notice_ids(r),
            ["not_a_guarantee", "scope", "running_is_snapshot", "not_root",
             "from_repo_unavailable", "running_kernel_not_found"],
        )


class ReportShapeTest(unittest.TestCase):
    def test_top_level(self):
        r = check.collect(FakeSystem())
        self.assertEqual(
            list(r),
            ["format", "schema_version", "generated_at", "run", "system",
             "checks", "notices"],
        )
        self.assertEqual(r["format"], "tojimari-check")
        self.assertEqual(r["schema_version"], 1)
        self.assertEqual(r["generated_at"], "2026-11-21T09:39:12Z")
        self.assertRegex(r["generated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(list(r["checks"]), ["focus_packages", "user_installed"])
        self.assertEqual(list(r["run"]), ["is_root"])
        self.assertEqual(list(r["system"]), ["running_kernel"])
        self.assertEqual(
            list(r["checks"]["focus_packages"]), ["packages", "from_repo_available"]
        )

    def test_generated_at_converted_to_utc(self):
        from datetime import timedelta
        tz = timezone(timedelta(hours=9))
        r = check.collect(FakeSystem(now=datetime(2026, 11, 21, 18, 39, 0, tzinfo=tz)))
        self.assertEqual(r["generated_at"], "2026-11-21T09:39:00Z")

    def test_entry_keys(self):
        r = check.collect(FakeSystem())
        base = ["name", "epoch", "version", "release", "arch", "evr", "from_repo"]
        for p in r["checks"]["focus_packages"]["packages"]:
            self.assertEqual(list(p), ["name", "reason", "status", "installed"])
            for v in p["installed"]:
                if p["name"] == "kernel":
                    self.assertEqual(list(v), base + ["is_running_kernel"])
                else:
                    self.assertEqual(list(v), base)

    def test_no_future_keys(self):
        r = check.collect(FakeSystem())
        self.assertNotIn("staleness", r["checks"])
        for p in r["checks"]["focus_packages"]["packages"]:
            for v in p["installed"]:
                self.assertNotIn("running", v)
                self.assertNotIn("systemd_service", v)


def ui(report):
    return report["checks"]["user_installed"]


def ui_keys(report):
    return [(p["name"], p["version"], p["release"]) for p in ui(report)["packages"]]


class UserInstalledTest(unittest.TestCase):
    def test_history_method(self):
        s = FakeSystem()
        r = check.collect(s)
        self.assertTrue(s.history_called)
        self.assertEqual(ui(r)["status"], "ok")
        self.assertEqual(ui(r)["method"], "history")
        # kernel の 2 つの版（50 と 55）、kernel-core、更新された bash、sudo は除かれる
        self.assertEqual(
            [p["name"] for p in ui(r)["packages"]], ["gh", "git", "htop", "openssl"]
        )
        self.assertNotIn("history_fallback", notice_ids(r))
        self.assertNotIn("user_installed_unavailable", notice_ids(r))

    def test_entries(self):
        r = check.collect(FakeSystem())
        by = {p["name"]: p for p in ui(r)["packages"]}
        self.assertEqual(
            by["git"],
            {"name": "git", "epoch": None, "version": "2.47.1", "release": "1.el10",
             "arch": "aarch64", "evr": "2.47.1-1.el10", "from_repo": "appstream"},
        )
        self.assertEqual(by["openssl"]["epoch"], "1")
        self.assertEqual(by["openssl"]["evr"], "1:3.5.1-3.el10")

    def test_fallback_each_kind(self):
        for kind in ("not_found", "permission", "os_error", "busy", "changed",
                     "query_failed", "missing_columns", "no_first_transaction",
                     "no_rpm_items"):
            with self.subTest(kind=kind):
                r = check.collect(FakeSystem(history=history.HistoryError(kind)))
                self.assertEqual(ui(r)["status"], "ok")
                self.assertEqual(ui(r)["method"], "from_repo_fallback")
                names = [p["name"] for p in ui(r)["packages"]]
                # anaconda の行を持つ kernel、kernel-core、sudo は除かれ、bash は残る
                self.assertEqual(names, ["bash", "gh", "git", "htop", "openssl"])
                n = [n for n in r["notices"] if n["id"] == "history_fallback"]
                self.assertEqual(len(n), 1)
                self.assertIn(history.reason_text(kind), n[0]["message"])

    def test_unavailable(self):
        cases = [
            CommandError("not_found"),
            CommandError("timeout"),
            CommandError("exit_status", returncode=1),
            CommandError("os_error"),
            "",
            "kernel\tonly-two-fields\n",
            "zzz\t0\t1\t1\taarch64\tbaseos\n",
        ]
        for value in cases:
            with self.subTest(value=repr(value)):
                s = FakeSystem(userinstalled=value)
                r = check.collect(s)
                self.assertEqual(
                    ui(r), {"status": "unavailable", "method": None, "packages": []}
                )
                self.assertFalse(s.history_called)
                self.assertIn("user_installed_unavailable", notice_ids(r))
                self.assertNotIn("history_fallback", notice_ids(r))
                self.assertNotIn("from_repo_unavailable", notice_ids(r))
                self.assertTrue(r["checks"]["focus_packages"]["from_repo_available"])

    def test_unavailable_reasons(self):
        def reason(value):
            r = check.collect(FakeSystem(userinstalled=value))
            return [n for n in r["notices"] if n["id"] == "user_installed_unavailable"][0]["message"]
        self.assertIn("dnf が 60 秒で終わらなかった", reason(CommandError("timeout")))
        self.assertIn("dnf の出力に読み取れる行が無かった", reason(""))
        self.assertIn("dnf の出力が rpm の記録と突き合わなかった",
                      reason("zzz\t0\t1\t1\taarch64\tbaseos\n"))

    def test_stderr_not_in_report(self):
        err = CommandError("exit_status", returncode=1, stderr_tail="SECRETLIKE-TEXT")
        r = check.collect(FakeSystem(userinstalled=err))
        self.assertNotIn("SECRETLIKE-TEXT", repr(r))

    def test_zero_items(self):
        names = frozenset({"kernel", "kernel-core", "bash", "sudo", "git", "htop",
                           "gh", "openssl"})
        r = check.collect(FakeSystem(history=names))
        self.assertEqual(ui(r), {"status": "ok", "method": "history", "packages": []})
        self.assertEqual(
            notice_ids(r), ["not_a_guarantee", "scope", "running_is_snapshot"]
        )

    def test_multiple_versions_all_listed(self):
        r = check.collect(FakeSystem(history=frozenset({"bash", "sudo"})))
        kernels = [p for p in ui(r)["packages"] if p["name"] == "kernel"]
        self.assertEqual([p["release"] for p in kernels], ["50.el10", "55.el10"])
        self.assertEqual([p["from_repo"] for p in kernels], ["anaconda", "baseos"])

    def test_from_repo_null_when_key_missing(self):
        dnf = (
            "git\t0\t2.47.1\t1.el10\taarch64\tappstream\n"
        )
        rpm = (
            recorded.RPM_ALL_INSTALLED
            + "git\t\t2.46.0\t1.el10\taarch64\n"
        )
        r = check.collect(FakeSystem(rpm=rpm, userinstalled=dnf))
        git = [p for p in ui(r)["packages"] if p["name"] == "git"]
        self.assertEqual([p["version"] for p in git], ["2.46.0", "2.47.1"])
        self.assertEqual([p["from_repo"] for p in git], [None, "appstream"])

    def test_only_rpm_names_used(self):
        # dnf にだけある名前（rpm に無い）と、rpm にだけある名前は入れない
        dnf = (
            "git\t0\t2.47.1\t1.el10\taarch64\tappstream\n"
            "ghost\t0\t1\t1\taarch64\tepel\n"
        )
        r = check.collect(FakeSystem(userinstalled=dnf, history=frozenset({"sudo"})))
        self.assertEqual([p["name"] for p in ui(r)["packages"]], ["git"])

    def test_focus_name_also_listed(self):
        dnf = recorded.DNF_USERINSTALLED + "systemd\t0\t257\t9.el10\taarch64\tbaseos\n"
        r = check.collect(FakeSystem(userinstalled=dnf))
        self.assertIn("systemd", [p["name"] for p in ui(r)["packages"]])
        self.assertEqual(pkg(r, "systemd")["status"], "installed")

    def test_sorted(self):
        r = check.collect(FakeSystem(history=frozenset()))
        keys = [(p["name"], p["version"], p["release"], p["arch"]) for p in ui(r)["packages"]]
        self.assertEqual(keys, sorted(keys))

    def test_key_order(self):
        r = check.collect(FakeSystem())
        self.assertEqual(list(ui(r)), ["status", "method", "packages"])
        for v in ui(r)["packages"]:
            self.assertEqual(
                list(v),
                ["name", "epoch", "version", "release", "arch", "evr", "from_repo"],
            )

    def test_notice_order(self):
        r = check.collect(
            FakeSystem(root=False, dnf=CommandError("not_found"), kernel=None,
                       history=history.HistoryError("busy"))
        )
        self.assertEqual(
            notice_ids(r),
            ["not_a_guarantee", "scope", "running_is_snapshot", "not_root",
             "from_repo_unavailable", "running_kernel_not_found", "history_fallback"],
        )
        r = check.collect(
            FakeSystem(root=False, dnf=CommandError("not_found"), kernel=None,
                       userinstalled=CommandError("not_found"))
        )
        self.assertEqual(
            notice_ids(r)[-2:], ["running_kernel_not_found", "user_installed_unavailable"]
        )

    def test_focus_unchanged_when_userinstalled_fails(self):
        a = check.collect(FakeSystem())["checks"]["focus_packages"]
        b = check.collect(FakeSystem(userinstalled=CommandError("timeout")))["checks"]["focus_packages"]
        self.assertEqual(a, b)

    def test_os_names_from_repo(self):
        m = {("a", "0", "1", "1", "x"): "anaconda", ("a", "0", "2", "1", "x"): "baseos",
             ("b", "0", "1", "1", "x"): "baseos"}
        self.assertEqual(check.os_names_from_repo(m), frozenset({"a"}))


class ErrorTest(unittest.TestCase):
    def test_rpm_command_error(self):
        for kind in ("not_found", "timeout", "exit_status", "os_error"):
            with self.subTest(kind=kind):
                with self.assertRaises(CheckError):
                    check.collect(
                        FakeSystem(rpm=CommandError(kind, returncode=1 if kind == "exit_status" else None))
                    )

    def test_rpm_stderr_tail_in_message(self):
        err = CommandError("exit_status", returncode=1, stderr_tail="error: db")
        with self.assertRaises(CheckError) as cm:
            check.collect(FakeSystem(rpm=err))
        self.assertIn("終了コード 1", str(cm.exception))
        self.assertIn("error: db", str(cm.exception))

    def test_rpm_parse_error(self):
        for text in (recorded.RPM_MALFORMED, ""):
            with self.assertRaises(CheckError):
                check.collect(FakeSystem(rpm=text))


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from datetime import datetime, timezone

from tests import recorded
from tests.recorded import (
    FakeSystem, SELF_PID, SERVICE_CGROUP, make_proc, make_scan,
)
from tojimari import check, history, processes
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
            (CommandError("timeout", timeout=60), "dnf が 60 秒で終わらなかった"),
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
            notice_ids(r),
            ["not_a_guarantee", "scope", "running_is_snapshot",
             "security_updates_cache"],
        )

    def test_order_with_all(self):
        r = check.collect(
            FakeSystem(root=False, dnf=CommandError("not_found"), kernel=None)
        )
        self.assertEqual(
            notice_ids(r),
            ["not_a_guarantee", "scope", "running_is_snapshot", "not_root",
             "from_repo_unavailable", "running_kernel_not_found",
             "security_updates_cache", "reboot_unknown"],
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
        self.assertEqual(
            list(r["checks"]),
            ["focus_packages", "user_installed", "staleness", "running_processes"],
        )
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
        marks = ["running", "systemd_service"]
        for p in r["checks"]["focus_packages"]["packages"]:
            self.assertEqual(list(p), ["name", "reason", "status", "installed"])
            for v in p["installed"]:
                if p["name"] == "kernel":
                    self.assertEqual(list(v), base + ["is_running_kernel"] + marks)
                else:
                    self.assertEqual(list(v), base + marks)


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
             "arch": "aarch64", "evr": "2.47.1-1.el10", "from_repo": "appstream",
             "running": False, "systemd_service": False},
        )
        self.assertEqual(by["openssl"]["epoch"], "1")
        self.assertEqual(by["openssl"]["evr"], "1:3.5.1-3.el10")

    def test_fallback_each_kind(self):
        for kind in ("not_found", "permission", "os_error", "busy", "no_shm", "no_wal",
                     "changed", "query_failed", "missing_columns", "no_first_transaction",
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
            CommandError("timeout", timeout=60),
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
        self.assertIn("dnf が 60 秒で終わらなかった", reason(CommandError("timeout", timeout=60)))
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
            notice_ids(r),
            ["not_a_guarantee", "scope", "running_is_snapshot",
             "security_updates_cache"],
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
                ["name", "epoch", "version", "release", "arch", "evr", "from_repo",
                 "running", "systemd_service"],
            )

    def test_notice_order(self):
        r = check.collect(
            FakeSystem(root=False, dnf=CommandError("not_found"), kernel=None,
                       history=history.HistoryError("busy"))
        )
        self.assertEqual(
            notice_ids(r),
            ["not_a_guarantee", "scope", "running_is_snapshot", "not_root",
             "from_repo_unavailable", "running_kernel_not_found", "history_fallback",
             "security_updates_cache", "reboot_unknown"],
        )
        r = check.collect(
            FakeSystem(root=False, dnf=CommandError("not_found"), kernel=None,
                       userinstalled=CommandError("not_found"))
        )
        self.assertEqual(
            notice_ids(r)[-4:],
            ["running_kernel_not_found", "user_installed_unavailable",
             "security_updates_cache", "reboot_unknown"],
        )

    def test_focus_unchanged_when_userinstalled_fails(self):
        a = check.collect(FakeSystem())["checks"]["focus_packages"]
        b = check.collect(FakeSystem(userinstalled=CommandError("timeout", timeout=60)))["checks"]["focus_packages"]
        self.assertEqual(a, b)

    def test_os_names_from_repo(self):
        m = {("a", "0", "1", "1", "x"): "anaconda", ("a", "0", "2", "1", "x"): "baseos",
             ("b", "0", "1", "1", "x"): "baseos"}
        self.assertEqual(check.os_names_from_repo(m), frozenset({"a"}))


class StalenessCheckTest(unittest.TestCase):
    def test_key_order_and_values(self):
        r = check.collect(FakeSystem())
        st = r["checks"]["staleness"]
        self.assertEqual(list(st), ["security_updates", "reboot", "last_update"])
        self.assertEqual(
            list(st["security_updates"]), ["status", "total", "by_severity", "packages"]
        )
        self.assertEqual(
            list(st["reboot"]), ["status", "running_kernel", "latest_kernel"]
        )
        self.assertEqual(list(st["last_update"]), ["status", "at", "days_ago"])
        self.assertEqual(st["reboot"]["running_kernel"], r["system"]["running_kernel"])
        self.assertEqual(st["last_update"]["at"], "2026-11-20T10:00:00Z")
        self.assertEqual(r["schema_version"], 1)

    def test_notices_when_ok(self):
        r = check.collect(FakeSystem())
        ids = notice_ids(r)
        self.assertIn("security_updates_cache", ids)
        for i in ("security_updates_unavailable", "reboot_unknown",
                  "last_update_unavailable"):
            self.assertNotIn(i, ids)

    def test_zero_security_still_has_cache_notice(self):
        data = dict(recorded.SECURITY_DEFAULT)
        data[None] = ""
        r = check.collect(FakeSystem(security=data))
        self.assertEqual(r["checks"]["staleness"]["security_updates"]["total"], 0)
        self.assertIn("security_updates_cache", notice_ids(r))

    def test_security_unavailable(self):
        data = dict(recorded.SECURITY_DEFAULT)
        data[None] = CommandError("exit_status", returncode=1,
                                  stderr_tail="SECRETLIKE-TEXT")
        base = check.collect(FakeSystem())
        r = check.collect(FakeSystem(security=data))
        self.assertEqual(
            r["checks"]["staleness"]["security_updates"]["status"], "unavailable"
        )
        ids = notice_ids(r)
        self.assertIn("security_updates_unavailable", ids)
        self.assertNotIn("security_updates_cache", ids)
        msg = next(n["message"] for n in r["notices"]
                   if n["id"] == "security_updates_unavailable")
        self.assertIn("dnf が終了コード 1 で終わった", msg)
        self.assertNotIn("SECRETLIKE-TEXT", repr(r))
        self.assertEqual(r["checks"]["focus_packages"], base["checks"]["focus_packages"])
        self.assertEqual(r["checks"]["user_installed"], base["checks"]["user_installed"])
        self.assertEqual(r["checks"]["staleness"]["reboot"], base["checks"]["staleness"]["reboot"])

    def test_reboot_unknown(self):
        r = check.collect(FakeSystem(kernel=None))
        self.assertEqual(r["checks"]["staleness"]["reboot"]["status"], "unknown")
        self.assertIn("reboot_unknown", notice_ids(r))
        self.assertIn("running_kernel_not_found", notice_ids(r))

    def test_last_update_unavailable_and_none(self):
        r = check.collect(FakeSystem(last_upgrade=history.HistoryError("busy")))
        self.assertEqual(r["checks"]["staleness"]["last_update"]["status"], "unavailable")
        self.assertIn("last_update_unavailable", notice_ids(r))
        msg = next(n["message"] for n in r["notices"]
                   if n["id"] == "last_update_unavailable")
        self.assertIn(history.reason_text("busy"), msg)
        r = check.collect(FakeSystem(last_upgrade=None))
        self.assertEqual(r["checks"]["staleness"]["last_update"]["status"], "none")
        self.assertNotIn("last_update_unavailable", notice_ids(r))

    def test_notice_order(self):
        data = dict(recorded.SECURITY_DEFAULT)
        data[None] = CommandError("timeout", timeout=60)
        r = check.collect(
            FakeSystem(security=data, kernel=None,
                       last_upgrade=history.HistoryError("busy"),
                       userinstalled=CommandError("not_found"))
        )
        self.assertEqual(
            notice_ids(r)[-5:],
            ["running_kernel_not_found", "user_installed_unavailable",
             "security_updates_unavailable", "reboot_unknown",
             "last_update_unavailable"],
        )

    def test_user_installed_not_changed_by_staleness(self):
        a = check.collect(FakeSystem())["checks"]["user_installed"]
        b = check.collect(FakeSystem(last_upgrade=None))["checks"]["user_installed"]
        self.assertEqual(a, b)


class ErrorTest(unittest.TestCase):
    def test_rpm_command_error(self):
        for kind in ("not_found", "timeout", "exit_status", "os_error"):
            with self.subTest(kind=kind):
                with self.assertRaises(CheckError):
                    check.collect(
                        FakeSystem(
                            rpm=CommandError(
                                kind,
                                returncode=1 if kind == "exit_status" else None,
                                timeout=30 if kind == "timeout" else None,
                            )
                        )
                    )

    def test_rpm_stderr_tail_in_message(self):
        err = CommandError("exit_status", returncode=1, stderr_tail="error: db")
        with self.assertRaises(CheckError) as cm:
            check.collect(FakeSystem(rpm=err))
        self.assertIn("終了コード 1", str(cm.exception))
        self.assertIn("error: db", str(cm.exception))

    def rpm_message(self, err):
        with self.assertRaises(CheckError) as cm:
            check.collect(FakeSystem(rpm=err))
        return str(cm.exception)

    def test_rpm_timeout_message(self):
        msg = self.rpm_message(CommandError("timeout", timeout=30))
        self.assertEqual(msg, "rpm の問い合わせが 30 秒で終わりませんでした")

    def test_rpm_timeout_seconds_come_from_error(self):
        msg = self.rpm_message(CommandError("timeout", timeout=7))
        self.assertEqual(msg, "rpm の問い合わせが 7 秒で終わりませんでした")

    def test_rpm_timeout_without_seconds(self):
        msg = self.rpm_message(CommandError("timeout"))
        self.assertEqual(msg, "rpm の問い合わせが時間内に終わりませんでした")
        self.assertFalse(any(ch.isdigit() for ch in msg))

    def test_rpm_timeout_stderr_tail(self):
        msg = self.rpm_message(CommandError("timeout", timeout=30, stderr_tail="error: db"))
        self.assertEqual(msg, "rpm の問い合わせが 30 秒で終わりませんでした\nerror: db")

    def test_rpm_stderr_tail_controls_replaced(self):
        msg = self.rpm_message(
            CommandError("exit_status", returncode=1, stderr_tail="error: \x1b[31mdb\r\x08")
        )
        lines = msg.split("\n")
        self.assertEqual(lines[0], "rpm の問い合わせが終了コード 1 で失敗しました")
        self.assertEqual(lines[1], "error: \\x1b[31mdb\\x0d\\x08")
        self.assertEqual(len(lines), 2)

    def test_rpm_stderr_tail_five_lines(self):
        tail = "\n".join(f"l{i}\r" for i in range(5))
        msg = self.rpm_message(CommandError("exit_status", returncode=1, stderr_tail=tail))
        self.assertEqual(len(msg.split("\n")), 6)

    def test_rpm_stderr_tail_long_line_clipped(self):
        tail = "short\n" + "x" * 201
        msg = self.rpm_message(CommandError("exit_status", returncode=1, stderr_tail=tail))
        lines = msg.split("\n")
        self.assertEqual(lines[1], "short")
        self.assertEqual(lines[2], "x" * 200 + " ...（残り 1 文字を省略）")
        self.assertEqual(lines[0], "rpm の問い合わせが終了コード 1 で失敗しました")

    def test_rpm_timeout_stderr_tail_controls_replaced(self):
        msg = self.rpm_message(
            CommandError("timeout", timeout=30, stderr_tail="error: \x1b[31mdb\r\x08")
        )
        self.assertEqual(
            msg,
            "rpm の問い合わせが 30 秒で終わりませんでした\nerror: \\x1b[31mdb\\x0d\\x08",
        )

    def test_rpm_parse_error(self):
        for text in (recorded.RPM_MALFORMED, ""):
            with self.assertRaises(CheckError):
                check.collect(FakeSystem(rpm=text))


if __name__ == "__main__":
    unittest.main()


def ui_by_name(report):
    return {p["name"]: p for p in report["checks"]["user_installed"]["packages"]}


def marks_of(v):
    return (v["running"], v["systemd_service"])


def running_system(extra=(), **kw):
    procs = [
        make_proc(10, exe="/usr/sbin/sshd", cgroup=SERVICE_CGROUP),
        make_proc(11, exe="/usr/bin/htop"),
        make_proc(100, exe="/usr/bin/sudo", ppid=50),
        make_proc(SELF_PID, exe="/usr/bin/git", ppid=100),
        make_proc(5001, exe="/usr/bin/bash", ppid=SELF_PID),
    ]
    procs.extend(extra)
    return FakeSystem(processes=make_scan(*procs), **kw)


class RunningTest(unittest.TestCase):
    def test_default_no_processes(self):
        fs = FakeSystem()
        r = check.collect(fs)
        self.assertEqual(r["checks"]["running_processes"], {"status": "ok", "unreadable": 0})
        for p in r["checks"]["focus_packages"]["packages"]:
            for v in p["installed"]:
                self.assertEqual(marks_of(v), (False, False))
        for v in ui_by_name(r).values():
            self.assertEqual(marks_of(v), (False, False))
        for n in ("running_unavailable", "running_partial"):
            self.assertNotIn(n, notice_ids(r))
        self.assertTrue(fs.rpm_files_called)

    def test_marks(self):
        r = check.collect(running_system())
        self.assertEqual(r["checks"]["running_processes"], {"status": "ok", "unreadable": 0})
        self.assertEqual(list(r["checks"]["running_processes"]), ["status", "unreadable"])
        self.assertEqual(marks_of(pkg(r, "openssh-server")["installed"][0]), (True, True))
        # Tojimari を起動した sudo（pid 100）には印が付かない
        self.assertEqual(marks_of(pkg(r, "sudo")["installed"][0]), (False, False))
        self.assertEqual(marks_of(pkg(r, "polkit")["installed"][0]), (False, False))
        self.assertEqual(marks_of(ui_by_name(r)["htop"]), (True, False))
        # Tojimari 自身（git の実行ファイルとして置いた）とその子には印が付かない
        self.assertEqual(marks_of(ui_by_name(r)["git"]), (False, False))
        self.assertEqual(marks_of(pkg(r, "kernel")["installed"][0]), (False, False))
        self.assertNotIn("running_partial", notice_ids(r))

    def test_unrelated_sudo_is_marked(self):
        extra = [make_proc(200, exe="/usr/bin/sudo", ppid=1)]
        r = check.collect(running_system(extra=extra))
        self.assertEqual(r["checks"]["running_processes"], {"status": "ok", "unreadable": 0})
        self.assertEqual(marks_of(pkg(r, "sudo")["installed"][0]), (True, False))

    def test_sudo_not_stripped_when_started_from_shell(self):
        procs = [
            make_proc(200, exe="/usr/bin/sudo", ppid=1),
            make_proc(60, exe="/usr/bin/bash", ppid=1),
            make_proc(SELF_PID, exe="/usr/bin/git", ppid=60),
        ]
        r = check.collect(FakeSystem(processes=make_scan(*procs)))
        self.assertEqual(marks_of(pkg(r, "sudo")["installed"][0]), (True, False))

    def test_systemd_package_marked_via_service(self):
        procs = [make_proc(10, exe="/usr/lib/systemd/systemd-journald", cgroup=SERVICE_CGROUP),
                 make_proc(1, exe="/usr/lib/systemd/systemd", cgroup="0::/init.scope\n")]
        r = check.collect(FakeSystem(processes=make_scan(*procs)))
        self.assertEqual(marks_of(pkg(r, "systemd")["installed"][0]), (True, True))

    def test_unknown_path_ignored(self):
        r = check.collect(FakeSystem(processes=make_scan(make_proc(10, exe="/opt/zzz"))))
        self.assertEqual(r["checks"]["running_processes"]["status"], "ok")
        self.assertFalse(any(
            v["running"] for p in r["checks"]["focus_packages"]["packages"] for v in p["installed"]
        ))

    def test_partial(self):
        procs = [make_proc(10, exe_error="permission"), make_proc(11, root_error="permission"),
                 make_proc(12, exe_error="gone")]
        r = check.collect(FakeSystem(processes=make_scan(*procs)))
        self.assertEqual(r["checks"]["running_processes"], {"status": "ok", "unreadable": 2})
        n = [x for x in r["notices"] if x["id"] == "running_partial"]
        self.assertEqual(len(n), 1)
        self.assertIn("2 個", n[0]["message"])

    def test_scan_error(self):
        fs = FakeSystem(processes=processes.ScanError("x"))
        r = check.collect(fs)
        self.assertEqual(r["checks"]["running_processes"], {"status": "unavailable", "unreadable": None})
        self.assertFalse(fs.rpm_files_called)
        for p in r["checks"]["focus_packages"]["packages"]:
            for v in p["installed"]:
                self.assertEqual(marks_of(v), (None, None))
        for v in ui_by_name(r).values():
            self.assertEqual(marks_of(v), (None, None))
        n = [x for x in r["notices"] if x["id"] == "running_unavailable"]
        self.assertEqual(len(n), 1)
        self.assertIn("/proc を読み取れなかった", n[0]["message"])
        self.assertNotIn("running_partial", notice_ids(r))
        # ほかの確認はそのまま
        base = check.collect(FakeSystem())
        self.assertEqual(r["checks"]["staleness"], base["checks"]["staleness"])
        self.assertEqual(
            [p["name"] for p in r["checks"]["focus_packages"]["packages"]],
            [p["name"] for p in base["checks"]["focus_packages"]["packages"]],
        )

    def test_rpm_files_command_errors(self):
        reasons = {
            "timeout": "rpm が 30 秒で終わらなかった",
            "exit_status": "rpm が終了コード 1 で終わった",
            "not_found": "rpm コマンドが見つからない",
        }
        for kind, reason in reasons.items():
            with self.subTest(kind=kind):
                err = CommandError(
                    kind,
                    returncode=1,
                    stderr_tail="secret-ish text",
                    timeout=30 if kind == "timeout" else None,
                )
                r = check.collect(running_system(rpm_files=err))
                self.assertEqual(r["checks"]["running_processes"]["status"], "unavailable")
                n = [x for x in r["notices"] if x["id"] == "running_unavailable"]
                self.assertIn(reason, n[0]["message"])
                self.assertNotIn("secret-ish", n[0]["message"])
                self.assertIsNone(pkg(r, "sudo")["installed"][0]["running"])

    def test_rpm_files_parse_error(self):
        r = check.collect(running_system(rpm_files="garbage\n"))
        self.assertEqual(r["checks"]["running_processes"], {"status": "unavailable", "unreadable": None})
        n = [x for x in r["notices"] if x["id"] == "running_unavailable"]
        self.assertIn("rpm の出力を読み取れなかった", n[0]["message"])

    def test_rpm_files_called_even_with_no_candidates(self):
        fs = FakeSystem(rpm_files=CommandError("timeout", timeout=30))
        r = check.collect(fs)
        self.assertTrue(fs.rpm_files_called)
        self.assertEqual(r["checks"]["running_processes"]["status"], "unavailable")

    def test_notice_order(self):
        r = check.collect(FakeSystem(
            processes=make_scan(make_proc(10, exe_error="permission")),
            last_upgrade=history.HistoryError("not_found"),
            root=False,
        ))
        ids = notice_ids(r)
        self.assertEqual(ids[-2:], ["last_update_unavailable", "running_partial"])
        r = check.collect(FakeSystem(
            processes=processes.ScanError("x"), last_upgrade=history.HistoryError("not_found"),
        ))
        self.assertEqual(notice_ids(r)[-2:], ["last_update_unavailable", "running_unavailable"])

    def test_no_paths_or_pids_in_output(self):
        import json

        procs = [make_proc(7777, exe="/home/fakeuser/secret-tool", exe_error=None),
                 make_proc(7778, exe_error="permission"),
                 make_proc(7779, exe="/usr/sbin/sshd", cgroup="0::/system.slice/fakename.service\n")]
        r = check.collect(FakeSystem(processes=make_scan(*procs)))
        text = json.dumps(r, ensure_ascii=False)
        for word in ("fakeuser", "secret-tool", "7777", "7778", "7779", "fakename"):
            self.assertNotIn(word, text)
        r = check.collect(FakeSystem(processes=make_scan(*procs), rpm_files=CommandError("timeout", timeout=30)))
        text = json.dumps(r, ensure_ascii=False)
        for word in ("fakeuser", "secret-tool", "7777"):
            self.assertNotIn(word, text)

    def test_snapshot_notice_text(self):
        r = check.collect(FakeSystem())
        msg = [n for n in r["notices"] if n["id"] == "running_is_snapshot"][0]["message"]
        self.assertIn("Docker コンテナの中で動いているものには印を付けません。", msg)
        self.assertIn("再起動していないプロセスは、新しい版の印として出ます。", msg)

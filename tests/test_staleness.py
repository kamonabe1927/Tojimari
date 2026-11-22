import unittest
from datetime import datetime, timedelta, timezone

from tests import recorded
from tests.recorded import FakeSystem
from tojimari import history, packages, staleness
from tojimari.runner import CommandError

NOW = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)


def pv(name, version, release, arch="aarch64", epoch=None):
    return packages.PackageVersion(name, epoch, version, release, arch)


def sec_map(**kw):
    out = {k: frozenset() for k in ("critical", "important", "moderate", "low")}
    out.update({k: frozenset(v) for k, v in kw.items()})
    return out


class SecurityBuildTest(unittest.TestCase):
    def test_counts_and_order(self):
        r = staleness.build_security_updates(
            frozenset({"b", "a", "c", "d", "e"}),
            sec_map(critical={"e"}, important={"b", "a"}, low={"d"}),
        )
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["total"], 5)
        self.assertEqual(
            r["by_severity"],
            {"critical": 1, "important": 2, "moderate": 0, "low": 1, "unspecified": 1},
        )
        self.assertEqual(list(r["by_severity"]), list(staleness.SEVERITY_KEYS))
        self.assertEqual(
            r["packages"],
            [{"name": "e", "severity": "critical"},
             {"name": "a", "severity": "important"},
             {"name": "b", "severity": "important"},
             {"name": "d", "severity": "low"},
             {"name": "c", "severity": "unspecified"}],
        )
        self.assertEqual(sum(r["by_severity"].values()), r["total"])

    def test_heaviest_only(self):
        r = staleness.build_security_updates(
            frozenset({"x"}),
            sec_map(important={"x"}, moderate={"x"}, low={"x"}),
        )
        self.assertEqual(r["by_severity"]["important"], 1)
        self.assertEqual(r["by_severity"]["moderate"], 0)
        self.assertEqual(r["total"], 1)

    def test_names_outside_security_not_counted(self):
        r = staleness.build_security_updates(
            frozenset({"x"}), sec_map(critical={"y"})
        )
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["by_severity"]["critical"], 0)
        self.assertEqual(r["packages"], [{"name": "x", "severity": "unspecified"}])

    def test_zero_is_ok(self):
        r = staleness.build_security_updates(frozenset(), {})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["packages"], [])
        self.assertEqual(list(r["by_severity"]), list(staleness.SEVERITY_KEYS))

    def test_unavailable(self):
        self.assertEqual(
            staleness.build_security_updates(None, {}),
            {"status": "unavailable", "total": None, "by_severity": None,
             "packages": []},
        )


class SecurityCollectTest(unittest.TestCase):
    def collect(self, **kw):
        s = FakeSystem(**kw)
        st, problems = staleness.collect(
            s, packages.parse_rpm_list(recorded.RPM_ALL_INSTALLED),
            recorded.RUNNING_KERNEL, NOW,
        )
        return s, st["security_updates"], problems["security_updates"]

    def test_default(self):
        s, sec, problem = self.collect()
        self.assertIsNone(problem)
        self.assertEqual(sec["total"], 3)
        self.assertEqual(
            sec["by_severity"],
            {"critical": 0, "important": 1, "moderate": 1, "low": 0, "unspecified": 1},
        )
        self.assertEqual(
            [(p["name"], p["severity"]) for p in sec["packages"]],
            [("openssl-libs", "important"), ("git", "moderate"),
             ("bash", "unspecified")],
        )
        self.assertEqual(
            s.security_calls, [None, "Critical", "Important", "Moderate", "Low"]
        )

    def test_zero_skips_severity_calls(self):
        sec_data = dict(recorded.SECURITY_DEFAULT)
        sec_data[None] = ""
        s, sec, problem = self.collect(security=sec_data)
        self.assertEqual(sec["status"], "ok")
        self.assertEqual(sec["total"], 0)
        self.assertIsNone(problem)
        self.assertEqual(s.security_calls, [None])

    def test_failure_in_each_call(self):
        order = [None, "Critical", "Important", "Moderate", "Low"]
        for i, key in enumerate(order):
            with self.subTest(call=key):
                data = dict(recorded.SECURITY_DEFAULT)
                data[key] = CommandError("exit_status", returncode=1,
                                         stderr_tail="SECRETLIKE-TEXT")
                s, sec, problem = self.collect(security=data)
                self.assertEqual(sec["status"], "unavailable")
                self.assertIsNone(sec["total"])
                self.assertEqual(problem, "dnf が終了コード 1 で終わった")
                self.assertEqual(s.security_calls, order[: i + 1])

    def test_failure_kinds(self):
        cases = {
            "not_found": "dnf コマンドが見つからない",
            "timeout": "dnf が 60 秒で終わらなかった",
            "os_error": "dnf を実行できなかった",
        }
        for kind, text in cases.items():
            with self.subTest(kind=kind):
                data = dict(recorded.SECURITY_DEFAULT)
                data[None] = CommandError(kind)
                _, sec, problem = self.collect(security=data)
                self.assertEqual(sec["status"], "unavailable")
                self.assertEqual(problem, text)

    def test_parse_error_stops(self):
        for key in (None, "Low"):
            with self.subTest(call=key):
                data = dict(recorded.SECURITY_DEFAULT)
                data[key] = "bad line with spaces\n"
                s, sec, problem = self.collect(security=data)
                self.assertEqual(sec["status"], "unavailable")
                self.assertEqual(problem, "dnf の出力を読み取れなかった")
                self.assertEqual(s.security_calls[-1], key)

    def test_other_exceptions_not_hidden(self):
        data = dict(recorded.SECURITY_DEFAULT)
        data[None] = RuntimeError("bug")
        with self.assertRaises(RuntimeError):
            self.collect(security=data)


class RebootTest(unittest.TestCase):
    K = [pv("kernel", "6.12.0", "50.el10"), pv("kernel", "6.12.0", "55.el10")]

    def test_pending(self):
        r, reason = staleness.build_reboot(self.K, "6.12.0-50.el10.aarch64")
        self.assertEqual(
            r, {"status": "pending", "running_kernel": "6.12.0-50.el10.aarch64",
                "latest_kernel": "6.12.0-55.el10.aarch64"},
        )
        self.assertIsNone(reason)

    def test_not_pending(self):
        r, reason = staleness.build_reboot(self.K, "6.12.0-55.el10.aarch64")
        self.assertEqual(r["status"], "not_pending")
        self.assertEqual(r["latest_kernel"], "6.12.0-55.el10.aarch64")
        self.assertIsNone(reason)

    def test_numeric_release_order(self):
        k = [pv("kernel", "6.12.0", "9.el10"), pv("kernel", "6.12.0", "10.el10")]
        r, _ = staleness.build_reboot(k, "6.12.0-9.el10.aarch64")
        self.assertEqual(r["status"], "pending")
        self.assertEqual(r["latest_kernel"], "6.12.0-10.el10.aarch64")

    def test_epoch_not_in_string_but_compared(self):
        k = [pv("kernel", "7.0", "1.el10"), pv("kernel", "6.0", "1.el10", epoch="1")]
        r, _ = staleness.build_reboot(k, "7.0-1.el10.aarch64")
        self.assertEqual(r["status"], "pending")
        self.assertEqual(r["latest_kernel"], "6.0-1.el10.aarch64")

    def test_running_not_in_records(self):
        r, reason = staleness.build_reboot(self.K, "6.12.0-40.el10.aarch64")
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["latest_kernel"], "6.12.0-55.el10.aarch64")
        self.assertEqual(r["running_kernel"], "6.12.0-40.el10.aarch64")
        self.assertTrue(reason)

    def test_running_none(self):
        r, reason = staleness.build_reboot(self.K, None)
        self.assertEqual(
            r, {"status": "unknown", "running_kernel": None, "latest_kernel": None}
        )
        self.assertEqual(reason, "動いているカーネルを取得できなかった")

    def test_no_kernel(self):
        r, reason = staleness.build_reboot(
            [pv("kernel-core", "6.12.0", "55.el10")], "6.12.0-55.el10.aarch64"
        )
        self.assertEqual(r["status"], "unknown")
        self.assertIsNone(r["latest_kernel"])
        self.assertTrue(reason)

    def test_other_arch_not_compared(self):
        k = [pv("kernel", "6.12.0", "55.el10"),
             pv("kernel", "6.13.0", "1.el10", arch="x86_64")]
        r, _ = staleness.build_reboot(k, "6.12.0-55.el10.aarch64")
        self.assertEqual(r["status"], "not_pending")
        self.assertEqual(r["latest_kernel"], "6.12.0-55.el10.aarch64")

    def test_only_other_arch(self):
        k = [pv("kernel", "6.12.0", "55.el10", arch="x86_64")]
        r, reason = staleness.build_reboot(k, "6.12.0-55.el10.aarch64")
        self.assertEqual(r["status"], "unknown")
        self.assertTrue(reason)

    def test_64k_is_unknown(self):
        r, reason = staleness.build_reboot(self.K, "6.12.0-55.el10.aarch64+64k")
        self.assertEqual(r["status"], "unknown")
        self.assertIsNone(r["latest_kernel"])
        self.assertTrue(reason)


class LastUpdateTest(unittest.TestCase):
    def at(self, delta):
        return int((NOW - delta).timestamp())

    def test_ok(self):
        r = staleness.build_last_update(self.at(timedelta(days=2)), NOW)
        self.assertEqual(
            r, {"status": "ok", "at": "2026-11-20T10:00:00Z", "days_ago": 2}
        )

    def test_floor(self):
        r = staleness.build_last_update(self.at(timedelta(days=2) - timedelta(seconds=1)), NOW)
        self.assertEqual(r["days_ago"], 1)

    def test_future_is_zero(self):
        r = staleness.build_last_update(self.at(-timedelta(hours=3)), NOW)
        self.assertEqual(r["days_ago"], 0)

    def test_none(self):
        self.assertEqual(
            staleness.build_last_update(None, NOW),
            {"status": "none", "at": None, "days_ago": None},
        )

    def test_history_errors(self):
        for kind in ("not_found", "busy", "missing_columns", "no_usable_time"):
            with self.subTest(kind=kind):
                s = FakeSystem(last_upgrade=history.HistoryError(kind))
                st, problems = staleness.collect(s, [], None, NOW)
                self.assertEqual(
                    st["last_update"],
                    {"status": "unavailable", "at": None, "days_ago": None},
                )
                self.assertEqual(problems["last_update"], history.reason_text(kind))


class IndependenceTest(unittest.TestCase):
    INSTALLED = packages.parse_rpm_list(recorded.RPM_ALL_INSTALLED)

    def run_collect(self, **kw):
        return staleness.collect(
            FakeSystem(**kw), self.INSTALLED, recorded.RUNNING_KERNEL, NOW
        )

    def test_security_fails_others_ok(self):
        data = dict(recorded.SECURITY_DEFAULT)
        data[None] = CommandError("timeout")
        st, problems = self.run_collect(security=data)
        self.assertEqual(st["security_updates"]["status"], "unavailable")
        self.assertEqual(st["reboot"]["status"], "not_pending")
        self.assertEqual(st["last_update"]["status"], "ok")
        self.assertIsNone(problems["reboot"])
        self.assertIsNone(problems["last_update"])

    def test_reboot_unknown_others_ok(self):
        st, problems = staleness.collect(
            FakeSystem(), self.INSTALLED, None, NOW
        )
        self.assertEqual(st["reboot"]["status"], "unknown")
        self.assertEqual(st["security_updates"]["status"], "ok")
        self.assertEqual(st["last_update"]["status"], "ok")
        self.assertIsNone(problems["security_updates"])

    def test_last_update_fails_others_ok(self):
        st, problems = self.run_collect(last_upgrade=history.HistoryError("busy"))
        self.assertEqual(st["last_update"]["status"], "unavailable")
        self.assertEqual(st["security_updates"]["status"], "ok")
        self.assertEqual(st["reboot"]["status"], "not_pending")
        self.assertIsNone(problems["security_updates"])

    def test_key_order(self):
        st, problems = self.run_collect()
        self.assertEqual(list(st), ["security_updates", "reboot", "last_update"])
        self.assertEqual(list(problems), ["security_updates", "reboot", "last_update"])
        self.assertEqual(
            list(st["security_updates"]), ["status", "total", "by_severity", "packages"]
        )
        self.assertEqual(
            list(st["reboot"]), ["status", "running_kernel", "latest_kernel"]
        )
        self.assertEqual(list(st["last_update"]), ["status", "at", "days_ago"])


class ImportTest(unittest.TestCase):
    def test_no_forbidden_imports(self):
        import re
        with open(staleness.__file__, encoding="utf-8") as f:
            src = f.read()
        for mod in ("sqlite3", "os", "subprocess"):
            self.assertIsNone(
                re.search(rf"^\s*(import|from)\s+{mod}\b", src, re.M), mod
            )


if __name__ == "__main__":
    unittest.main()

import unittest

from tests.recorded import (
    OTHER_ROOT,
    OWN_ROOT,
    SELF_PID,
    SERVICE_CGROUP,
    make_proc,
    make_scan,
)
from tojimari import processes
from tojimari.processes import (
    apply_marks,
    build_marks,
    classify,
    is_system_service,
    parse_stat,
    strip_deleted,
)

KTHREAD = 0x00200000


def paths(scan):
    return [p for p, _ in classify(scan)[0]]


class ParseStatTest(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(parse_stat("10 (abc) S 1 10 10 0 -1 4194560 1 2 3 4\n"), ("S", 1, 4194560))

    def test_name_with_space_and_paren(self):
        text = "10 (a b) c) R 7 10 10 0 -1 2097152 1\n"
        self.assertEqual(parse_stat(text), ("R", 7, 2097152))

    def test_malformed(self):
        for text in (None, "", "10 abc S 1", "10 (abc) S 1 2", "10 (abc) S x 1 1 0 -1 0",
                     "10 (abc) S 1 1 1 0 -1 zz"):
            with self.subTest(text=text):
                self.assertIsNone(parse_stat(text))


class ClassifyKeepTest(unittest.TestCase):
    def test_normal_process(self):
        scan = make_scan(make_proc(10, exe="/usr/bin/a"))
        self.assertEqual(classify(scan), ([("/usr/bin/a", False)], 0))

    def test_same_root_other_mount_namespace(self):
        # マウントの名前空間は見ない。ルートの値が同じなら候補
        scan = make_scan(make_proc(10, exe="/usr/sbin/a", cgroup=SERVICE_CGROUP))
        self.assertEqual(classify(scan), ([("/usr/sbin/a", True)], 0))

    def test_parent_and_grandparent_of_self_are_kept(self):
        scan = make_scan(
            make_proc(100, exe="/usr/bin/sudo", ppid=50),
            make_proc(50, exe="/usr/bin/shell", ppid=1),
            make_proc(SELF_PID, exe="/usr/bin/py", ppid=100),
        )
        self.assertEqual(paths(scan), ["/usr/bin/sudo", "/usr/bin/shell"])

    def test_stat_none_kept_if_exe_readable(self):
        scan = make_scan(make_proc(10, exe="/usr/bin/a", stat=None))
        self.assertEqual(classify(scan), ([("/usr/bin/a", False)], 0))

    def test_deleted_suffix_removed(self):
        scan = make_scan(make_proc(10, exe="/usr/sbin/a (deleted)"))
        self.assertEqual(paths(scan), ["/usr/sbin/a"])


class ClassifyExcludeTest(unittest.TestCase):
    def assertExcluded(self, *procs):
        self.assertEqual(classify(make_scan(*procs)), ([], 0))

    def test_self(self):
        self.assertExcluded(make_proc(SELF_PID))

    def test_children_and_grandchildren(self):
        self.assertExcluded(
            make_proc(SELF_PID),
            make_proc(5001, ppid=SELF_PID),
            make_proc(5002, ppid=5001),
        )

    def test_kernel_thread(self):
        self.assertExcluded(make_proc(2, flags=KTHREAD, exe_error="gone", root_error="gone"))

    def test_kernel_thread_permission_without_root(self):
        self.assertExcluded(
            make_proc(2, flags=KTHREAD, exe_error="permission", root_error="permission")
        )

    def test_zombie(self):
        self.assertExcluded(make_proc(10, state="Z", exe_error="gone"))
        self.assertExcluded(make_proc(11, state="X", exe_error="permission"))

    def test_exe_gone(self):
        self.assertExcluded(make_proc(10, exe_error="gone"))

    def test_root_gone(self):
        self.assertExcluded(make_proc(10, root_error="gone"))

    def test_different_root(self):
        self.assertExcluded(
            make_proc(10, root=OTHER_ROOT),
            make_proc(11, root=(OWN_ROOT[0] + 1, OWN_ROOT[1])),
            make_proc(12, root=(OWN_ROOT[0], OWN_ROOT[1] + 1)),
        )

    def test_ppid_loop_terminates(self):
        scan = make_scan(
            make_proc(10, ppid=11, exe="/usr/bin/a"),
            make_proc(11, ppid=10, exe="/usr/bin/b"),
        )
        self.assertEqual(paths(scan), ["/usr/bin/a", "/usr/bin/b"])


class ClassifyUnreadableTest(unittest.TestCase):
    def test_exe_permission(self):
        scan = make_scan(make_proc(10, exe_error="permission"))
        self.assertEqual(classify(scan), ([], 1))

    def test_root_permission(self):
        scan = make_scan(make_proc(10, root_error="permission"))
        self.assertEqual(classify(scan), ([], 1))

    def test_both_counted_once(self):
        scan = make_scan(make_proc(10, exe_error="permission", root_error="permission"))
        self.assertEqual(classify(scan), ([], 1))

    def test_other(self):
        scan = make_scan(make_proc(10, exe_error="other"), make_proc(11, root_error="other"))
        self.assertEqual(classify(scan), ([], 2))


class IsSystemServiceTest(unittest.TestCase):
    def test_cases(self):
        cases = [
            ("0::/system.slice/example.service\n", True),
            ("0::/system.slice/example.service/child\n", True),
            ("0::/user.slice/user-1000.slice/session-3.scope\n", False),
            ("0::/user.slice/user-1000.slice/user@1000.service/app.slice/x.service\n", False),
            ("0::/system.slice/user@1000.service/app.slice/x.service\n", False),
            ("0::/init.scope\n", False),
            ("0::/system.slice/example.scope\n", False),
            ("1:name=systemd:/system.slice/a.service\n", False),
            ("", False),
            (None, False),
            ("12:cpu:/other\n1:name=systemd:/x.service\n0::/system.slice/y.service\n", True),
            ("12:cpu:/other\n0::/init.scope\n", False),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertIs(is_system_service(text), want)


class StripDeletedTest(unittest.TestCase):
    def test_strip(self):
        self.assertEqual(strip_deleted("/a/b (deleted)"), "/a/b")
        self.assertEqual(strip_deleted("/a/b (deleted) (deleted)"), "/a/b (deleted)")
        self.assertEqual(strip_deleted("/a/b"), "/a/b")


K1 = ("pkga", "0", "1.0", "1", "x86_64")
K2 = ("pkga", "0", "1.0", "1", "i686")
K3 = ("pkgb", "0", "2.0", "1", "x86_64")


def entry(name, version, release, arch, epoch=None):
    return {"name": name, "epoch": epoch, "version": version, "release": release,
            "arch": arch}


class MarksTest(unittest.TestCase):
    def test_two_versions_same_path(self):
        marks = build_marks([("/p", False)], {"/p": frozenset({K1, K2})})
        self.assertEqual(marks, {K1: False, K2: False})

    def test_service_wins(self):
        marks = build_marks([("/p", False), ("/p", True)], {"/p": frozenset({K1})})
        self.assertEqual(marks, {K1: True})
        marks = build_marks([("/p", True), ("/p", False)], {"/p": frozenset({K1})})
        self.assertEqual(marks, {K1: True})

    def test_unknown_path(self):
        self.assertEqual(build_marks([("/zzz", True)], {"/p": frozenset({K1})}), {})

    def test_unreadable_cgroup_is_running_only(self):
        scan = make_scan(make_proc(10, exe="/p", cgroup=None))
        marks = build_marks(classify(scan)[0], {"/p": frozenset({K1})})
        self.assertEqual(marks, {K1: False})

    def test_apply(self):
        focus = {"packages": [
            {"installed": [entry("pkga", "1.0", "1", "x86_64"),
                           dict(entry("kernel", "6", "1", "x86_64"), is_running_kernel=True)]},
            {"installed": []},
        ]}
        ui = {"packages": [entry("pkgb", "2.0", "1", "x86_64")]}
        apply_marks(focus, ui, {K1: True, K3: False})
        a, kernel = focus["packages"][0]["installed"]
        self.assertEqual((a["running"], a["systemd_service"]), (True, True))
        self.assertEqual((kernel["running"], kernel["systemd_service"]), (False, False))
        self.assertEqual(list(kernel)[-3:], ["is_running_kernel", "running", "systemd_service"])
        self.assertEqual((ui["packages"][0]["running"], ui["packages"][0]["systemd_service"]),
                         (True, False))

    def test_apply_epoch_zero_equals_none(self):
        ui = {"packages": [entry("pkga", "1.0", "1", "x86_64", epoch="0")]}
        apply_marks({"packages": []}, ui, {K1: False})
        self.assertIs(ui["packages"][0]["running"], True)

    def test_apply_none(self):
        focus = {"packages": [{"installed": [entry("pkga", "1.0", "1", "x86_64")]}]}
        ui = {"packages": [entry("pkgb", "2.0", "1", "x86_64")]}
        apply_marks(focus, ui, None)
        for v in (focus["packages"][0]["installed"][0], ui["packages"][0]):
            self.assertIsNone(v["running"])
            self.assertIsNone(v["systemd_service"])


class ScanErrorTest(unittest.TestCase):
    def test_is_exception(self):
        self.assertTrue(issubclass(processes.ScanError, Exception))

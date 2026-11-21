import unittest

from tests import recorded
from tojimari import packages
from tojimari.packages import PackageVersion, ParseError


class ArgvTest(unittest.TestCase):
    def test_rpm_argv(self):
        self.assertEqual(
            packages.RPM_LIST_ARGV,
            [
                "/usr/bin/rpm",
                "-qa",
                "--queryformat",
                "%{NAME}\\t%|EPOCH?{%{EPOCH}}:{}|\\t%{VERSION}\\t%{RELEASE}\\t%{ARCH}\\n",
            ],
        )

    def test_dnf_argv(self):
        names = ["kernel", "sudo"]
        self.assertEqual(
            packages.dnf_from_repo_argv(names),
            [
                "/usr/bin/dnf",
                "repoquery",
                "--installed",
                "--cacheonly",
                "--quiet",
                "--queryformat",
                "%{name}\t%{epoch}\t%{version}\t%{release}\t%{arch}\t%{from_repo}\n",
                "kernel",
                "sudo",
            ],
        )


class ParseRpmTest(unittest.TestCase):
    def test_all_installed(self):
        pkgs = packages.parse_rpm_list(recorded.RPM_ALL_INSTALLED)
        by = {}
        for p in pkgs:
            by.setdefault(p.name, []).append(p)
        self.assertIsNone(by["sudo"][0].epoch)
        self.assertEqual(by["openssl-libs"][0].epoch, "1")
        self.assertEqual(by["gpg-pubkey"][0].arch, "(none)")
        self.assertEqual(len(by["kernel"]), 2)

    def test_multi_arch(self):
        pkgs = packages.parse_rpm_list(recorded.RPM_MULTI_ARCH)
        self.assertEqual(
            sorted(p.arch for p in pkgs if p.name == "glibc"), ["i686", "x86_64"]
        )

    def test_blank_lines_skipped(self):
        pkgs = packages.parse_rpm_list("\nsudo\t\t1\t2\tx86_64\n\n")
        self.assertEqual(len(pkgs), 1)

    def test_malformed(self):
        with self.assertRaises(ParseError):
            packages.parse_rpm_list(recorded.RPM_MALFORMED)

    def test_empty(self):
        for text in ("", "\n\n"):
            with self.assertRaises(ParseError):
                packages.parse_rpm_list(text)

    def test_non_numeric_epoch(self):
        with self.assertRaises(ParseError):
            packages.parse_rpm_list("sudo\t(none)\t1\t2\tx86_64\n")

    def test_empty_required_field(self):
        with self.assertRaises(ParseError):
            packages.parse_rpm_list("sudo\t\t\t2\tx86_64\n")


class ParseDnfTest(unittest.TestCase):
    def test_all(self):
        m = packages.parse_dnf_from_repo(recorded.DNF_ALL)
        self.assertEqual(len(m), 9)
        self.assertEqual(
            m[("sudo", "0", "1.9.15", "8.p5.el10", "aarch64")], "appstream"
        )

    def test_noise_skipped(self):
        m = packages.parse_dnf_from_repo(recorded.DNF_NOISE)
        self.assertEqual(list(m.values()), ["baseos"])

    def test_empty_from_repo_is_none(self):
        m = packages.parse_dnf_from_repo(recorded.DNF_PARTIAL)
        self.assertIsNone(m[("sudo", "0", "1.9.15", "8.p5.el10", "aarch64")])

    def test_epoch_zero_matches_rpm_without_epoch(self):
        m = packages.parse_dnf_from_repo(recorded.DNF_ALL)
        pkg = PackageVersion("glibc", None, "2.39", "43.el10", "aarch64")
        key = packages.version_key(
            pkg.name, pkg.epoch, pkg.version, pkg.release, pkg.arch
        )
        self.assertIn(key, m)

    def test_empty_text(self):
        self.assertEqual(packages.parse_dnf_from_repo(""), {})


class FormatTest(unittest.TestCase):
    def test_evr(self):
        self.assertEqual(
            packages.format_evr(PackageVersion("a", None, "1.0", "2.el10", "x")),
            "1.0-2.el10",
        )
        self.assertEqual(
            packages.format_evr(PackageVersion("a", "1", "1.0", "2.el10", "x")),
            "1:1.0-2.el10",
        )

    def test_version_entry_keys(self):
        e = packages.version_entry(
            PackageVersion("a", None, "1.0", "2.el10", "x"), "baseos"
        )
        self.assertEqual(
            list(e),
            ["name", "epoch", "version", "release", "arch", "evr", "from_repo"],
        )


if __name__ == "__main__":
    unittest.main()

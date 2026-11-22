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

    def test_userinstalled_argv(self):
        argv = packages.DNF_USERINSTALLED_ARGV
        self.assertEqual(
            argv,
            [
                "/usr/bin/dnf",
                "repoquery",
                "--userinstalled",
                "--cacheonly",
                "--quiet",
                "--queryformat",
                packages.DNF_QUERYFORMAT,
            ],
        )
        self.assertTrue(argv[0].startswith("/"))


class SecurityArgvTest(unittest.TestCase):
    def test_security(self):
        argv = packages.dnf_security_upgrades_argv(None)
        self.assertEqual(
            argv,
            ["/usr/bin/dnf", "repoquery", "--upgrades", "--cacheonly", "--quiet",
             "--setopt=*.skip_if_unavailable=0", "--security",
             "--queryformat", "%{name}\n"],
        )
        self.assertTrue(argv[0].startswith("/"))
        self.assertFalse([a for a in argv if a.startswith("--sec-severity")])

    def test_severity(self):
        for sev in packages.SEVERITIES:
            with self.subTest(sev=sev):
                argv = packages.dnf_security_upgrades_argv(sev)
                self.assertIn(f"--sec-severity={sev}", argv)
                self.assertNotIn("--security", argv)
                for opt in ("--upgrades", "--cacheonly", "--quiet",
                            "--setopt=*.skip_if_unavailable=0"):
                    self.assertIn(opt, argv)
                self.assertEqual(argv[-2:], ["--queryformat", "%{name}\n"])

    def test_severities_order(self):
        self.assertEqual(
            packages.SEVERITIES, ("Critical", "Important", "Moderate", "Low")
        )

    def test_unknown_severity(self):
        for bad in ("critical", "LOW", "", "Urgent", "Low --security"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    packages.dnf_security_upgrades_argv(bad)

    def test_existing_argv_unchanged(self):
        self.assertEqual(
            packages.DNF_USERINSTALLED_ARGV[:3],
            ["/usr/bin/dnf", "repoquery", "--userinstalled"],
        )
        self.assertNotIn("--setopt=*.skip_if_unavailable=0", packages.DNF_USERINSTALLED_ARGV)


class ParseNamesTest(unittest.TestCase):
    def test_blank_lines_and_duplicates(self):
        self.assertEqual(
            packages.parse_dnf_names("git\n\ngit\nopenssl-libs\n"),
            frozenset({"git", "openssl-libs"}),
        )

    def test_empty(self):
        self.assertEqual(packages.parse_dnf_names(""), frozenset())
        self.assertEqual(packages.parse_dnf_names("\n\n"), frozenset())

    def test_names_with_symbols(self):
        self.assertEqual(
            packages.parse_dnf_names("libstdc++\npython3.12-foo_bar\n"),
            frozenset({"libstdc++", "python3.12-foo_bar"}),
        )

    def test_bad_lines(self):
        for bad in ("a b\n", "a\tb\n", "a:b\n", "-x\n", " git\n", "git \n",
                    "Last metadata expiration check: 0:01:00 ago\n", ".x\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(ParseError):
                    packages.parse_dnf_names(bad)

    def test_one_bad_line_fails_all(self):
        with self.assertRaises(ParseError):
            packages.parse_dnf_names("git\nbad name\nbash\n")


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

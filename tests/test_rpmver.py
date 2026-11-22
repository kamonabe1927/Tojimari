import unittest
from collections import namedtuple

from tojimari.rpmver import compare_evr, vercmp

EVR = namedtuple("EVR", "epoch version release")

# rpmvercmp の手順から決まる答え（設計 6.2 の表）
CASES = [
    ("1.0", "1.0", 0), ("1.0", "2.0", -1), ("2.0.1", "2.0", 1), ("9", "10", -1),
    ("5.5p1", "5.5p2", -1), ("5.5p10", "5.5p1", 1), ("10xyz", "10.1xyz", -1),
    ("xyz10", "xyz10.1", -1), ("xyz.4", "8", -1), ("6.0.rc1", "6.0", 1),
    ("10b2", "10a1", 1), ("1.0aa", "1.0a", 1), ("1.0", "1.0a", -1),
    ("1.0a", "1.0.1", -1), ("4.999.9", "5.0", -1), ("6.12.0", "6.9.0", 1),
    ("1.0~rc1", "1.0", -1), ("1.0~rc1", "1.0~rc2", -1),
    ("1.0~rc1~git123", "1.0~rc1", -1), ("1.0^", "1.0", 1), ("1.0^git1", "1.0", 1),
    ("1.0^git1", "1.0^git2", -1), ("1.0^git1", "1.01", -1),
    ("1.0^20160101", "1.0.1", -1), ("1.0~rc1^git1", "1.0~rc1", 1),
    ("1.0^git1~pre", "1.0^git1", -1), ("10.0001", "10.1", 0),
    ("10.0001", "10.0039", -1), ("2_0", "2.0", 0), ("a+", "a_", 0),
    ("+_", "_+", 0), ("8.p5.el10", "8.el10", 1),
]


class VercmpTest(unittest.TestCase):
    def test_table(self):
        for a, b, expected in CASES:
            with self.subTest(a=a, b=b):
                self.assertEqual(vercmp(a, b), expected)

    def test_swapped_reverses_sign(self):
        for a, b, expected in CASES:
            with self.subTest(a=a, b=b):
                self.assertEqual(vercmp(b, a), -expected)

    def test_not_string_order(self):
        self.assertEqual(vercmp("9.el10", "10.el10"), -1)
        self.assertGreater("9.el10", "10.el10")

    def test_non_ascii_not_alnum(self):
        # 全角の数字は英数字として扱わない（区切りとして飛ばす）
        self.assertEqual(vercmp("1２", "1"), 0)


class CompareEvrTest(unittest.TestCase):
    def test_epoch_first(self):
        self.assertEqual(compare_evr(EVR("1", "1.0", "1"), EVR(None, "2.0", "1")), 1)
        self.assertEqual(compare_evr(EVR(None, "2.0", "1"), EVR("1", "1.0", "1")), -1)

    def test_missing_epoch_is_zero(self):
        self.assertEqual(compare_evr(EVR(None, "1.0", "1"), EVR("0", "1.0", "1")), 0)
        self.assertEqual(compare_evr(EVR("", "1.0", "1"), EVR("0", "1.0", "1")), 0)

    def test_epoch_numeric(self):
        self.assertEqual(compare_evr(EVR("10", "1", "1"), EVR("9", "1", "1")), 1)

    def test_release_decides(self):
        self.assertEqual(compare_evr(EVR(None, "6.12.0", "55.el10"),
                                     EVR(None, "6.12.0", "100.el10")), -1)
        self.assertEqual(compare_evr(EVR(None, "6.12.0", "55.el10"),
                                     EVR(None, "6.12.0", "55.el10_0.1")), -1)

    def test_version_before_release(self):
        self.assertEqual(compare_evr(EVR(None, "6.13.0", "1.el10"),
                                     EVR(None, "6.12.0", "99.el10")), 1)


if __name__ == "__main__":
    unittest.main()

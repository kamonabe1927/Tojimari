import copy
import unittest

from tojimari import display


def has_control(text):
    return any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in text)


class ReplaceControlsTest(unittest.TestCase):
    def test_c0(self):
        for raw, want in [
            ("\x00", "\\x00"),
            ("\t", "\\x09"),
            ("\n", "\\x0a"),
            ("\r", "\\x0d"),
            ("\x08", "\\x08"),
            ("\x1b", "\\x1b"),
            ("\x1f", "\\x1f"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(display.replace_controls(raw), want)
                self.assertEqual(len(want), 4)

    def test_del_and_c1(self):
        for raw, want in [
            ("\x7f", "\\x7f"),
            ("\x80", "\\x80"),
            ("\x9b", "\\x9b"),
            ("\x9f", "\\x9f"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(display.replace_controls(raw), want)

    def test_boundaries_unchanged(self):
        for text in (" ", "~", "\xa0"):
            with self.subTest(text=text):
                self.assertEqual(display.replace_controls(text), text)

    def test_others_unchanged(self):
        for text in (
            "全角ＡＢＣ漢字",
            "plain-text_1.2",
            "a\\b",
            "\\x1b",
            "\u202e",
            "\u2028",
            "\u2029",
            "",
        ):
            with self.subTest(text=text):
                self.assertEqual(display.replace_controls(text), text)

    def test_mixed(self):
        self.assertEqual(
            display.replace_controls("a\x1b[31mb\r\n"), "a\\x1b[31mb\\x0d\\x0a"
        )


class ReplaceControlsDeepTest(unittest.TestCase):
    def test_nested(self):
        src = {
            "b": "x\x1b",
            "a": [1, True, None, "y\x9b", {"k": "z\n"}],
            "t": ("q\x00",),
            "n": 3,
        }
        got = display.replace_controls_deep(src)
        self.assertEqual(
            got,
            {
                "b": "x\\x1b",
                "a": [1, True, None, "y\\x9b", {"k": "z\\x0a"}],
                "t": ["q\\x00"],
                "n": 3,
            },
        )
        self.assertEqual(list(got), ["b", "a", "t", "n"])
        self.assertIs(got["a"][1], True)
        self.assertIsNone(got["a"][2])

    def test_keys_unchanged(self):
        got = display.replace_controls_deep({"k\x1b": "v\x1b"})
        self.assertEqual(got, {"k\x1b": "v\\x1b"})

    def test_input_not_modified(self):
        src = {"a": ["x\x1b", {"b": "y\r"}]}
        before = copy.deepcopy(src)
        display.replace_controls_deep(src)
        self.assertEqual(src, before)


class ReplaceAndClipTest(unittest.TestCase):
    MARK = " ...（残り {} 文字を省略）"

    def test_exact_limit(self):
        self.assertEqual(display.replace_and_clip("a" * 200), "a" * 200)

    def test_over_by_one(self):
        self.assertEqual(
            display.replace_and_clip("a" * 201), "a" * 200 + self.MARK.format(1)
        )

    def test_not_cut_inside_replacement(self):
        got = display.replace_and_clip("a" * 199 + "\x1b" + "b")
        self.assertEqual(got, "a" * 199 + self.MARK.format(5))

    def test_limit_applies_after_replacement(self):
        got = display.replace_and_clip("\x1b" * 100)
        self.assertEqual(got, "\\x1b" * 50 + self.MARK.format(200))

    def test_fullwidth_counted_by_chars(self):
        got = display.replace_and_clip("あ" * 201)
        self.assertEqual(got, "あ" * 200 + self.MARK.format(1))

    def test_custom_limit(self):
        self.assertEqual(display.replace_and_clip("abcdef", 3), "abc" + self.MARK.format(3))
        self.assertEqual(display.replace_and_clip("abc", 3), "abc")

    def test_no_controls_in_result(self):
        got = display.replace_and_clip("x\x1b\r\x08\x9b" * 80)
        self.assertFalse(has_control(got))


if __name__ == "__main__":
    unittest.main()

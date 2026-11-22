import unittest

from tojimari import notices
from tojimari.runner import CommandError


class CommandReasonTest(unittest.TestCase):
    def test_seconds_come_from_error(self):
        self.assertEqual(
            notices.command_reason("dnf", CommandError("timeout", timeout=7)),
            "dnf が 7 秒で終わらなかった",
        )

    def test_current_texts(self):
        self.assertEqual(
            notices.command_reason("dnf", CommandError("timeout", timeout=60)),
            "dnf が 60 秒で終わらなかった",
        )
        self.assertEqual(
            notices.command_reason("rpm", CommandError("timeout", timeout=30)),
            "rpm が 30 秒で終わらなかった",
        )

    def test_timeout_without_seconds(self):
        text = notices.command_reason("dnf", CommandError("timeout"))
        self.assertEqual(text, "dnf が時間内に終わらなかった")
        self.assertFalse(any(ch.isdigit() for ch in text))

    def test_other_kinds(self):
        cases = [
            (CommandError("not_found"), "dnf コマンドが見つからない"),
            (CommandError("exit_status", returncode=2), "dnf が終了コード 2 で終わった"),
            (CommandError("os_error"), "dnf を実行できなかった"),
        ]
        for err, text in cases:
            with self.subTest(kind=err.kind):
                self.assertEqual(notices.command_reason("dnf", err), text)

    def test_stderr_tail_not_included(self):
        err = CommandError("exit_status", returncode=1, stderr_tail="secret-ish text")
        self.assertNotIn("secret-ish", notices.command_reason("dnf", err))


if __name__ == "__main__":
    unittest.main()

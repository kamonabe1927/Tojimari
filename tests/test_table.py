import copy
import unittest

from tests import recorded
from tests.recorded import FakeSystem
from tojimari import check, notices, table
from tojimari.runner import CommandError


def report(**kw):
    return check.collect(FakeSystem(**kw))


def col_of(line, text):
    """行の中で text が始まる位置を表示幅で返す。"""
    return table.display_width(line[: line.index(text)])


class WidthTest(unittest.TestCase):
    def test_width(self):
        self.assertEqual(table.display_width("abc"), 3)
        self.assertEqual(table.display_width("入っている"), 10)
        self.assertEqual(table.display_width("ab入"), 4)
        self.assertEqual(table.display_width(""), 0)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.report = report()
        self.text = table.render_table(self.report)
        self.lines = self.text.split("\n")

    def test_header_and_guarantee(self):
        self.assertEqual(self.lines[0], "Tojimari check  2026-11-21 09:39 UTC")
        self.assertEqual(self.lines[1], notices.NOT_A_GUARANTEE)
        self.assertEqual(self.lines[2], "")
        self.assertEqual(self.lines[3], "[重点リスト]")
        self.assertTrue(self.text.endswith("\n"))
        self.assertFalse(self.text.endswith("\n\n"))

    def test_guarantee_not_repeated_in_notes(self):
        self.assertEqual(self.text.count(notices.NOT_A_GUARANTEE), 1)
        idx = self.lines.index("[注意]")
        self.assertNotIn(notices.NOT_A_GUARANTEE, "\n".join(self.lines[idx:]))

    def test_columns_aligned(self):
        start = self.lines.index("[重点リスト]") + 1
        rows = self.lines[start : start + 1 + 9]  # 見出し + 版の行 9 本
        header = rows[0]
        status_pos = col_of(header, "状態")
        ver_pos = col_of(header, "バージョン")
        arch_pos = col_of(header, "アーキ")
        repo_pos = col_of(header, "入れた元")
        installed = [l for l in rows[1:] if "入っている" in l]
        self.assertEqual(len(installed), 8)
        for l in installed:
            self.assertEqual(col_of(l, "入っている"), status_pos)
        for l in rows[1:]:
            if "aarch64" in l:
                self.assertEqual(col_of(l, "aarch64"), arch_pos)
        evrs = {"6.12.0-50.el10", "6.12.0-55.el10", "9.9p1-7.el10", "1:3.5.1-3.el10",
                "2.39-43.el10", "1.9.15-8.p5.el10", "257-9.el10", "126-2.el10"}
        for l in rows[1:]:
            self.assertTrue(
                any(col_of(l, e) == ver_pos for e in evrs if e in l), l
            )
        for l in rows[1:]:
            for r in ("baseos", "appstream"):
                if r in l:
                    self.assertEqual(col_of(l, r), repo_pos)

    def test_no_trailing_spaces(self):
        for l in self.lines:
            self.assertEqual(l, l.rstrip())

    def test_multi_version_rows(self):
        i = [n for n, l in enumerate(self.lines) if l.startswith("kernel ")][0]
        first, second = self.lines[i], self.lines[i + 1]
        self.assertIn("入っている", first)
        self.assertEqual(second[: second.index("6.12.0-")].strip(), "")
        self.assertEqual(col_of(second, "6.12.0-"), col_of(first, "6.12.0-"))

    def test_running_mark_only_on_running_row(self):
        marked = [l for l in self.lines if "<- 動いている" in l]
        self.assertEqual(len(marked), 1)
        self.assertIn("55.el10", marked[0])
        self.assertTrue(marked[0].endswith("baseos  <- 動いている"))

    def test_kernel_line(self):
        self.assertIn("動いているカーネル: " + recorded.RUNNING_KERNEL, self.lines)

    def test_kernel_line_none(self):
        t = table.render_table(report(kernel=None))
        self.assertIn("動いているカーネル: -", t.split("\n"))
        self.assertNotIn("<- 動いている", t)

    def test_not_installed_row(self):
        t = table.render_table(report(rpm=recorded.RPM_PARTIAL))
        line = [l for l in t.split("\n") if l.startswith("polkit")][0]
        self.assertIn("入っていない", line)
        self.assertTrue(line.endswith(" -"))
        self.assertNotIn("aarch64", line)

    def test_from_repo_null_dash(self):
        t = table.render_table(report(dnf=CommandError("not_found")))
        line = [l for l in t.split("\n") if l.startswith("sudo")][0]
        self.assertTrue(line.endswith("aarch64  -"))

    def test_notes_section(self):
        idx = self.lines.index("[注意]")
        notes = self.lines[idx + 1 : -1]
        self.assertEqual(
            notes, ["- " + notices.SCOPE, "- " + notices.RUNNING_IS_SNAPSHOT]
        )

    def test_notes_all(self):
        r = report(root=False, dnf=CommandError("not_found"), kernel=None)
        t = table.render_table(r)
        for n in r["notices"]:
            if n["id"] != "not_a_guarantee":
                self.assertIn("- " + n["message"], t)

    def test_all_report_content_present(self):
        for p in self.report["checks"]["focus_packages"]["packages"]:
            self.assertIn(p["name"], self.text)
            for v in p["installed"]:
                self.assertIn(v["evr"], self.text)
                self.assertIn(v["arch"], self.text)
                self.assertIn(v["from_repo"], self.text)

    def test_bad_format(self):
        r = copy.deepcopy(self.report)
        r["format"] = "other"
        with self.assertRaises(ValueError):
            table.render_table(r)

    def test_bad_schema(self):
        r = copy.deepcopy(self.report)
        r["schema_version"] = 2
        with self.assertRaises(ValueError):
            table.render_table(r)

    def test_no_focus_packages(self):
        r = copy.deepcopy(self.report)
        r["checks"] = {"something_new": {}}
        t = table.render_table(r)
        self.assertNotIn("[重点リスト]", t)
        self.assertNotIn("動いているカーネル", t)
        self.assertIn("[注意]", t)
        self.assertTrue(t.startswith("Tojimari check"))

    def test_unknown_keys_ignored(self):
        r = copy.deepcopy(self.report)
        r["extra"] = 1
        r["checks"]["focus_packages"]["packages"][0]["installed"][0]["new"] = True
        self.assertEqual(table.render_table(r), self.text)


class NoGuaranteeWordsTest(unittest.TestCase):
    WORDS = ["保証", "担保", "安全です", "守られています"]

    def test_words_absent(self):
        r = report(root=False, dnf=CommandError("not_found"), kernel=None)
        texts = [n["message"] for n in r["notices"]]
        texts.append(table.render_table(r))
        texts.append(table.render_table(report()))
        for t in texts:
            for w in self.WORDS:
                self.assertNotIn(w, t)


if __name__ == "__main__":
    unittest.main()

import copy
import unittest

from tests import recorded
from tests.recorded import FakeSystem, SELF_PID, SERVICE_CGROUP, make_proc, make_scan
from tojimari import check, notices, processes, table
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
            notes,
            ["- " + notices.SCOPE, "- " + notices.RUNNING_IS_SNAPSHOT,
             "- " + notices.SECURITY_UPDATES_CACHE],
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


def section(text):
    lines = text.split("\n")
    i = lines.index(next(l for l in lines if l.startswith("[後から入れたもの]")))
    end = len(lines)
    for j in range(i + 1, len(lines)):
        if lines[j] == "" or lines[j] == "[注意]":
            end = j
            break
    return lines[i:end]


def with_ui(**ui):
    r = report()
    r["checks"]["user_installed"] = ui
    return r


def entry(name, evr, arch="aarch64", from_repo="baseos"):
    return {"name": name, "epoch": None, "version": evr, "release": "1",
            "arch": arch, "evr": evr, "from_repo": from_repo}


class UserInstalledTableTest(unittest.TestCase):
    def setUp(self):
        self.report = report()
        self.text = table.render_table(self.report)
        self.lines = self.text.split("\n")

    def test_position(self):
        i = self.lines.index(next(l for l in self.lines if l.startswith("[後から入れたもの]")))
        self.assertGreater(i, self.lines.index("[重点リスト]"))
        self.assertLess(i, self.lines.index("[注意]"))
        self.assertTrue(self.lines[i - 1] == "")
        kernel = [n for n, l in enumerate(self.lines) if l.startswith("動いているカーネル")][0]
        self.assertEqual(self.lines[kernel + 1], "")
        self.assertEqual(kernel + 2, i)
        self.assertEqual(self.lines[self.lines.index("[注意]") - 1], "")

    def test_history_section(self):
        sec = section(self.text)
        self.assertEqual(sec[0], "[後から入れたもの]  dnf 履歴の 1 番の名前を除いた 4 件")
        self.assertEqual(
            [l.split() for l in sec[1:]],
            [["パッケージ", "バージョン", "アーキ", "入れた元"],
             ["gh", "2.65.0-1", "aarch64", "gh-cli"],
             ["git", "2.47.1-1.el10", "aarch64", "appstream"],
             ["htop", "3.3.0-5.el10", "aarch64", "epel"],
             ["openssl", "1:3.5.1-3.el10", "aarch64", "appstream"]],
        )

    def test_columns_aligned(self):
        sec = section(self.text)
        for word in ("バージョン", "アーキ", "入れた元"):
            pos = col_of(sec[1], word)
            self.assertGreater(pos, 0)
        self.assertEqual(col_of(sec[2], "2.65.0-1"), col_of(sec[1], "バージョン"))
        self.assertEqual(col_of(sec[2], "aarch64"), col_of(sec[1], "アーキ"))
        self.assertEqual(col_of(sec[2], "gh-cli"), col_of(sec[1], "入れた元"))
        for l in sec:
            self.assertEqual(l, l.rstrip())

    def test_fallback_heading(self):
        r = report(history=recorded_error())
        self.assertEqual(
            section(table.render_table(r))[0],
            "[後から入れたもの]  入れた元が anaconda のものを除いた 5 件（代わりの判定）",
        )

    def test_unknown_method_heading(self):
        r = with_ui(status="ok", method="zzz", packages=[entry("a", "1")])
        self.assertEqual(section(table.render_table(r))[0], "[後から入れたもの]  1 件")

    def test_multiple_versions(self):
        r = with_ui(status="ok", method="history",
                    packages=[entry("a", "1.0"), entry("a", "2.0"), entry("b", "1.0")])
        sec = section(table.render_table(r))
        self.assertEqual(sec[0], "[後から入れたもの]  dnf 履歴の 1 番の名前を除いた 2 件")
        self.assertTrue(sec[2].startswith("a "))
        self.assertEqual(sec[3][: sec[3].index("2.0")].strip(), "")
        self.assertTrue(sec[4].startswith("b "))

    def test_null_from_repo(self):
        r = with_ui(status="ok", method="history",
                    packages=[entry("a", "1.0", from_repo=None)])
        sec = section(table.render_table(r))
        self.assertTrue(sec[2].endswith("aarch64  -"))

    def test_zero(self):
        r = with_ui(status="ok", method="history", packages=[])
        self.assertEqual(
            section(table.render_table(r)),
            ["[後から入れたもの]  dnf 履歴の 1 番の名前を除いた 0 件", "該当なし"],
        )

    def test_unavailable_and_unknown_status(self):
        for st in ("unavailable", "zzz"):
            with self.subTest(status=st):
                r = with_ui(status=st, method=None, packages=[entry("a", "1.0")])
                self.assertEqual(
                    section(table.render_table(r)),
                    ["[後から入れたもの]", "確認できませんでした"],
                )

    def test_missing_key(self):
        r = copy.deepcopy(self.report)
        del r["checks"]["user_installed"]
        t = table.render_table(r)
        self.assertNotIn("[後から入れたもの]", t)
        self.assertIn("[注意]", t)

    def test_all_content_present(self):
        for p in self.report["checks"]["user_installed"]["packages"]:
            for k in ("name", "evr", "arch", "from_repo"):
                self.assertIn(p[k], self.text)

    def test_focus_section_unchanged(self):
        r = copy.deepcopy(self.report)
        del r["checks"]["user_installed"]
        del r["checks"]["staleness"]
        old = table.render_table(r)
        a = old.split("[注意]")[0].rstrip("\n")
        self.assertTrue(self.text.startswith(a))


def recorded_error():
    from tojimari.history import HistoryError
    return HistoryError("not_found")


def stale_section(text):
    lines = text.split("\n")
    i = lines.index("[古さ]")
    end = len(lines)
    for j in range(i + 1, len(lines)):
        if lines[j] == "":
            end = j
            break
    return lines[i:end]


def stale_report(**parts):
    r = report()
    r["checks"]["staleness"] = {
        "security_updates": {
            "status": "ok", "total": 2,
            "by_severity": {"critical": 0, "important": 1, "moderate": 1,
                            "low": 0, "unspecified": 0},
            "packages": [{"name": "openssl-libs", "severity": "important"},
                         {"name": "vim-enhanced", "severity": "moderate"}],
        },
        "reboot": {"status": "pending",
                   "running_kernel": "6.12.0-50.el10.aarch64",
                   "latest_kernel": "6.12.0-55.el10.aarch64"},
        "last_update": {"status": "ok", "at": "2026-11-20T10:00:00Z", "days_ago": 2},
    }
    r["checks"]["staleness"].update(parts)
    return r


class StalenessTableTest(unittest.TestCase):
    def test_example_from_spec(self):
        text = table.render_table(stale_report())
        self.assertEqual(
            stale_section(text),
            [
                "[古さ]",
                "セキュリティ更新    2 件（Critical 0、Important 1、Moderate 1、Low 0、重要度なし 0）",
                "  openssl-libs      Important",
                "  vim-enhanced      Moderate",
                "再起動待ち          再起動待ち（動いている 6.12.0-50.el10.aarch64、入っている最新 6.12.0-55.el10.aarch64）",
                "最後に更新した日    2026-11-20 10:00 UTC（2 日前）",
            ],
        )

    def test_position(self):
        lines = table.render_table(report()).split("\n")
        i = lines.index("[古さ]")
        ui = next(n for n, l in enumerate(lines) if l.startswith("[後から入れたもの]"))
        self.assertGreater(i, ui)
        self.assertLess(i, lines.index("[注意]"))
        self.assertEqual(lines[i - 1], "")
        self.assertEqual(lines[lines.index("[注意]") - 1], "")

    def test_default_report_content(self):
        sec = stale_section(table.render_table(report()))
        self.assertIn("3 件（Critical 0、Important 1、Moderate 1、Low 0、重要度なし 1）", sec[1])
        self.assertEqual([l.split()[0] for l in sec[2:5]], ["openssl-libs", "git", "bash"])
        self.assertTrue(sec[2].endswith("Important"))
        self.assertTrue(sec[4].endswith("重要度なし"))
        self.assertIn("再起動待ちではない（動いている 6.12.0-55.el10.aarch64、入っている最新 6.12.0-55.el10.aarch64）", sec[5])
        self.assertTrue(sec[6].endswith("2026-11-20 10:00 UTC（0 日前）"))

    def test_no_trailing_spaces_and_aligned(self):
        text = table.render_table(
            stale_report(security_updates={
                "status": "ok", "total": 1,
                "by_severity": {"critical": 0, "important": 0, "moderate": 0,
                                "low": 1, "unspecified": 0},
                "packages": [{"name": "a-very-long-package-name-for-width", "severity": "low"}],
            })
        )
        sec = stale_section(text)
        for line in sec:
            self.assertEqual(line, line.rstrip())
        cols = {table.display_width(l[: l.index(v)]) for l, v in
                ((sec[1], "1 件"), (sec[2], "Low"), (sec[3], "再起動待ち（"),
                 (sec[4], "2026-"))}
        self.assertEqual(len(cols), 1)
        self.assertGreaterEqual(cols.pop(), len("  a-very-long-package-name-for-width") + 4)

    def test_zero(self):
        sec = stale_section(table.render_table(stale_report(security_updates={
            "status": "ok", "total": 0,
            "by_severity": {k: 0 for k in ("critical", "important", "moderate", "low", "unspecified")},
            "packages": []})))
        self.assertEqual(sec[1], "セキュリティ更新    0 件")
        self.assertEqual(len(sec), 4)

    def test_unavailable(self):
        text = table.render_table(stale_report(
            security_updates={"status": "unavailable", "total": None,
                              "by_severity": None, "packages": []},
            last_update={"status": "unavailable", "at": None, "days_ago": None},
        ))
        sec = stale_section(text)
        self.assertEqual(sec[1], "セキュリティ更新    確認できませんでした")
        self.assertEqual(sec[3], "最後に更新した日    確認できませんでした")
        self.assertNotIn("0 件", "\n".join(sec))
        self.assertNotIn("更新なし", "\n".join(sec))

    def test_unknown_status_values(self):
        sec = stale_section(table.render_table(stale_report(
            security_updates={"status": "zzz", "total": 5, "by_severity": {}, "packages": [{"name": "x", "severity": "low"}]},
            reboot={"status": "zzz", "running_kernel": None, "latest_kernel": None},
            last_update={"status": "zzz", "at": None, "days_ago": None},
        )))
        self.assertEqual(sec[1], "セキュリティ更新    確認できませんでした")
        self.assertEqual(sec[2], "再起動待ち          確認できませんでした（動いている -、入っている最新 -）")
        self.assertEqual(sec[3], "最後に更新した日    確認できませんでした")

    def test_reboot_states(self):
        for status, label in (("not_pending", "再起動待ちではない"), ("unknown", "確認できませんでした")):
            with self.subTest(status=status):
                sec = stale_section(table.render_table(stale_report(
                    reboot={"status": status, "running_kernel": "k1", "latest_kernel": None})))
                self.assertIn(f"{label}（動いている k1、入っている最新 -）", sec[4])

    def test_last_update_none(self):
        sec = stale_section(table.render_table(stale_report(
            last_update={"status": "none", "at": None, "days_ago": None})))
        self.assertEqual(sec[-1], "最後に更新した日    更新の記録がありません")

    def test_unknown_severity_shown_as_is(self):
        sec = stale_section(table.render_table(stale_report(security_updates={
            "status": "ok", "total": 1,
            "by_severity": {"critical": 0, "important": 0, "moderate": 0, "low": 0, "unspecified": 0},
            "packages": [{"name": "x", "severity": "weird"}]})))
        self.assertTrue(sec[2].endswith("weird"))

    def test_missing_staleness_prints_nothing(self):
        r = report()
        del r["checks"]["staleness"]
        text = table.render_table(r)
        self.assertNotIn("[古さ]", text)
        self.assertIn("[注意]", text)

    def test_missing_items_skipped(self):
        r = report()
        r["checks"]["staleness"] = {"reboot": r["checks"]["staleness"]["reboot"]}
        sec = stale_section(table.render_table(r))
        self.assertEqual(len(sec), 2)
        self.assertTrue(sec[1].startswith("再起動待ち"))

    def test_only_report_content(self):
        r = stale_report()
        r["checks"]["staleness"]["security_updates"]["total"] = 9  # 数え直さない
        self.assertIn("9 件（", table.render_table(r))

    def test_existing_parts_unchanged(self):
        r = report()
        del r["checks"]["staleness"]
        old = table.render_table(r)
        new = table.render_table(report())
        self.assertTrue(new.startswith(old.split("[注意]")[0].rstrip("\n")))


class NoGuaranteeWordsTest(unittest.TestCase):
    WORDS = ["保証", "担保", "安全です", "守られています"]

    def test_words_absent(self):
        r = report(root=False, dnf=CommandError("not_found"), kernel=None)
        texts = [n["message"] for n in r["notices"]]
        r2 = report(history=recorded_error(), userinstalled=CommandError("timeout", timeout=60))
        texts += [n["message"] for n in r2["notices"]]
        texts.append(table.render_table(r2))
        texts.append(table.render_table(r))
        texts.append(table.render_table(report()))
        r3 = report(security={None: CommandError("timeout", timeout=60)}, kernel=None,
                    last_upgrade=recorded_error())
        texts += [n["message"] for n in r3["notices"]]
        texts.append(table.render_table(r3))
        for t in texts:
            for w in self.WORDS:
                self.assertNotIn(w, t)


class ControlReplaceTest(unittest.TestCase):
    NOISE = "\x1b[31m\n\r\t\x08\x7f\x9b"

    def noisy_report(self):
        r = copy.deepcopy(report())
        n = self.NOISE
        kernel = r["checks"]["focus_packages"]["packages"][0]["installed"][1]
        kernel["evr"] += n
        kernel["arch"] += n
        kernel["from_repo"] += n
        sshd = r["checks"]["focus_packages"]["packages"][1]["installed"][0]
        sshd["evr"] += n
        r["system"]["running_kernel"] += n
        for v in r["checks"]["user_installed"]["packages"][:2]:
            v["name"] += n
            v["evr"] += n
            v["arch"] += n
            v["from_repo"] += n
        stale = r["checks"]["staleness"]
        stale["security_updates"]["packages"][0]["name"] += n
        stale["security_updates"]["packages"][0]["severity"] = "odd" + n
        stale["reboot"] = {
            "status": "pending",
            "running_kernel": "6.12.0-50.el10.aarch64" + n,
            "latest_kernel": "6.12.0-55.el10.aarch64" + n,
        }
        r["notices"][1]["message"] += n
        return r

    @staticmethod
    def bad_chars(text):
        return [
            c for c in text if c != "\n" and (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F)
        ]

    def test_no_control_chars(self):
        out = table.render_table(self.noisy_report())
        self.assertEqual(self.bad_chars(out), [])
        self.assertIn("\\x1b[31m", out)
        self.assertIn("\\x0a", out)
        self.assertIn("\\x9b", out)

    def test_line_count_unchanged(self):
        plain = table.render_table(report())
        noisy = table.render_table(self.noisy_report())
        self.assertEqual(len(noisy.split("\n")), len(plain.split("\n")))

    def test_kernel_line_has_replaced_form(self):
        out = table.render_table(self.noisy_report())
        line = [l for l in out.split("\n") if l.startswith("動いているカーネル")][0]
        self.assertIn("\\x1b[31m", line)

    def test_columns_aligned(self):
        lines = table.render_table(self.noisy_report()).split("\n")
        for title, first in (("[重点リスト]", "パッケージ"), ("[後から入れたもの]", "パッケージ")):
            start = next(i for i, l in enumerate(lines) if l.startswith(title)) + 1
            header = lines[start]
            want = table.display_width(header[: header.index("アーキ")])
            rows = []
            for l in lines[start + 1 :]:
                if l == "" or l.startswith("動いているカーネル"):
                    break
                rows.append(l)
            self.assertTrue(rows)
            for l in rows:
                if "aarch64" not in l:
                    continue
                self.assertEqual(table.display_width(l[: l.index("aarch64")]), want, l)
        self.assertTrue(any("\\x" in l and "aarch64\\x1b" in l for l in lines))

    def test_input_not_modified(self):
        r = self.noisy_report()
        before = copy.deepcopy(r)
        table.render_table(r)
        self.assertEqual(r, before)


if __name__ == "__main__":
    unittest.main()


def running_report(**kw):
    procs = [
        make_proc(10, exe="/usr/sbin/sshd", cgroup=SERVICE_CGROUP),
        make_proc(11, exe="/usr/bin/htop"),
        make_proc(100, exe="/usr/bin/sudo", ppid=50),
        make_proc(SELF_PID, exe="/usr/bin/git", ppid=100),
        make_proc(200, exe="/usr/bin/sudo", ppid=1),
    ]
    return report(processes=make_scan(*procs), **kw)


def line_of(text, name):
    return [l for l in text.split("\n") if l.startswith(name + " ")][0]


class RunningMarkTest(unittest.TestCase):
    def setUp(self):
        self.text = table.render_table(running_report())

    def test_service_mark(self):
        self.assertTrue(line_of(self.text, "openssh-server").endswith(
            "baseos  <- 今動いている（systemd のサービス）"))

    def test_running_only_mark_in_focus(self):
        self.assertTrue(line_of(self.text, "sudo").endswith("appstream  <- 今動いている"))

    def test_launching_sudo_alone_has_no_mark(self):
        procs = [
            make_proc(100, exe="/usr/bin/sudo", ppid=50),
            make_proc(SELF_PID, exe="/usr/bin/git", ppid=100),
        ]
        text = table.render_table(report(processes=make_scan(*procs)))
        self.assertNotIn("<- 今動いている", line_of(text, "sudo"))

    def test_user_installed_marks(self):
        self.assertTrue(line_of(self.text, "htop").endswith("epel  <- 今動いている"))
        self.assertNotIn("<- 今動いている", line_of(self.text, "git"))
        self.assertNotIn("<- 今動いている", line_of(self.text, "gh"))

    def test_kernel_mark_unchanged(self):
        marked = [l for l in self.text.split("\n") if "<- 動いている" in l]
        self.assertEqual(len(marked), 1)

    def test_no_marks_for_default(self):
        t = table.render_table(report())
        self.assertNotIn("<- 今動いている", t)

    def test_unavailable_has_no_marks(self):
        r = report(processes=processes.ScanError("x"))
        t = table.render_table(r)
        self.assertNotIn("<- 今動いている", t)
        self.assertIn("- " + [n for n in r["notices"] if n["id"] == "running_unavailable"][0]["message"], t)

    def test_partial_notice_shown(self):
        r = report(processes=make_scan(make_proc(10, exe_error="permission")))
        t = table.render_table(r)
        msg = [n for n in r["notices"] if n["id"] == "running_partial"][0]["message"]
        self.assertIn("- " + msg, t)

    def test_matches_json(self):
        r = running_report()
        t = table.render_table(r)
        for p in r["checks"]["focus_packages"]["packages"]:
            for v in p["installed"]:
                line_marked = "<- 今動いている" in [l for l in t.split("\n") if l.startswith(p["name"] + " ")][0]
                self.assertEqual(line_marked, bool(v["running"]))

    def test_both_marks_kernel_first(self):
        r = running_report()
        v = r["checks"]["focus_packages"]["packages"][0]["installed"][1]
        self.assertTrue(v["is_running_kernel"])
        v["running"] = True
        t = table.render_table(r)
        line = [l for l in t.split("\n") if "<- 動いている" in l][0]
        self.assertTrue(line.endswith("<- 動いている  <- 今動いている"))

    def test_old_json_without_running_keys(self):
        r = running_report()
        for p in r["checks"]["focus_packages"]["packages"]:
            for v in p["installed"]:
                v.pop("running"), v.pop("systemd_service")
        for v in r["checks"]["user_installed"]["packages"]:
            v.pop("running"), v.pop("systemd_service")
        del r["checks"]["running_processes"]
        t = table.render_table(r)
        self.assertNotIn("<- 今動いている", t)
        self.assertIn("[後から入れたもの]", t)

    def test_no_paths_or_pids(self):
        t = table.render_table(running_report())
        for word in ("/usr/sbin", "/usr/bin", "4000", "system.slice", "example.service"):
            self.assertNotIn(word, t)

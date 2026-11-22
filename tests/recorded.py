"""記録出力（テスト用データ）と、差し替え用の実行部。値はすべて架空。"""

import sqlite3
from datetime import datetime, timezone

RUNNING_KERNEL = "6.12.0-55.el10.aarch64"

RPM_ALL_INSTALLED = (
    "kernel\t\t6.12.0\t50.el10\taarch64\n"
    + "kernel\t\t6.12.0\t55.el10\taarch64\n"
    + "kernel-core\t\t6.12.0\t55.el10\taarch64\n"
    + "openssh-server\t\t9.9p1\t7.el10\taarch64\n"
    + "openssh\t\t9.9p1\t7.el10\taarch64\n"
    + "openssl-libs\t1\t3.5.1\t3.el10\taarch64\n"
    + "glibc\t\t2.39\t43.el10\taarch64\n"
    + "sudo\t\t1.9.15\t8.p5.el10\taarch64\n"
    + "systemd\t\t257\t9.el10\taarch64\n"
    + "polkit\t\t126\t2.el10\taarch64\n"
    + "bash\t\t5.2.26\t6.el10\taarch64\n"
    + "gpg-pubkey\t\t5b6c7d8e\t60a1b2c3\t(none)\n"
    + "kernel-core\t\t6.12.0\t50.el10\taarch64\n"
    + "git\t\t2.47.1\t1.el10\taarch64\n"
    + "htop\t\t3.3.0\t5.el10\taarch64\n"
    + "gh\t\t2.65.0\t1\taarch64\n"
    + "openssl\t1\t3.5.1\t3.el10\taarch64\n"
)

RPM_PARTIAL = "".join(
    line + "\n"
    for line in RPM_ALL_INSTALLED.split("\n")
    if line and not line.startswith(("polkit\t", "openssh-server\t"))
)

RPM_MULTI_ARCH = (
    "glibc\t\t2.39\t43.el10\tx86_64\n"
    "glibc\t\t2.39\t43.el10\ti686\n"
    "sudo\t\t1.9.15\t8.p5.el10\tx86_64\n"
)

RPM_MALFORMED = (
    "sudo\t\t1.9.15\t8.p5.el10\taarch64\n"
    "glibc\t2.39\t43.el10\n"
)

DNF_ALL = (
    "kernel\t0\t6.12.0\t50.el10\taarch64\tbaseos\n"
    "\n"
    "kernel\t0\t6.12.0\t55.el10\taarch64\tbaseos\n"
    "\n"
    "openssh-server\t0\t9.9p1\t7.el10\taarch64\tbaseos\n"
    "\n"
    "openssh\t0\t9.9p1\t7.el10\taarch64\tbaseos\n"
    "\n"
    "openssl-libs\t1\t3.5.1\t3.el10\taarch64\tbaseos\n"
    "\n"
    "glibc\t0\t2.39\t43.el10\taarch64\tbaseos\n"
    "\n"
    "sudo\t0\t1.9.15\t8.p5.el10\taarch64\tappstream\n"
    "\n"
    "systemd\t0\t257\t9.el10\taarch64\tbaseos\n"
    "\n"
    "polkit\t0\t126\t2.el10\taarch64\tbaseos\n"
    "\n"
)

# kernel 55 の行が無く、sudo の from_repo が空
DNF_PARTIAL = (
    "kernel\t0\t6.12.0\t50.el10\taarch64\tbaseos\n"
    "openssl-libs\t1\t3.5.1\t3.el10\taarch64\tbaseos\n"
    "sudo\t0\t1.9.15\t8.p5.el10\taarch64\t\n"
)

DNF_NOISE = (
    "Last metadata expiration check\n"
    "sudo\t0\t1.9.15\t8.p5.el10\taarch64\tbaseos\n"
    "a\tb\n"
)


# dnf repoquery --userinstalled の記録出力（架空）。kernel は 2 つの版、
# bash はインストール後に更新された OS 標準（入れた元が baseos）
DNF_USERINSTALLED = (
    "kernel\t0\t6.12.0\t50.el10\taarch64\tanaconda\n"
    "kernel\t0\t6.12.0\t55.el10\taarch64\tbaseos\n"
    "kernel-core\t0\t6.12.0\t50.el10\taarch64\tanaconda\n"
    "bash\t0\t5.2.26\t6.el10\taarch64\tbaseos\n"
    "sudo\t0\t1.9.15\t8.p5.el10\taarch64\tanaconda\n"
    "git\t0\t2.47.1\t1.el10\taarch64\tappstream\n"
    "htop\t0\t3.3.0\t5.el10\taarch64\tepel\n"
    "gh\t0\t2.65.0\t1\taarch64\tgh-cli\n"
    "openssl\t1\t3.5.1\t3.el10\taarch64\tappstream\n"
)

# 履歴の 1 番の名前（架空）
HISTORY_FIRST_NAMES = frozenset({"kernel", "kernel-core", "bash", "sudo"})


def make_history_db(conn, transactions):
    """履歴のデータベースの形（trans、trans_item、rpm、item）を作る。
    transactions は {処理の id: [パッケージ名, ...]}。型は書かない。値はすべて架空。"""
    conn.execute(
        "CREATE TABLE trans (id, dt_begin, dt_end, rpmdb_version_begin, "
        "rpmdb_version_end, releasever, user_id, cmdline, state, comment)"
    )
    conn.execute("CREATE TABLE item (id, item_type)")
    conn.execute("CREATE TABLE rpm (item_id, name, epoch, version, release, arch)")
    conn.execute(
        "CREATE TABLE trans_item (id, trans_id, item_id, repoid, action, reason, state)"
    )
    item_id = 0
    row_id = 0
    for trans_id, names in transactions.items():
        conn.execute(
            "INSERT INTO trans VALUES (?, 0, 0, '', '', '', 0, '', 0, '')", (trans_id,)
        )
        for name in names:
            item_id += 1
            row_id += 1
            conn.execute("INSERT INTO item VALUES (?, 0)", (item_id,))
            conn.execute(
                "INSERT INTO rpm VALUES (?, ?, 0, '1', '1', 'x')", (item_id, name)
            )
            conn.execute(
                "INSERT INTO trans_item VALUES (?, ?, ?, '', 0, 0, 0)",
                (row_id, trans_id, item_id),
            )
    conn.commit()


def memory_history_db(transactions):
    conn = sqlite3.connect(":memory:")
    make_history_db(conn, transactions)
    return conn


class FakeSystem:
    """返す値か投げる例外を受け取る。値が例外なら投げる。"""

    def __init__(
        self,
        rpm=RPM_ALL_INSTALLED,
        dnf=DNF_ALL,
        kernel=RUNNING_KERNEL,
        root=True,
        now=None,
        userinstalled=DNF_USERINSTALLED,
        history=HISTORY_FIRST_NAMES,
    ):
        self._rpm = rpm
        self._dnf = dnf
        self._kernel = kernel
        self._root = root
        self._now = now or datetime(2026, 11, 21, 9, 39, 12, tzinfo=timezone.utc)
        self._userinstalled = userinstalled
        self._history = history
        self.dnf_names = None
        self.history_called = False

    @staticmethod
    def _give(value):
        if isinstance(value, Exception):
            raise value
        return value

    def rpm_list(self):
        return self._give(self._rpm)

    def dnf_from_repo(self, names):
        self.dnf_names = list(names)
        return self._give(self._dnf)

    def dnf_userinstalled(self):
        return self._give(self._userinstalled)

    def history_first_names(self):
        self.history_called = True
        return self._give(self._history)

    def running_kernel(self):
        return self._kernel

    def is_root(self):
        return self._root

    def now(self):
        return self._now

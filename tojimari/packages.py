"""読み取り部。rpm と dnf の問い合わせの形と、その出力の読み取り。何も実行しない。"""

import re
from dataclasses import dataclass

RPM_LIST_ARGV = [
    "/usr/bin/rpm",
    "-qa",
    "--queryformat",
    "%{NAME}\\t%|EPOCH?{%{EPOCH}}:{}|\\t%{VERSION}\\t%{RELEASE}\\t%{ARCH}\\n",
]

DNF_QUERYFORMAT = (
    "%{name}\t%{epoch}\t%{version}\t%{release}\t%{arch}\t%{from_repo}\n"
)


def _dnf_repoquery_argv(selector: str) -> list[str]:
    return [
        "/usr/bin/dnf",
        "repoquery",
        selector,
        "--cacheonly",
        "--quiet",
        "--queryformat",
        DNF_QUERYFORMAT,
    ]


DNF_USERINSTALLED_ARGV = _dnf_repoquery_argv("--userinstalled")


def dnf_from_repo_argv(names: list[str]) -> list[str]:
    return [*_dnf_repoquery_argv("--installed"), *names]


SEVERITIES = ("Critical", "Important", "Moderate", "Low")  # dnf に渡す書き方。重い順

_NAME_QUERYFORMAT = "%{name}\n"
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


def dnf_security_upgrades_argv(severity: str | None) -> list[str]:
    """None なら --security、SEVERITIES の値なら --sec-severity=<値>。それ以外は ValueError。
    --security と --sec-severity は同じ呼び出しに入れない。"""
    if severity is None:
        selector = "--security"
    elif severity in SEVERITIES:
        selector = f"--sec-severity={severity}"
    else:
        raise ValueError("知らない重要度")
    return [
        "/usr/bin/dnf",
        "repoquery",
        "--upgrades",
        "--cacheonly",
        "--quiet",
        "--setopt=*.skip_if_unavailable=0",
        selector,
        "--queryformat",
        _NAME_QUERYFORMAT,
    ]


class ParseError(Exception):
    """rpm の出力が決めた形でない。"""


@dataclass(frozen=True)
class PackageVersion:
    name: str
    epoch: str | None
    version: str
    release: str
    arch: str


def parse_rpm_list(text: str) -> list[PackageVersion]:
    result = []
    for line in text.split("\n"):
        if line.strip() == "":
            continue
        fields = line.split("\t")
        if len(fields) != 5:
            raise ParseError("項目の数が違う行がある")
        name, epoch, version, release, arch = fields
        if not name or not version or not release:
            raise ParseError("名前・version・release が空の行がある")
        if epoch != "" and not (epoch.isascii() and epoch.isdigit()):
            raise ParseError("epoch が数字でない行がある")
        result.append(
            PackageVersion(name, epoch if epoch != "" else None, version, release, arch)
        )
    if not result:
        raise ParseError("1 行も読めなかった")
    return result


def version_key(name, epoch, version, release, arch) -> tuple:
    return (name, epoch if epoch else "0", version, release, arch)


def parse_dnf_from_repo(text: str) -> dict[tuple, str | None]:
    result: dict[tuple, str | None] = {}
    for line in text.split("\n"):
        if line.strip() == "":
            continue
        fields = line.split("\t")
        if len(fields) != 6:
            continue
        name, epoch, version, release, arch, from_repo = fields
        result[version_key(name, epoch, version, release, arch)] = (
            from_repo if from_repo != "" else None
        )
    return result


def format_evr(pkg: PackageVersion) -> str:
    base = f"{pkg.version}-{pkg.release}"
    if pkg.epoch:
        return f"{pkg.epoch}:{base}"
    return base


def version_entry(pkg: PackageVersion, from_repo: str | None) -> dict:
    return {
        "name": pkg.name,
        "epoch": pkg.epoch,
        "version": pkg.version,
        "release": pkg.release,
        "arch": pkg.arch,
        "evr": format_evr(pkg),
        "from_repo": from_repo,
    }


def parse_dnf_names(text: str) -> frozenset[str]:
    """空行を飛ばし、名前の集まりを返す。名前の形でない行があれば ParseError。
    0 行（空の出力）は空の集まり。"""
    names = set()
    for line in text.split("\n"):
        if line == "":
            continue
        if _NAME_RE.fullmatch(line) is None:
            raise ParseError("名前の形でない行がある")
        names.add(line)
    return frozenset(names)

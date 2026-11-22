"""表示の注意の文言と、出す条件。"""

NOT_A_GUARANTEE = "この表示は確認の補助であり、安全であることを示すものではありません。"
SCOPE = (
    "表示対象は dnf（rpm）で入れたものと重点リストだけです。"
    "パッケージ管理の外で個別にビルド・配置したもの、"
    "pip などの言語ごとのパッケージ管理で入れたもの、"
    "Docker コンテナの中身は表示しません。"
    "表示されないことを「入っていない」と扱わないでください。"
)
RUNNING_IS_SNAPSHOT = (
    "「今動いている」はその瞬間の様子です。"
    "印がないことを「使っていない」と扱わないでください。"
    "Docker コンテナの中で動いているものには印を付けません。"
    "印は実行ファイルのパスで付けるため、"
    "更新した後に再起動していないプロセスは、新しい版の印として出ます。"
)
NOT_ROOT = (
    "root なしで実行したため、見えた範囲だけを表示しています。"
    "sudo を付けて実行することを勧めます。"
)
FROM_REPO_UNAVAILABLE = (
    "入れた元のリポジトリを取得できませんでした（理由: {reason}）。"
    "入れた元は表示していません。"
)
RUNNING_KERNEL_NOT_FOUND = (
    "動いているカーネルが、rpm の記録にある kernel の版の中に見つかりませんでした。"
)
HISTORY_FALLBACK = (
    "dnf 履歴を読み取れなかったため（理由: {reason}）、"
    "入れた元のリポジトリが anaconda かどうかによる代わりの判定を使いました。"
    "精度が落ちており、インストール後に更新した OS 標準のパッケージが"
    "「後から入れたもの」に混ざることがあります。"
)
USER_INSTALLED_UNAVAILABLE = (
    "後から入れたものの一覧を取得できなかったため、確認できませんでした（理由: {reason}）。"
    "「後から入れたものは無い」という意味ではありません。"
)
SECURITY_UPDATES_CACHE = (
    "セキュリティ更新の数は、dnf が手元に持っているリポジトリ情報"
    "（最後に取得した時点のもの）にもとづいており、最新とは限りません。"
    "Tojimari はリポジトリ情報を取り直しません。"
    "最新にするには、先に sudo dnf makecache を実行してください。"
)
SECURITY_UPDATES_UNAVAILABLE = (
    "リポジトリ情報を確認できなかったため（理由: {reason}）、"
    "セキュリティ更新があるかどうかは分かりません。"
    "「更新なし」という意味ではありません。"
    "dnf が手元にリポジトリ情報を持っていないときは、"
    "sudo dnf makecache を実行した後に確かめ直せます。"
)
REBOOT_UNKNOWN = (
    "再起動待ちかどうかを確認できませんでした（理由: {reason}）。"
    "「再起動待ちではない」という意味ではありません。"
)
LAST_UPDATE_UNAVAILABLE = (
    "dnf 履歴から最後に更新した日を確認できませんでした（理由: {reason}）。"
)
RUNNING_UNAVAILABLE = (
    "動いているプロセスを確認できなかったため（理由: {reason}）、"
    "今動いているかの印を付けていません。"
    "「どれも動いていない」という意味ではありません。"
)
RUNNING_PARTIAL = (
    "{count} 個のプロセスは、権限が無くて実行ファイルかルートディレクトリを"
    "読めなかったため、印のもとにしていません。"
    "印の無い版の中にも、動いているものがありえます。"
)


def command_reason(tool: str, timeout: int, err) -> str:
    """外部コマンドの失敗を、注意に入れる理由の文にする。標準エラー出力は入れない。"""
    if err.kind == "not_found":
        return f"{tool} コマンドが見つからない"
    if err.kind == "timeout":
        return f"{tool} が {timeout} 秒で終わらなかった"
    if err.kind == "exit_status":
        return f"{tool} が終了コード {err.returncode} で終わった"
    return f"{tool} を実行できなかった"


def build_notices(
    is_root: bool,
    from_repo_problem: str | None,
    running_kernel_found: bool,
    history_problem: str | None = None,
    user_installed_problem: str | None = None,
    security_updates_ok: bool = False,
    security_updates_problem: str | None = None,
    reboot_problem: str | None = None,
    last_update_problem: str | None = None,
    running_problem: str | None = None,
    running_unreadable: int = 0,
) -> list[dict]:
    notices = [
        {"id": "not_a_guarantee", "message": NOT_A_GUARANTEE},
        {"id": "scope", "message": SCOPE},
        {"id": "running_is_snapshot", "message": RUNNING_IS_SNAPSHOT},
    ]
    if not is_root:
        notices.append({"id": "not_root", "message": NOT_ROOT})
    if from_repo_problem is not None:
        notices.append(
            {
                "id": "from_repo_unavailable",
                "message": FROM_REPO_UNAVAILABLE.format(reason=from_repo_problem),
            }
        )
    if not running_kernel_found:
        notices.append(
            {"id": "running_kernel_not_found", "message": RUNNING_KERNEL_NOT_FOUND}
        )
    if history_problem is not None:
        notices.append(
            {
                "id": "history_fallback",
                "message": HISTORY_FALLBACK.format(reason=history_problem),
            }
        )
    if user_installed_problem is not None:
        notices.append(
            {
                "id": "user_installed_unavailable",
                "message": USER_INSTALLED_UNAVAILABLE.format(
                    reason=user_installed_problem
                ),
            }
        )
    if security_updates_ok:
        notices.append(
            {"id": "security_updates_cache", "message": SECURITY_UPDATES_CACHE}
        )
    if security_updates_problem is not None:
        notices.append(
            {
                "id": "security_updates_unavailable",
                "message": SECURITY_UPDATES_UNAVAILABLE.format(
                    reason=security_updates_problem
                ),
            }
        )
    if reboot_problem is not None:
        notices.append(
            {
                "id": "reboot_unknown",
                "message": REBOOT_UNKNOWN.format(reason=reboot_problem),
            }
        )
    if last_update_problem is not None:
        notices.append(
            {
                "id": "last_update_unavailable",
                "message": LAST_UPDATE_UNAVAILABLE.format(reason=last_update_problem),
            }
        )
    if running_problem is not None:
        notices.append(
            {
                "id": "running_unavailable",
                "message": RUNNING_UNAVAILABLE.format(reason=running_problem),
            }
        )
    if running_unreadable >= 1:
        notices.append(
            {
                "id": "running_partial",
                "message": RUNNING_PARTIAL.format(count=running_unreadable),
            }
        )
    return notices

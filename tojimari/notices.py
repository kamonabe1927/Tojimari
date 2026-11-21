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


def build_notices(
    is_root: bool,
    from_repo_problem: str | None,
    running_kernel_found: bool,
    history_problem: str | None = None,
    user_installed_problem: str | None = None,
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
    return notices

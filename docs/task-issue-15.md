# タスク: タイムアウトの秒数の二重持ちをなくし、実行部の配線をテストする（issue #15）

- 作成日: 2026-11-22
- 依頼: issue #15「[自走] 外部コマンドのタイムアウト秒数の二重持ちをなくし、実行部の配線をテストする」。週の計画（#17、2026-11-21）で PM が立てた issue
- 書いた人: PM
- 関連: [output-1.1.md](output-1.1.md) の 1.3（終了コード 1 のときの理由）と 2.4 の注意（`notices`）、[design-issue-5.md](design-issue-5.md) の 3.1・5.1・5.2・6（タイムアウトの値、理由の文言、テストの方針）、[design-issue-13.md](design-issue-13.md)・[design-issue-14.md](design-issue-14.md)（dnf と rpm の呼び出しが増えたところ）

## 1. 範囲の判断

マニフェストと今の段階の中に収まると判断した。

- 種類は「コードの質（リファクタリング、テスト）」で、`docs/agent-rules.md` の 6 の週の計画の条件に当たる。根拠は issue に書かれた `docs/vision.md` の 3（1.1 の完了の目安）と、`docs/spec-1.1.md` の 6 が出力の決定を置いた [output-1.1.md](output-1.1.md) の 1.3
- 表と JSON の中身、文言、終了コード、タイムアウトの値は変えない。使う人から見た振る舞いは変わらない
- 新しい依存は入れない。通信は起こさない。テストで実行してよいのは `sys.executable`（Python 自身）だけで、rpm と dnf は実行しない（[design-issue-5.md](design-issue-5.md) の 6）

## 2. main を読み直した結果（issue の「#12 が先にマージされたとき」）

issue を立てた後に #12〜#14 がマージされ、秒数の直書きが増えていた。issue の目的（二重持ちをなくす）に沿って、次をすべて対象にする。目的の外には広げない。

| 場所 | 今の書き方 | 実際の値の持ち主 |
|---|---|---|
| `tojimari/check.py` の `_rpm_failure_message` | 文言に `30 秒` を直書き | `runner.RPM_TIMEOUT` |
| `tojimari/check.py` の `_collect_user_installed` | `notices.command_reason("dnf", 60, err)` | `runner.DNF_TIMEOUT` |
| `tojimari/check.py` の `_collect_running` | `notices.command_reason("rpm", 30, err)` | `runner.RPM_TIMEOUT` |
| `tojimari/check.py` の `collect`（入れた元） | `notices.command_reason("dnf", 60, err)` | `runner.DNF_TIMEOUT` |
| `tojimari/staleness.py` | `_DNF_TIMEOUT = 60` を別に持ち、`command_reason` に渡す | `runner.DNF_TIMEOUT` |

`System` の配線のテストは、`dnf_userinstalled`、`rpm_files`、`history_first_names`、`process_scan` はすでにある。`rpm_list`、`dnf_from_repo`、`dnf_security_upgrades` が残っている。

## 3. 要件

### 3.1 秒数の持ち方

1. タイムアウトの秒数を決めるのは `tojimari/runner.py` の定数（`RPM_TIMEOUT = 30`、`DNF_TIMEOUT = 60`）だけにする。値は変えない
2. `CommandError` に、タイムアウトしたときの秒数を持たせる。`run_command` は、`kind` が `"timeout"` のときに、渡された `timeout` の値を入れる。ほかの `kind` では入らない（`None`）
3. 理由の文言（`check.py` の rpm の失敗の文言、`notices.command_reason`）は、秒数を `CommandError` から取る。`check.py`、`staleness.py`、`notices.py` に、タイムアウトの秒数の数字の直書きも、秒数を別に持つ定数も残さない
4. `notices.command_reason` の引数の形（秒数の引数をなくすか）は、テックリードが決める。呼び出しの側で秒数を書かないで済む形にする
5. 文言は今と一字一句同じにする
   - rpm の問い合わせ全体の失敗（終了コード 1）: `rpm の問い合わせが 30 秒で終わりませんでした`
   - 注意の理由: `dnf が 60 秒で終わらなかった`、`rpm が 30 秒で終わらなかった`
6. `kind` が `"timeout"` なのに秒数が入っていない `CommandError`（今のコードでは `run_command` からは起きない。テストの差し替えで作ったときなど）でも、例外を出さずに理由の文を返す。そのときの文言はテックリードが決める。数字を作り出して出さない（実際の値と違う数を出さないため）

### 3.2 テストで確かめること

1. `System.rpm_list`、`System.dnf_from_repo`、`System.dnf_security_upgrades`（重要度なしと、重要度ありの 1 つ）が、`packages` の argv と `runner` の定数で `run_command` を呼ぶこと。`run_command` を差し替えて確かめ、rpm と dnf は実行しない。`dnf_from_repo` は渡した名前が argv に入ること
2. `run_command` の `os_error`。実行できるファイルではないものを実行させるなど、`sys.executable` 以外の外部コマンドを呼ばずに起こす（作り方はテックリードが決める）
3. `run_command` のタイムアウトで、`kind` が `"timeout"`、秒数が渡した値、標準エラー出力の末尾（`stderr_tail`）が子プロセスの書いたものになること。子プロセスは `sys.executable` で、標準エラー出力に書いてから眠るものにする
4. タイムアウト以外の `kind` では、秒数が入らないこと
5. 理由の文言に出る秒数が `CommandError` の値から来ること（たとえば、30 や 60 ではない値を持つ `CommandError` を渡すと、その値が文言に出る）
6. 今あるテストの期待値（`"dnf が 60 秒で終わらなかった"`、`"rpm が 30 秒で終わらなかった"` など）は、テストで作る `CommandError("timeout")` に秒数を持たせる形に合わせて直す。期待する文言そのものは変えない
7. `tojimari check` と `tojimari check --json` の出力（`generated_at` を除く）と終了コードが変わらないこと。今あるテスト（`tests/test_cli.py`、`tests/test_table.py` など）がそのまま通ることで確かめる

## 4. やらないこと

- 表と JSON の中身、文言の意味と字面、終了コード、タイムアウトの値（30 秒、60 秒）を変えない
- モジュールの分け直し、ほかのリファクタリング（`tests/test_runner.py` の途中にある `if __name__ == "__main__":` の位置なども、今回は触らない）
- `cli.py` の例外の受け方を変えない
- 全体の締め切り（[design-issue-13.md](design-issue-13.md) の 2.4 で作らないと決めたもの）を足さない
- #16 の中身（制御文字の置き換え、標準エラー出力の 1 行の上限）に手を付けない。#16 は次の回以降に進める

## 5. 終わりの条件

- `tojimari/check.py`、`tojimari/staleness.py`、`tojimari/notices.py` に、タイムアウトの秒数の直書きと、秒数を別に持つ定数が無い
- 3.2 の 1〜5 のテストがあり、リポジトリの最上位で `python3 -m unittest` がすべて通る
- `tojimari check` と `tojimari check --json` の出力（`generated_at` を除く）と終了コードが、変更の前と同じ

## 6. 実機での確認

要らない。振る舞いを変えず、テストは Python 自身と差し替えだけで行うため。

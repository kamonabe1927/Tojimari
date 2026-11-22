# 設計: タイムアウトの秒数の二重持ちをなくし、実行部の配線をテストする（issue #15）

- 作成日: 2026-11-22
- 書いた人: テックリード
- 要件: [task-issue-15.md](task-issue-15.md)
- 土台: [design-issue-5.md](design-issue-5.md) の 3.1・5.1・5.2・6、[design-issue-13.md](design-issue-13.md)、[design-issue-14.md](design-issue-14.md)（モジュールの分け方はそのまま守る）

差し戻しは無い。要件に矛盾と抜けは見つからなかった。
振る舞いを変えないリファクタリングとテストで、[output-1.1.md](output-1.1.md) と [spec-1.1.md](spec-1.1.md) は変えない。新しい依存は無い。

## 1. 全体の形

秒数は、次の一方向にだけ流れる。

```
runner.RPM_TIMEOUT / runner.DNF_TIMEOUT   … 秒数を決めるのはここだけ
  └─ System の各メソッド → run_command(argv, timeout)
       └─ タイムアウトしたら CommandError("timeout", timeout=渡された値)
            ├─ check._rpm_failure_message(err)    … err.timeout を文言に入れる
            └─ notices.command_reason(tool, err)  … err.timeout を文言に入れる
```

- 文言を作る側（`check.py`、`notices.py`、`staleness.py`）は `runner` の定数を見ない。見るのは受け取った `CommandError` だけにする
- 理由: 文言の側が定数を見る形（`runner.DNF_TIMEOUT` を `command_reason` に渡すなど）でも直書きは消えるが、「どのコマンドがどの定数で呼ばれたか」を文言の側がもう一度決めることになり、二重持ちが残る。実際に使われた値を例外が運べば、呼び出しと文言がずれようがない

## 2. 決めたこと

### 2.1 `CommandError` に秒数を持たせる

```python
class CommandError(Exception):
    def __init__(self, kind, returncode=None, stderr_tail="", timeout=None):
        ...
        self.timeout = timeout  # kind が "timeout" のときだけ入る（秒）
```

- 引数は最後に足し、既定値は `None`。今ある `CommandError("not_found")`、`CommandError("exit_status", returncode=1, stderr_tail=...)` の書き方はそのまま通る
- 名前は `timeout`。`run_command` の引数と同じ名前にして、「渡された値がそのまま入る」ことが読めるようにする
- `run_command` は `subprocess.TimeoutExpired` を受けたところでだけ `timeout=timeout` を渡す。ほかの 3 つ（`not_found`、`os_error`、`exit_status`）では渡さない
- 入れる値は、`run_command` に渡された値そのもの（`exc.timeout` ではなく引数の `timeout`）。丸めや型の変換はしない
- `CommandError` の中で `kind` と `timeout` の組み合わせを確かめることはしない。`returncode` も同じ扱い（`exit_status` 以外で渡しても止めない）で、そろえる

### 2.2 `notices.command_reason` の引数（未決 1）

秒数の引数をなくし、`command_reason(tool: str, err) -> str` にする。

- 理由: 秒数の引数が残ると、呼び出しの側が何かの数を書くことになり、要件 3.1 の 4（呼び出しの側で秒数を書かないで済む形）を満たせない。既定値を付けて残す形（`timeout=None`）も、古い書き方が通ってしまい、文言と実際の値がずれる入口が残るので採らない
- 呼び出しは 4 か所（`check.py` の 3 か所、`staleness.py` の 1 か所）で、すべて直す。引数の数が変わるので、直し忘れは `TypeError` になり、今あるテストで見つかる

### 2.3 秒数が無いときの文言（未決 2）

`kind` が `"timeout"` で `err.timeout` が `None` のときは、数字の無い文にする。

| 作る場所 | 秒数があるとき（今と同じ） | 秒数が無いとき |
|---|---|---|
| `notices.command_reason` | `{tool} が {秒数} 秒で終わらなかった` | `{tool} が時間内に終わらなかった` |
| `check._rpm_failure_message` | `rpm の問い合わせが {秒数} 秒で終わりませんでした` | `rpm の問い合わせが時間内に終わりませんでした` |

- 判定は `err.timeout is None`。例外は出さない
- 理由: 既定の数（30 や 60）を埋めると、実際と違う数を出しうる（要件 3.1 の 6）。「時間内に」は、タイムアウトで止めたことが伝わり、数字を含まない。`{tool} を実行できなかった`（`os_error` の文）に寄せる案は、実行はできて終わらなかったという事実と違うので採らない
- この文は `run_command` を通る限り出ない（`run_command` は必ず秒数を入れる）。使う人から見える文言は変わらないので、`output-1.1.md` は変えない
- 秒数は `f"{err.timeout}"` でそのまま文字にする。定数は整数なので `30`、`60` と出て、今の文言と一字一句同じになる。定数を小数に変えるような変更は、この issue の外（値を変えないため）

### 2.4 `os_error` の起こし方（未決 3）

テストでは、`tempfile.TemporaryDirectory()` で作った一時ディレクトリのパスを argv の先頭にして `run_command` を呼ぶ。

```python
with tempfile.TemporaryDirectory() as d:
    run_command([d], 10)   # → CommandError("os_error")
```

- ディレクトリは実行できないので、OS が `PermissionError`（`FileNotFoundError` ではない `OSError`）を返し、`run_command` の `except OSError` に入る。何も実行されない
- 理由（ほかの案を採らない理由）

| 案 | 採らない／採る理由 |
|---|---|
| 実行権の無い一時ファイル | root でも一般ユーザーでも失敗するが、ファイルを作る・権限を変えるの 2 手が要る。ディレクトリなら作るだけで済む |
| 実行権はあるが中身が実行形式でない一時ファイル | 失敗はするが、「実行できる印の付いたファイル」をテストが作ることになる。作らずに済む方法があるので避ける |
| `subprocess.run` を差し替えて `OSError` を投げさせる | 外部コマンドは呼ばないが、`run_command` と本物の `subprocess` のつながり（どの例外がどの `kind` になるか）を確かめられない。`not_found` のテストが本物で確かめているのと、そろえる |
| 一時ディレクトリを実行させる（採る） | 権限やファイルの中身に頼らず、クラウド実行環境（root で動く）でも一般ユーザーでも同じ結果になる。`sys.executable` 以外を実行しない決まり（[design-issue-5.md](design-issue-5.md) の 6）にも合う（何も実行されない） |

- クラウド実行環境（Python 3.11）で、一時ディレクトリを実行させると `PermissionError` になることを確かめた

## 3. ファイルごとの変更

モジュールの分け方、関数の分担、出力（表と JSON）の構造は変えない。

| ファイル | 変えること |
|---|---|
| `tojimari/runner.py` | `CommandError` に `timeout` を足す。`run_command` のタイムアウトの枝で `timeout=timeout` を渡す。定数の値、`System`、ほかの関数は変えない |
| `tojimari/notices.py` | `command_reason(tool, err)` にする。`timeout` の枝を 2.3 のとおりにする。`build_notices` と文言の定数は変えない |
| `tojimari/check.py` | `_rpm_failure_message` の `timeout` の枝を 2.3 のとおりにする。`command_reason` の呼び出し 3 か所から秒数を外す |
| `tojimari/staleness.py` | `_DNF_TIMEOUT` を消す。`command_reason` の呼び出しから秒数を外す |
| `tojimari/cli.py`、`table.py`、`packages.py`、`history.py`、`processes.py`、`rpmver.py` | 変えない |

`check.py`、`staleness.py`、`notices.py` には、タイムアウトの秒数の数字も、秒数を持つ定数も残さない。`runner` の定数を import して使うこともしない。

## 4. エラーと権限不足のときの振る舞い

変えない。確かめのために、今の対応を書いておく。

| 起きたこと | `kind` | `returncode` | `timeout` | `stderr_tail` |
|---|---|---|---|---|
| コマンドが無い | `not_found` | `None` | `None` | 空 |
| 時間内に終わらない | `timeout` | `None` | 渡された値 | 止めるまでに子プロセスが書いたものの末尾（最大 5 行） |
| そのほかの `OSError`（実行できないなど） | `os_error` | `None` | `None` | 空 |
| 終了コードが 0 以外 | `exit_status` | 終了コード | `None` | 末尾（最大 5 行） |

- `stderr_tail` の扱い（注意の理由には入れない、rpm の問い合わせ全体の失敗のときだけ標準エラー出力に足す）は今のまま。制御文字の置き換えと 1 行の上限は #16 で扱い、今回は触らない

## 5. テストの方針

- 実行してよいのは `sys.executable` だけ。rpm と dnf は実行しない。`System` の配線は `run_command` を `mock.patch` で差し替えて確かめる
- 実機の出力は新しく使わない。テストに足す値（パッケージの名前など）は、重点リストにある一般的な名前（`sudo` など）だけにする
- `tests/test_runner.py` の途中にある `if __name__ == "__main__":` とその後ろは触らない。足すテストは、その前にある今のクラス（`RunCommandTest`、`SystemTest`）に入れる

### 5.1 足すテスト

`tests/test_runner.py` の `RunCommandTest`

| テスト | 確かめること |
|---|---|
| `os_error` | 一時ディレクトリを argv の先頭にすると、`kind` が `os_error`、`returncode` と `timeout` が `None`、`stderr_tail` が空 |
| タイムアウトの中身 | 子プロセス（`sys.executable`）が標準エラー出力に 7 行書いて flush してから眠る。`run_command(..., 1)` で、`kind` が `timeout`、`timeout` が `1`、`stderr_tail` が末尾の 5 行、`returncode` が `None` |
| ほかの `kind` の秒数 | 今ある `test_exit_status` と `test_not_found` に、`timeout` が `None` であることの確かめを足す |

- タイムアウトのテストの待ち時間は 1 秒にする。今ある `test_timeout`（0.3 秒）は `kind` だけを見ているので短くてよいが、新しいテストは「子プロセスが書き終わってから止める」必要があり、遅い環境で Python の起動が間に合わないとテストがたまに落ちる。子プロセスの眠りは 30 秒にする（止められるので待たない）
- 今ある `test_timeout` はそのまま残す

`tests/test_runner.py` の `SystemTest`

| テスト | 確かめること |
|---|---|
| `rpm_list` | `run_command` が `(packages.RPM_LIST_ARGV, runner.RPM_TIMEOUT)` で 1 回呼ばれ、戻り値がそのまま返る |
| `dnf_from_repo` | `(packages.dnf_from_repo_argv(["sudo", "glibc"]), runner.DNF_TIMEOUT)` で 1 回呼ばれる。渡した名前が argv に入っている。リスト以外（タプル）で渡しても同じ argv になる |
| `dnf_security_upgrades` | 引数なしで `(packages.dnf_security_upgrades_argv(None), runner.DNF_TIMEOUT)`、`"Critical"` で `(packages.dnf_security_upgrades_argv("Critical"), runner.DNF_TIMEOUT)` |
| 定数の値 | `runner.RPM_TIMEOUT == 30`、`runner.DNF_TIMEOUT == 60` |

- 定数の値のテストを置く理由: 文言の `30 秒`、`60 秒` は、これからは定数だけで決まる。ほかのテストは秒数を自分で作った `CommandError` に入れるので、定数が変わっても落ちない。値を変えない（要件 3.1 の 1）ことを守るテストが 1 つ要る

`tests/test_notices.py`（新しいファイル）

| テスト | 確かめること |
|---|---|
| 秒数は `CommandError` から来る | `command_reason("dnf", CommandError("timeout", timeout=7))` が `dnf が 7 秒で終わらなかった` |
| 今の文言 | `timeout=60` で `dnf が 60 秒で終わらなかった`、`timeout=30` と `"rpm"` で `rpm が 30 秒で終わらなかった` |
| 秒数が無い | `CommandError("timeout")` で例外が出ず、`dnf が時間内に終わらなかった`。数字が入っていない |
| ほかの `kind` | `not_found`、`exit_status`、`os_error` の文言が今と同じ。`stderr_tail` が文に入らない |

- `command_reason` を直接確かめるテストは今まで無かった（`check` と `staleness` を通して確かめていた）。秒数の出どころは `command_reason` だけの話なので、ここに置く

`tests/test_check.py` の `ErrorTest`

| テスト | 確かめること |
|---|---|
| rpm のタイムアウトの文言 | `FakeSystem(rpm=CommandError("timeout", timeout=30))` で、`CheckError` の文が `rpm の問い合わせが 30 秒で終わりませんでした` |
| 秒数は `CommandError` から来る | `timeout=7` で `rpm の問い合わせが 7 秒で終わりませんでした` |
| 秒数が無い | `CommandError("timeout")` で `rpm の問い合わせが時間内に終わりませんでした`。数字が入っていない |
| 標準エラー出力の末尾 | `CommandError("timeout", timeout=30, stderr_tail="error: db")` で、文の後ろに改行と `error: db` が続く |

### 5.2 直すテスト

テストで作る `CommandError("timeout")` は、本物の `run_command` が作る形に合わせて秒数を持たせる。決まりは 1 つ: dnf の呼び出しの代わりなら `timeout=60`、rpm の呼び出しの代わりなら `timeout=30`。期待する文言は変えない。

- 文言を見ているところ（直さないと落ちる）
  - `tests/test_check.py`: `test_command_errors`（`dnf が 60 秒で終わらなかった`）、`test_unavailable_reasons`（同じ）、`test_rpm_files_command_errors`（`rpm が 30 秒で終わらなかった`。`kind` が `timeout` のときだけ `timeout=30` を渡す）
  - `tests/test_staleness.py`: `test_failure_kinds`（`dnf が 60 秒で終わらなかった`。`kind` が `timeout` のときだけ `timeout=60` を渡す）
- 文言を見ていないところ（落ちないが、同じ決まりで直す）: `tests/test_check.py`、`tests/test_staleness.py`、`tests/test_cli.py`、`tests/test_table.py` に残る `CommandError("timeout")`
  - 理由: 秒数の無い `CommandError("timeout")` は本物では起きない形で、5.1 の「秒数が無い」のテストだけがわざと使う。ほかに残すと、どれがわざとなのかが読めなくなる
- `tests/test_check.py` の `ErrorTest.test_rpm_command_error` は、`kind` を順に回して `CheckError` になることだけを見ている。`timeout` のときに `timeout=30` を渡す形に直す
- `tests/recorded.py` の `FakeSystem` は変えない（受け取った例外を投げるだけなので）

### 5.3 出力が変わらないことの確かめ

- `tests/test_cli.py` と `tests/test_table.py` の期待値は変えない（変えるのは 5.2 の `CommandError` の作り方だけ）。これらが通ることで、表と JSON と終了コードが変わらないことを確かめる
- 実装の後、リポジトリの最上位で `python3 -m unittest` を実行し、すべて通ることを確かめる（今は 300 件が通っている）
- `tojimari/check.py`、`tojimari/staleness.py`、`tojimari/notices.py` に秒数の直書きが残っていないことは、レビューで確かめる（`grep` で `30`、`60`、`_TIMEOUT` を探す）。5.1 の「秒数は `CommandError` から来る」のテストが、動きの面からこれを支える

## 6. やらないこと

- [task-issue-15.md](task-issue-15.md) の 4 のとおり。表・JSON・文言・終了コード・タイムアウトの値の変更、ほかのリファクタリング、`cli.py` の例外の受け方、全体の締め切り、#16 の中身には手を付けない
- `CommandError` を dataclass にする、`kind` を列挙型にするなどの作り替えはしない
- 秒数を文言にする共通の関数は作らない。文の形が 2 つ（注意の理由と、rpm の問い合わせ全体の失敗）で違い、まとめても枝が 2 つ残るだけなので、それぞれの場所に書く

## 7. 実機での確認

要らない（[task-issue-15.md](task-issue-15.md) の 6 のとおり）。

# 設計: 後から入れたものの表示（issue #12、1.1-A）

- 作成日: 2026-11-21
- 書いた人: テックリード
- 関連: [task-issue-12.md](task-issue-12.md)（要件）、[output-1.1.md](output-1.1.md) の 2.4・2.6・3.3（JSON、notices、表）、[design-issue-5.md](design-issue-5.md)（土台の設計。今回もそのまま守る）
- 位置付け: 要件と出力仕様は変えない。この文書は「どう作るか」だけを決める。読み取りに幅がある所をどう決めたかは 8 に、手元で確かめられていないことは 9 にまとめた

## 1. 全体の形

design-issue-5.md の一方向の流れに、dnf 履歴のデータベースを足す。

```
実行部（runner）         外部コマンド、OS、データベースのファイルに触れるのはここだけ
   ↓ 文字列 / 行
読み取り部               決めた形のものを、データに直す。ファイルも開かず、何も実行しない
  packages               rpm と dnf の問い合わせの形と、その読み取り（今までどおり）
  history（新しく作る）  dnf 履歴に投げる SQL の形と、返ってきた行の読み取り
   ↓ データ
組み立て（check）        レポートに checks.user_installed と notices を足す
   ↓ レポート
出力（cli / table）      table に [後から入れたもの] を足す。cli は変えない
```

- データベースを「開く・閉じる・書き換わっていないか確かめる」は実行部、「どの SQL を投げ、返ってきた行をどう読むか」は読み取り部に置く（task-issue-12.md の 7）
- SQL と行の読み取りを同じ `history.py` に置く。`packages.py` で問い合わせの書式と読み取りを同じ場所に置いたのと同じ理由（片方を変えたらもう片方も変えることになる）
- 新しい依存は無い。足す標準ライブラリは `sqlite3` と `urllib.parse`（パスを URI にするため）、テストで `tempfile`、`unittest.mock`

## 2. dnf 履歴のデータベースの開き方

### 2.1 決めたこと

- パスは `/var/lib/dnf/history.sqlite` に固定する（`history.DB_PATH`）
- 開き方は `sqlite3.connect("file:<パス>?mode=ro&immutable=1", uri=True)` の 1 通りだけにする
- 開く前と読んだ後に、Tojimari の側でファイルの様子を確かめる（2.3）。確かめに通らなければ読んだ結果を捨てて、履歴が取れなかったものとして扱う（代わりの判定になる）
- 使い終わったら必ず閉じる（`try` / `finally`）

### 2.2 理由（手元の SQLite 3.45.1 で、root で確かめた結果）

一時ディレクトリに作ったデータベースで確かめた。dnf のデータベースがどの記録方式（ジャーナルの方式）で作られているかは手元では分からない（9 の G）ので、どの方式でも 3.5 を守れる開き方を選んだ。

| 開き方 | 確かめた結果 |
|---|---|
| `mode=ro` だけ | データベースが WAL という方式のとき、開いて読んだだけで、同じディレクトリに `-shm` と `-wal` のファイルが新しく作られ、閉じても残った。すでにある場合も `-shm` の中身が書き換わった。task-issue-12.md の 3.5（新しいファイルを作らない、書き込みをしない）に反するので採らない |
| `immutable=1` だけ | ファイルが無いとき、空のファイルが新しく作られた。採らない |
| `mode=ro&immutable=1` | ファイルが無ければ開けずに失敗し、何も作られなかった。WAL でもそうでなくても、ファイルは増えず、中身も変わらなかった。これを採る |

`immutable=1` は「このファイルは変わらない」と SQLite に伝える指定で、SQLite はロックを取らず、補助のファイル（`-journal`、`-wal`、`-shm`）も開かない。そのため次の 2 つを Tojimari の側で補う必要がある。

- WAL の方式で `-wal` に中身が残っていると、本体のファイルだけを読むことになり、古い中身や食い違った中身を読む（手元では、あるはずのテーブルが「無い」と返った）
- dnf が同時に書いていても、SQLite は気づかない

これを 2.3 の確かめで補う。ロックを取らないので、Tojimari が dnf の動作を待たせることも無い。

採らなかった案:

- データベースの先頭を読んで方式を見分け、WAL でなければ `mode=ro`（SQLite のロックに任せる）、WAL なら `immutable=1` にする: 開き方が 2 通りになり、どちらにも 2.3 の確かめが要る。1 通りにしたほうが、レビューとテストの範囲が小さい
- ファイルを一時ディレクトリに写してから開く: Tojimari は書き込みを一切しない（output-1.1.md の 1.1）ので採らない

### 2.3 開く前と読んだ後の確かめ

「様子」を次の 5 つの組とする（`os.stat` と、先頭 100 バイトの読み取りだけで取る）。

- 本体のファイルの大きさ、更新時刻（ナノ秒）、先頭 100 バイト（SQLite のヘッダ。方式によっては書き換えのたびに変わる番号が入っている）
- `<パス>-journal` の大きさ、`<パス>-wal` の大きさ（無ければ 0）

手順:

1. 様子を取る。本体が無い、読めないときはここで分かる
2. `-journal` か `-wal` の大きさが 0 より大きければ、開かずに止める（dnf が書いている途中か、書きかけの記録が残っている。`immutable=1` では正しく読めない）
3. 開いて、読み取り部の問い合わせ（3.2）を行い、閉じる
4. もう一度様子を取り、1 と少しでも違えば、読んだ結果を捨てる（読んでいる間に書き換わった）

分かっている限界:

- 2 と 4 は SQLite のロックほど確実ではない。ただし、外れたときに起きるのは「1 回の表示で OS 標準の名前の集まりがずれる」か「問い合わせが失敗して代わりの判定になる」で、何かを書き換えることは無い。読むのは一瞬で、dnf を動かしている最中に `tojimari check` を打ったときだけ関係する
- 検証用 VM のデータベースが WAL の方式で、dnf が動いていないときも `-wal` に中身が残る作りだった場合、2 でいつも止まり、いつも代わりの判定になる。そのときは `history_fallback` の注意に理由が出るので、実機確認（9 の G、H）で分かる。その場合に WAL を通して読むには `-shm` への書き込みが避けられない（上の表の 1 行目）ので、設計では決めず、PM に返して要件（3.5）の扱いを決め直す

## 3. ファイルと関数

型の書き方、Python の版の決まりは design-issue-5.md の 4 と 8 のまま。

### 3.1 変えるファイル

| ファイル | すること |
|---|---|
| `tojimari/history.py` | 新しく作る。SQL の形と行の読み取り |
| `tojimari/runner.py` | データベースを開く関数と、`System` のメソッド 2 つを足す |
| `tojimari/packages.py` | `dnf repoquery --userinstalled` の呼び方を足す |
| `tojimari/check.py` | `checks.user_installed` の組み立てを足す |
| `tojimari/notices.py` | notice を 2 つ足す |
| `tojimari/table.py` | `[後から入れたもの]` を足す |
| `tests/recorded.py`、`tests/test_*.py` | 6 のとおり。`tests/test_history.py` を新しく作る |

`cli.py`、`__main__.py`、`__init__.py` は変えない。

### 3.2 `history.py`（読み取り部。新しく作る）

```python
DB_PATH = "/var/lib/dnf/history.sqlite"

REQUIRED_COLUMNS = {                    # 使う列。#10 で本人が確かめた構造に含まれるもの
    "trans": ("id",),
    "trans_item": ("trans_id", "item_id"),
    "rpm": ("item_id", "name"),
}

class HistoryError(Exception):
    """dnf 履歴が取れなかった（代わりの判定に切り替える）。"""
    kind: str   # 5.2 の表の値

def query_first_transaction(execute) -> frozenset[str]:
    """execute は「SQL の文字列を受け取り、行（タプル）のリストを返す」呼び出し。
    履歴の 1 番に含まれたパッケージ名の集まりを返す。取れなければ HistoryError。"""

def reason_text(kind: str) -> str      # 5.2 の理由の要約。知らない kind は「dnf 履歴を読み取れなかった」
```

`query_first_transaction` の手順（投げる SQL はこのモジュールの定数だけ。外から来た文字列を SQL に入れない）:

1. `REQUIRED_COLUMNS` の各テーブルに `PRAGMA table_info("<テーブル名>")` を投げ、各行の 2 番目（列名）を集める。使う列が 1 つでも無ければ（テーブルが無ければ 0 行なので、これも含む）`HistoryError("missing_columns")`
2. `SELECT COUNT(*) FROM trans WHERE id = 1` が 0 なら `HistoryError("no_first_transaction")`
3. `SELECT DISTINCT rpm.name FROM trans_item JOIN rpm ON rpm.item_id = trans_item.item_id WHERE trans_item.trans_id = 1` の各行から、空でない文字列の名前だけを集める（SQLite は列に文字列以外も入るため、文字列でないものは捨てる）
4. 集まりが空なら `HistoryError("no_rpm_items")`。そうでなければ `frozenset` で返す

- id が 1 の処理だけを見る。いちばん小さい id などで代わりにしない（task-issue-12.md の 3.1）
- `trans_item` のほかの列（`action`、`state` など）は見ない。要件が使う列を 5 つに限っているため（task-issue-12.md の 2）
- このモジュールは `sqlite3`、`os`、`subprocess` を import しない。`execute` が投げる例外は捕まえない（実行部が捕まえる）

### 3.3 `runner.py`（実行部）

```python
def read_history_db(path: str, query):
    """path のデータベースを 2 の決まりで開き、query(execute) の結果を返す。
    開けない、確かめに通らない、問い合わせが失敗したときは history.HistoryError。"""

class System:
    def dnf_userinstalled(self) -> str            # packages.DNF_USERINSTALLED_ARGV を DNF_TIMEOUT で実行
    def history_first_names(self) -> frozenset[str]   # read_history_db(history.DB_PATH, history.query_first_transaction)
```

`read_history_db` の決まり:

- 様子を取る内部の関数（`_db_snapshot(path)`）を作る。本体の `os.stat` と、`open(path, "rb")` での先頭 100 バイトの読み取り、`-journal` と `-wal` の `os.stat`（`FileNotFoundError` なら大きさ 0）
- 例外の対応: 本体が `FileNotFoundError` → `not_found`、`PermissionError` → `permission`、そのほかの `OSError` → `os_error`。補助のファイルで `FileNotFoundError` 以外の `OSError` → `os_error`
- URI は `"file:" + urllib.parse.quote(path) + "?mode=ro&immutable=1"`。`mode=ro` と `immutable=1` の両方を必ず付ける（片方だけにしない。2.2）
- `query` には `lambda sql: conn.execute(sql).fetchall()` にあたるものを渡す。接続そのものは渡さない
- `sqlite3.connect` から閉じるまでの間の `sqlite3.Error` は `HistoryError("query_failed")` にする。SQLite のメッセージは理由に入れない（形を決められない文字列を出力に混ぜないため）。`query` が投げた `HistoryError` はそのまま通す
- 接続は `finally` で必ず閉じる。成功、`HistoryError`、`sqlite3.Error` のどれでも閉じる
- 2.3 の 2 は `busy`、4 は `changed`
- 標準出力、標準エラー出力には何も書かない。ファイルを書き込み用に開く所を作らない

### 3.4 `packages.py`

```python
DNF_USERINSTALLED_ARGV = [
    "/usr/bin/dnf", "repoquery", "--userinstalled", "--cacheonly", "--quiet",
    "--queryformat", DNF_QUERYFORMAT,
]
```

- 書式は重点リストの入れた元を取るときと同じ `DNF_QUERYFORMAT`（6 項目、本物のタブと改行）。読み取りも同じ `parse_dnf_from_repo` を使う。1 回の問い合わせで「利用者が入れたと記録されている版」と「その入れた元」の両方が取れる
- 名前は引数に渡さない（全部を取る）
- `dnf_from_repo_argv` と前半が重なるので、共通の部分を 1 か所にまとめてよい（出来上がる引数の並びは変えない）

### 3.5 `check.py`

```python
def os_names_from_repo(userinstalled: dict) -> frozenset[str]
    """代わりの判定。from_repo が "anaconda" の行を 1 つでも持つ名前の集まり。"""

def build_user_installed(installed, userinstalled, os_names, method) -> dict
    """output-1.1.md の 2.6 の形。userinstalled が None なら unavailable。"""
```

`collect` に足す手順（重点リストの組み立ては変えない。`collect` が長くなるので、この部分は内部の関数に分ける）:

1. `system.dnf_userinstalled()` → `parse_dnf_from_repo`。`CommandError` なら、理由を重点リストと同じ `_command_reason("dnf", 60, err)` で作り、一覧は無し（`None`）とする
2. 読み取れた行が 0 なら、一覧は無しとし、理由は「dnf の出力に読み取れる行が無かった」（8.1）
3. 一覧の名前のどれも rpm の記録に無ければ、一覧は無しとし、理由は「dnf の出力が rpm の記録と突き合わなかった」（8.1）
4. 一覧が無しなら、履歴は読まない（データベースを開かない）。`status` は `unavailable`、`method` は null、`packages` は空配列
5. 一覧があれば `system.history_first_names()`。成功なら `method` は `history`。`HistoryError` なら `os_names_from_repo` を使い、`method` は `from_repo_fallback`、理由は `history.reason_text(err.kind)`
6. `build_user_installed` で組み立て、`checks` に `focus_packages` の次のキーとして `user_installed` を足す
7. `notices.build_notices` に、履歴が取れなかった理由と、一覧が取れなかった理由を渡す

`build_user_installed` の決まり:

- 一覧の名前の集まり（dnf の行の名前）から `os_names` を除く。名前だけで比べる
- 残った名前について、rpm の一覧（`installed`）にあるその名前の版をすべて並べる。版の値は rpm の記録から取り、`packages.version_entry` で作る。`is_running_kernel` は付けない
- `from_repo` は、その版のキー（`packages.version_key`）が一覧にあればその値、無ければ null
- rpm の記録にあって dnf の一覧に名前が無いもの、dnf の一覧にあって rpm の記録に無い名前は、どちらも入れない（task-issue-12.md の 7）
- 並びは `(name, version, release, arch)` の文字列の昇順
- 重点リストの名前でも除かない
- キーの順は `status`、`method`、`packages`

### 3.6 `notices.py`

`build_notices` の引数に `history_problem: str | None` と `user_installed_problem: str | None` を足す。並びは output-1.1.md の 2.4 の表の順（`running_kernel_not_found` の後に `history_fallback`、`user_installed_unavailable`）。どちらも `None` でないときだけ出す。

| `id` | 文言 |
|---|---|
| `history_fallback` | dnf 履歴を読み取れなかったため（理由: <5.2 の要約>）、入れた元のリポジトリが anaconda かどうかによる代わりの判定を使いました。精度が落ちており、インストール後に更新した OS 標準のパッケージが「後から入れたもの」に混ざることがあります。 |
| `user_installed_unavailable` | 後から入れたものの一覧を取得できなかったため、確認できませんでした（理由: <5.1 の要約>）。「後から入れたものは無い」という意味ではありません。 |

### 3.7 `table.py`

- 重点リストの表（と「動いているカーネル」の行）の後、`[注意]` の前に出す。`checks` に `user_installed` が無ければ出さない
- 列をそろえて行を作る部分は、重点リストと共通の内部の関数にまとめる（同じ処理を 2 回書かない）。重点リストの見た目は 1 文字も変えない
- 見た目は output-1.1.md の 3.3 と、この文書の 4.2

## 4. 出力の形

### 4.1 JSON

output-1.1.md の 2.6 のとおり。`schema_version` は 1 のまま（項目を足すだけ）。

```json
"checks": {
  "focus_packages": { },
  "user_installed": {"status": "ok", "method": "history", "packages": [ ]}
}
```

取れなかったときは `{"status": "unavailable", "method": null, "packages": []}`。

### 4.2 表（output-1.1.md の 3.3 に書かれていない細部）

```
[後から入れたもの]  dnf 履歴の 1 番の名前を除いた 3 件
パッケージ  バージョン     アーキ   入れた元
gh          2.65.0-1       aarch64  gh-cli
git         2.47.1-1.el10  aarch64  appstream
htop        3.3.0-5.el10   aarch64  epel
```

- 見出しの行は `[後から入れたもの]`、空白 2 つ、判定と件数。件数は `packages` の中の名前の種類の数
- 列は「パッケージ」「バージョン」「アーキ」「入れた元」。幅はこの表の中だけでそろえる（重点リストの幅とは合わせない）
- 0 件のとき: 見出しの行（「…を除いた 0 件」）の次の行に `該当なし`
- `status` が `ok` でないとき（`unavailable` と、知らない値）: 見出しの行は `[後から入れたもの]` だけにし、次の行に `確認できませんでした`。`packages` は見ない
- `method` が知らない値のとき: 見出しの行は `[後から入れたもの]`、空白 2 つ、`N 件`
- 前の表との間は空行 1 つ

## 5. エラーと権限不足のときの振る舞い

終了コードは変えない。rpm の失敗だけが 1 で、今回足すものはどれも 0 のまま続ける。

### 5.1 `dnf repoquery --userinstalled`（確認できなかったと出す）

| 起きたこと | `user_installed_unavailable` に入れる理由の要約 |
|---|---|
| dnf が無い、時間内に終わらない、終了コードが 0 でない、実行できない | 重点リストと同じ文（design-issue-5.md の 5.2） |
| 読み取れた行が 0 | dnf の出力に読み取れる行が無かった |
| 一覧の名前のどれも rpm の記録に無い | dnf の出力が rpm の記録と突き合わなかった |

重点リストとその注意（`from_repo_unavailable`）は、これと独立に今までどおり出す。

### 5.2 dnf 履歴（代わりの判定にして続ける）

| `kind` | 起きたこと | `history_fallback` に入れる理由の要約 |
|---|---|---|
| `not_found` | データベースのファイルが無い | dnf 履歴のデータベースが見つからない |
| `permission` | 読む権限が無い（root なしなど） | dnf 履歴のデータベースを読む権限が無い |
| `os_error` | そのほかの理由で様子を取れない | dnf 履歴のデータベースを開けなかった |
| `busy` | `-journal` か `-wal` に中身がある | dnf 履歴のデータベースに書きかけの記録があった（dnf が動いている途中の可能性がある） |
| `changed` | 読んでいる間に様子が変わった | 読んでいる間に dnf 履歴のデータベースが書き換わった |
| `query_failed` | SQLite が失敗した（壊れている、データベースでない、など） | dnf 履歴のデータベースへの問い合わせが失敗した |
| `missing_columns` | 使う列が無い | dnf 履歴のデータベースに、使う列が無かった |
| `no_first_transaction` | id が 1 の処理が無い | dnf 履歴に 1 番の処理が無かった |
| `no_rpm_items` | 1 番にパッケージが 1 件も無い | dnf 履歴の 1 番にパッケージが 1 件も無かった |

- 理由の要約は Tojimari が決めた上の文だけにする。パス、SQLite のメッセージ、例外の文字列は出力に入れない

## 6. テストの方針

- 標準ライブラリと `unittest` だけ。リポジトリの最上位で `python3 -m unittest` を実行すれば全部通ること。今あるテストは、下に書いた 1 か所の書き換えを除いて、そのまま通ること
- rpm と dnf を呼ばない。実機の `/var/lib/dnf/history.sqlite` を開かない（テストから `runner.System().history_first_names()` を呼ばない）
- テスト用のデータベースは、テストの中で `sqlite3` で作る。`history.py` のテストはメモリ上（`:memory:`）、`runner.py` のテストは `tempfile.TemporaryDirectory` の中のファイルにする。リポジトリの中にデータベースのファイルを置かない
- テーブルと列の名前は、#10 で本人が貼った構造の `trans`、`trans_item`、`rpm`、`item` の列名をそのまま使う（`tests/recorded.py` に作る関数を置く）。列の型は届いていないので、型を書かずに作る（実装は型に頼らない）。中身は架空のパッケージ名と番号だけにし、`trans` の `cmdline`、`user_id`、日時などには実機らしい値を入れない（空か 0 でよい）
- `tests/recorded.py` の `FakeSystem` に、`dnf_userinstalled()` と `history_first_names()` を足す（返す値か、投げる例外を受け取る。今の作りと同じ）。履歴が呼ばれたかを覚える
- 記録出力の例（どれも架空）: 一覧は、kernel の 2 つの版（入れた元が `anaconda` と `baseos`）、bash（`baseos`。インストール後に更新された OS 標準の役）、sudo（`anaconda`）、git、htop、gh、openssl（epoch あり）。履歴の 1 番の名前は kernel、kernel-core、bash、sudo など。rpm の記録出力にも対応する行を足す

| テスト | 確かめること |
|---|---|
| `test_history.py` | 1 番の名前が重複なく返ること。2 番以降の処理のパッケージが混ざらないこと。テーブルが無い、`rpm.name` が無い、`trans_item.item_id` が無い → `missing_columns`。id が 1 の処理が無く 2 だけある → `no_first_transaction`（2 番で代わりにしない）。1 番に rpm の行が無い → `no_rpm_items`。名前が文字列でない行、空の行を捨てること。`reason_text` が全部の `kind` と知らない `kind` に文を返すこと。モジュールが `sqlite3`、`os`、`subprocess` を import していないこと |
| `test_runner.py` | 一時ディレクトリのデータベースを読めること。**読む前と後でディレクトリのファイルの一覧が同じであること（WAL の方式で作って閉じたデータベースと、そうでないものの両方で）**。ファイルが無い → `not_found` で、ファイルが作られないこと。`-journal` に中身がある、`-wal` に中身がある → `busy`。データベースでないファイル → `query_failed`。`query` の中でファイルを書き換える → `changed`。`os.stat` を差し替えて `PermissionError` → `permission`。`query` に渡された呼び出しで書き込みの SQL を投げると失敗すること。成功、`HistoryError`、`sqlite3.Error` のどれでも、終わった後に接続が閉じていること（渡された呼び出しを後から使うと失敗する）。パスに空白や `?` `#` を含むディレクトリでも開けること |
| `test_packages.py` | `DNF_USERINSTALLED_ARGV` が絶対パス、`--userinstalled`、`--cacheonly`、`--quiet`、`--queryformat` と書式を含み、名前を含まないこと。`dnf_from_repo_argv` の結果が今までと同じこと |
| `test_check.py` | 履歴が取れるとき: 1 番の名前（版が違う kernel、更新された bash を含む）が除かれ、残りが出て、`status` が `ok`、`method` が `history`、`history_fallback` が出ない。履歴が各 `kind` で取れないとき: `anaconda` の行を持つ名前が除かれ（bash は残る）、`method` が `from_repo_fallback`、`history_fallback` に理由の要約が入る。dnf の一覧が `CommandError` の各種類、0 行、rpm と突き合わない → `unavailable`、`method` が null、`packages` が空、`user_installed_unavailable` が出て、重点リストは今までどおり出て、履歴が呼ばれない。0 件（一覧の名前が全部 1 番にある）→ 空の一覧で `ok`、注意は出ない。同じ名前の版が複数、epoch あり（`evr` に出る）。重点リストの名前が後から入れたものに当たれば両方に出る。版の値が rpm の記録のもので、`from_repo` が一覧のもの、キーが合わない版は null。並び。キーの順（`checks` は `focus_packages`、`user_installed`。`user_installed` は `status`、`method`、`packages`。版の要素は 2.3 の順で `is_running_kernel` が無い）。notice の並び。今ある「後で足すキーが無いこと」のテストは、`staleness` が無いことだけを見るように書き換える |
| `test_table.py` | `[後から入れたもの]` が重点リストの後、`[注意]` の前に出ること。判定ごとの見出しの文と件数（名前の数）。列がそろうこと。版が複数のとき 2 行目から名前が空くこと。入れた元が null のとき `-`。0 件で `該当なし`、列の見出しが出ないこと。`unavailable` と知らない `status` で `確認できませんでした`。`user_installed` が無いレポートで何も出さずに続くこと。レポートの名前、`evr`、arch、`from_repo` が全部表に出ること。重点リストの部分が今までと同じこと |
| `test_cli.py` | `check --json` の出力に `checks.user_installed` があり、`collect` の結果と同じであること。今ある「保証」などの言葉が無いことのテストに、新しい 2 つの notice が出る場合と新しい表を含めること |

## 7. 実装担当への指示

1. 3.1 の表のファイルを、3.2〜3.7 と 4、5 のとおりに変える。`cli.py` は変えない
2. `history.py` は `sqlite3`、`os`、`subprocess` を import しない。データベースに触れるのは `runner.read_history_db` だけにする
3. 開き方は `mode=ro&immutable=1` の 1 通りだけ。`mode=ro` だけ、`immutable=1` だけの開き方をコードにもテストにも作らない（2.2 のとおり、ファイルが作られる）
4. SQL は `history.py` の定数だけ。文字列を組み立てて SQL にしない（テーブル名は `REQUIRED_COLUMNS` の固定の名前だけ）
5. 出力（JSON、表、notice）に入れる理由は 5 の表の文だけ。例外の文字列、SQLite や dnf のメッセージ、パスを入れない
6. 6 のテストを書き、リポジトリの最上位で `python3 -m unittest` が全部通ることを確かめる。テストが作るファイルは一時ディレクトリの中だけにし、終わったら残さない
7. テスト用データは全部架空にする。実機の生の情報（ホスト名、ユーザー名、ホームのパスなど）を入れない
8. 今回作らないもの: 古さ、今動いているかの印、`trans` のほかの列の読み取り、データベースのパスを変える指定、WAL を通して読む開き方
9. この文書と要件のとおりに作れない所が出たら、自分で決めずに、どこが作れないかを返す
10. 手元では dnf も実機のデータベースも無いので、9 の表は確かめられない。確かめたと書かない

## 8. 要件に書かれていない細部（今回決めたこと）

要件と出力仕様は変えていない。読み取りに幅がある所を次のように決めた。PM が要件や出力仕様に取り込むかを決める。

### 8.1 dnf が成功したのに一覧が使えないとき

dnf が終了コード 0 で終わっても、読み取れた行が 0、または一覧の名前のどれも rpm の記録に無いときは、`unavailable` にする。

- 理由: 書式が見込みと違って 1 行も読めなかったときに、0 件の `ok`（「該当なし」）と出してしまうと、「無かった」と読める。task-issue-12.md の 3.3 の「無かったと出さない」に合わせた。重点リストの `from_repo_unavailable` と同じ考え方
- AlmaLinux をインストールした VM で、利用者が入れたと記録されたパッケージが 1 つも無いことは考えにくい

### 8.2 代わりの判定は名前で除く

`from_repo` が `anaconda` の行を 1 つでも持つ名前を OS 標準とみなし、その名前の版をすべて除く。

- 理由: 履歴を使う判定と同じく名前で比べることにし、除き方を 1 通りにするため。行ごとに除くと、同じ名前の古い版（`anaconda`）は除かれ新しい版は残る、という見え方になり、名前ごとに版をすべて並べる決まり（task-issue-12.md の 3.4）と合わない
- `anaconda` の行が 1 つも残っていない名前（更新されて古い版が消えた OS 標準）は、後から入れたものに混ざる。これは `history_fallback` の注意に書いてある精度の落ち方そのもの

### 8.3 版は名前でまとめて並べる

後から入れたものと判定された名前について、rpm の記録にあるその名前の版をすべて並べる（dnf の一覧に行が無い版も並べ、その `from_repo` は null）。dnf の出力は「どの名前か」と「入れた元」にだけ使う（task-issue-12.md の 3.4）。

## 9. 手元で確かめられていないこと（実機確認の手順に入れる）

task-issue-12.md の 6 の手順に、次を足す・置き換える。セキュリティ担当が PR を作るときに取り込む。どれも読むだけで、出るのはファイル名、大きさ、数字で、パッケージ名以外の実機の情報は出ない。

| 記号 | コマンド | 確かめること |
|---|---|---|
| G | `sudo python3 -B -c "print(open('/var/lib/dnf/history.sqlite','rb').read(20)[18:20])"` | `b'\x01\x01'` か `b'\x02\x02'` のどちらが出たか（データベースの記録方式。`\x02` なら WAL） |
| H | `sudo stat -c '%n %s' /var/lib/dnf/history.sqlite*`（dnf を動かしていないときに） | `history.sqlite-wal` や `history.sqlite-journal` があるか、その大きさ。0 より大きいものがあれば、手順 2 と 3 は代わりの判定になり、`[注意]` に「書きかけの記録があった」と出る見込み。そうなったら結果を伝えてほしい（2.3 のとおり、要件の決め直しが要る） |
| I | `dnf repoquery --userinstalled --cacheonly --quiet --queryformat $'%{name}\t%{epoch}\t%{version}\t%{release}\t%{arch}\t%{from_repo}\n' \| cat -A \| head -5; echo "exit=${PIPESTATUS[0]}"`（表の中なので `\|` と書いた。打つときは `|`。task-issue-12.md の 6 の手順 6 の呼び方はこれ） | 終了コードが 0。1 件ごとに 6 項目がタブ区切りで出る。epoch の無いものが `0` と出る |
| J | task-issue-12.md の 6 の最後にある件数だけを出すコマンドは、`mode=ro` を `mode=ro&immutable=1` に置き換えて使う | 数が出る。`mode=ro` だけで開くと、2.2 のとおり `/var/lib/dnf/` にファイルが作られることがある |

分かっていないことと、外れたときの動き:

- データベースの記録方式と、dnf が動いていないときに補助のファイルに中身が残るか → G、H で分かる。残る作りなら、いつも代わりの判定になる（誤った一覧は出ず、注意が出る）
- `dnf repoquery --userinstalled` が `--cacheonly` で動くか、書式が見込みどおりか → 外れたら `unavailable` になり、注意が出る。I で分かる
- root なしでデータベースを読めるか（ファイルの権限しだい）→ 読めなければ代わりの判定になり、注意が出る。task-issue-12.md の 6 の手順 5 で分かる
- AlmaLinux 10.2 の SQLite の版での `mode=ro&immutable=1` の動き（手元は 3.45.1）→ task-issue-12.md の 6 の手順 4（前後でファイルの一覧が変わらない）で分かる

## 10. 後で足すものとの関係（今回は作らない）

- 古さ（#13）の「最後に更新した日」も dnf 履歴を使う。`read_history_db` は問い合わせを引数で受け取るので、`history.py` に問い合わせを足せば同じ開き方を使える。今回はそのための関数や列の読み取りを先に作らない
- 今動いているかの印（#14）は、版の要素に項目を足す。`build_user_installed` は `version_entry` を使っているので、足す場所は 1 か所で済む

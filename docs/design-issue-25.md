# 設計: WAL 方式の dnf 履歴を正しく読めるようにする（issue #25）

- 作成日: 2026-11-27
- 書いた人: テックリード
- 関連: [task-issue-25.md](task-issue-25.md)（要件）、[design-issue-12.md](design-issue-12.md) の 2・3.3・5.2（今回置き換える所）、[design-issue-13.md](design-issue-13.md) の 4.2（同じ `read_history_db` を使う）、[output-1.1.md](output-1.1.md) の 1.1 と 2.4
- 位置付け: 要件と出力の形は変えない。変えるのは `runner.read_history_db` の開き方と前後の確かめ、理由の種類 2 つ、テスト。手元で確かめた結果は 2 に、design-issue-12.md から置き換わる点は 7 に、分かっている限界は 9 にまとめた

## 1. 変わること（まとめ）

- データベースの先頭のヘッダで WAL 方式かを見分け、開き方を 2 通りにする
  - WAL 方式: `mode=ro` だけで開く（`immutable` を付けない）。`-wal` の中の記録も読む
  - WAL 方式でない: 今までどおり `mode=ro&immutable=1`
- WAL 方式では、`-wal` に中身があることを理由に止めない。`-shm` か `-wal` のファイルが無いときは、開くと SQLite が新しいファイルを作るので開かない
- 「様子」に `-wal` の更新時刻と先頭 32 バイト、`-shm` があるかを足す
- 理由の種類に `no_shm` と `no_wal` を足す
- 待たない: `sqlite3.connect` に `timeout=0` を渡す（Python の既定は 5 秒待つ）

`history.py` の SQL と行の読み取り、`check.py`、`notices.py`、`table.py`、`cli.py` は変えない。

## 2. 手元で確かめた結果

一時ディレクトリに作ったデータベースで、root で確かめた（SQLite 3.45.1、Python 3.11）。WAL 方式で `-wal` に記録が残った状態は、書いた接続を開いたまま 3 つのファイルを別のディレクトリへ写して作った。「変わったもの」は、読む前と後で、ディレクトリのファイルの一覧、各ファイルの大きさ・中身・更新時刻を比べた結果。

### 2.1 WAL 方式のデータベースを `mode=ro` で開いて読んだとき

| `-shm` | `-wal` | 読めた中身 | 変わったもの | 扱い（3.2） |
|---|---|---|---|---|
| ある | 中身あり | 本体と `-wal` の両方の記録 | `-shm` の中身と更新時刻だけ。本体と `-wal` は大きさ・中身・更新時刻とも同じ | 開く |
| ある | 空（0 バイト） | 本体の記録 | `-shm` の中身と更新時刻だけ | 開く |
| ある | 無い | 本体の記録 | **`-wal`（0 バイト）が新しく作られ、閉じても残った** | 開かない（`no_wal`） |
| 無い | 中身あり | 本体と `-wal` の両方の記録 | **`-shm` が新しく作られた** | 開かない（`no_shm`） |
| 無い | 無い | 本体の記録 | **`-shm` と `-wal` が新しく作られた** | 開かない（`no_shm`） |
| 空（0 バイト） | 中身あり | 本体と `-wal` の両方の記録 | `-shm` の大きさが 0 から 32768 になった。新しいファイルは無い | 開く |
| 中身がでたらめ | 中身あり | 本体と `-wal` の両方の記録 | `-shm` の中身と更新時刻だけ | 開く |
| 空（0 バイト） | 無い | 本体の記録 | **`-wal`（0 バイト）が新しく作られた** | 開かない（`no_wal`） |

- どの場合も、書き込みの SQL（`INSERT`）は失敗した
- `-shm` は、ほかに開いている接続が無いとき、SQLite が中身を作り直す。そのため `-shm` が空でもでたらめでも読める。task-issue-25.md の 3.1 の 6 が受け入れているのは、この書き換え
- 引き継ぎの 3（`-shm` があって `-wal` が無いとき）の答え: SQLite は 0 バイトの `-wal` を作る。だから開かない

### 2.2 そのほか

| 確かめたこと | 結果 |
|---|---|
| WAL 方式で `-journal` にも中身がある（`mode=ro`） | SQLite が失敗した。ファイルは変わらなかった |
| WAL 方式でなく、`-journal` に中身がある（`mode=ro`。でたらめな中身と、書いている途中の本物の両方） | SQLite が失敗した（読み取り専用では巻き戻せない）。ファイルは変わらなかった |
| 同じく `mode=ro&immutable=1` | 失敗せずに読めてしまった（`-journal` を見ないので、書きかけの本体をそのまま読む） |
| WAL 方式でないのに `-wal` に中身がある（`mode=ro`） | `-shm` が新しく作られた |
| 書く接続が開いたままのデータベースを読む | 読めた。書きかけ（確定前）の行は見えなかった。本体と `-wal` は変わらなかった |
| 書く接続が確定（commit）した | `-wal` の大きさと更新時刻が変わった |
| `-wal` が先頭から書き直された（チェックポイントの後の書き込み） | 大きさは同じまま、先頭 32 バイトと更新時刻が変わった |
| その後、同じ大きさの中での書き込み | 大きさも先頭 32 バイトも同じまま、更新時刻だけが変わった |
| 書き込みの権限が無い利用者（root なしにあたる）で、3 つとも読めるとき | 読めた。何も変わらなかった（`-shm` も変わらない） |
| 同じく、`-shm` か `-wal` を読めないとき | SQLite が失敗した。何も作られなかった |

## 3. 決めたこと

### 3.1 WAL 方式かどうかの見分け方

様子の確かめで読んでいる先頭 100 バイトだけで見分ける。データベースは開かない。

- 先頭 16 バイトが `SQLite format 3\x00` で、かつ 19 番目（0 から数えて）のバイトが 2 のとき、WAL 方式とする
- それ以外（1、ほかの値、100 バイトに満たない、データベースでない）は、WAL 方式でないものとして扱う

理由:

- 19 番目のバイトは SQLite のファイル形式の「読むときの版」で、SQLite 自身がこの値が 2 のときに WAL を開く。`PRAGMA journal_mode` を投げるにはデータベースを開く必要があり、開いた時点でファイルが作られうる（2.1）ので使わない
- 先頭 16 バイトも見るのは、データベースでないファイルをたまたま WAL 方式とみなして「`-shm` が無かった」と出さないため。データベースでないものは今までどおり `mode=ro&immutable=1` で開かれ、`query_failed` になる

### 3.2 補助ファイルの組み合わせごとの扱い

上から順に見て、最初に当てはまったものを使う。「ある」「無い」はファイルがあるかどうかで、大きさは問わない（0 バイトでも「ある」）。

| 順 | 方式 | 条件 | すること | 理由の種類 |
|---|---|---|---|---|
| 1 | どちらでも | `-journal` の大きさが 0 より大きい | 開かない | `busy` |
| 2 | WAL | `-shm` が無い | 開かない | `no_shm` |
| 3 | WAL | `-shm` があり、`-wal` が無い | 開かない | `no_wal` |
| 4 | WAL | `-shm` も `-wal` もある | `mode=ro` で開く | - |
| 5 | WAL でない | `-wal` の大きさが 0 より大きい | 開かない | `busy` |
| 6 | WAL でない | それ以外 | `mode=ro&immutable=1` で開く | - |

- 2 は本人の決定（#25）のとおり。`-wal` があっても無くても、`-shm` が無ければ開かない
- 3 は 2.1 の結果による（task-issue-25.md の 3.1 の 5）
- 4 は `-wal` が 0 バイトでもよい。2.1 のとおり、何も作られない
- 5 と 6 は今までと同じ（3.5）

### 3.3 読む前と後の「様子」

次のものを様子とする。`os.stat` と、読み取り用に開いて先頭を読むことだけで取る。

| 対象 | 入れるもの |
|---|---|
| 本体 | 大きさ、更新時刻（ナノ秒）、先頭 100 バイト（今までと同じ） |
| `-journal` | あるか、大きさ、更新時刻 |
| `-wal` | あるか、大きさ、更新時刻、先頭 32 バイト（WAL のヘッダ） |
| `-shm` | あるかどうかだけ |

- `-wal` に 3 つとも入れる理由（2.2）: 確定のたびに大きさが増える。先頭から書き直されると大きさは変わらないが、ヘッダ（書き直しのたびに変わる番号が入っている）が変わる。同じ大きさの中での書き込みは更新時刻でしか分からない
- `-shm` の大きさ・中身・更新時刻は入れない。Tojimari が読むだけで SQLite が書き換えるので（2.1）、入れると自分の読み取りで `changed` になる
- `-shm` を「あるか」だけ入れるのは、読んでいる間に消えた・できたことを `changed` にするため
- 方式によって様子の形を変えない（1 通りにして、分岐を減らす）
- 読む前と後の様子が少しでも違えば `changed`。読んだ結果は捨てる（今までと同じ）

補助ファイルは、あれば読み取り用に開く（`-wal` は 32 バイト読む。`-journal` と `-shm` は開くだけで読まない）。root なしで補助ファイルを読めないときに、SQLite の失敗（`query_failed`）ではなく `permission` と出すため。

### 3.4 開き方

- WAL 方式（3.2 の 4）: `"file:" + urllib.parse.quote(path) + "?mode=ro"`
- WAL 方式でない（3.2 の 6）: `"file:" + urllib.parse.quote(path) + "?mode=ro&immutable=1"`
- どちらも `sqlite3.connect(uri, uri=True, timeout=0)`

`timeout=0` の理由: `immutable` を付けない開き方では SQLite がロックを使う。Python の `sqlite3.connect` は既定で 5 秒までロックが空くのを待つ。待ち合わせはしない決まり（task-issue-25.md の 5）なので、待たずに失敗させる。失敗は今までどおり `query_failed`（3.6）。

書き込みをしないことは、`mode=ro` が担う（2.1 のとおり、書き込みの SQL は失敗する）。Tojimari のコードがファイルを書き込み用に開く所は作らない。

### 3.5 WAL 方式でないとき

今までの決まりをそのまま使う。

- `-journal` に中身がある → 開かずに `busy`
- `-wal` に中身がある → 開かずに `busy`
- どちらも無い・空 → `mode=ro&immutable=1` で開く

`-journal` で止める理由:

- ロールバックジャーナルの方式で `-journal` に中身があるのは、書いている途中か、途中で止まった処理の巻き戻しが済んでいないとき。本体には書きかけの中身が入っている
- 読み取り専用では巻き戻せない。`mode=ro` で開くと SQLite が失敗し、`mode=ro&immutable=1` で開くと書きかけの本体をそのまま読んでしまう（2.2）。どちらでも正しく読めないので、開かない
- 理由の文言は今の `busy`（「書きかけの記録があった（dnf が動いている途中の可能性がある）」）が当てはまる

WAL 方式でないのに `-wal` に中身があるときも止める理由: 本体のヘッダと補助ファイルが食い違っていて、どちらを信じてよいか決められない。`mode=ro` で開くと `-shm` が作られる（2.2）。

`mode=ro`（SQLite のロックに任せる）に変えない理由: #25 で困っているのは WAL 方式だけ。WAL でない方式の開き方は #12 で確かめて決めたもので、変える理由が無い。

WAL 方式で `-journal` に中身があるとき（3.2 の 1）も `busy` にする。SQLite が失敗する（2.2）ので、開く前に止めて、当てはまる理由を出す。

### 3.6 理由の種類

足すもの（`history._REASONS`）:

| `kind` | 起きたこと | `history_fallback`・`last_update_unavailable` に入れる理由の要約 |
|---|---|---|
| `no_shm` | WAL 方式で、`-shm` のファイルが無い | dnf 履歴のデータベースの補助ファイル（-shm）が無かった（開くと新しいファイルが作られるため、開かなかった） |
| `no_wal` | WAL 方式で、`-shm` はあるが `-wal` のファイルが無い | dnf 履歴のデータベースの補助ファイル（-wal）が無かった（開くと新しいファイルが作られるため、開かなかった） |

- どちらも「dnf が動いている途中」とは読めず、どのファイルが無かったかが分かる文にした（task-issue-25.md の 3.1 の 4）
- `busy` の文言は変えない。起きる条件だけが変わる（3.2 の 1 と 5）
- `changed`、`permission`、`os_error`、`query_failed` の文言も変えない
- 理由の表の正本は design-issue-12.md の 5.2。今回そこに上の 2 行を足し、`busy` の「起きたこと」を直した。output-1.1.md の 2.4 は「理由の要約を含める」とだけ書いていて、種類ごとの文言は持たないので、直す所は無い

## 4. ファイルと関数

### 4.1 変えるファイル

| ファイル | すること |
|---|---|
| `tojimari/runner.py` | `_db_snapshot` と `read_history_db` を 3 のとおりに変える |
| `tojimari/history.py` | `_REASONS` に `no_shm` と `no_wal` を足す。ほかは変えない |
| `tests/test_runner.py` | 6 のとおり |
| `tests/test_history.py`、`tests/test_check.py`、`tests/test_staleness.py`、`tests/test_cli.py` | 理由の種類を並べている所に 2 つを足す。6 のとおり |

`tests/recorded.py` は変えなくてよい（`make_history_db`、`make_upgrade_history_db` をそのまま使う）。

### 4.2 `runner.py`

```python
_SQLITE_MAGIC = b"SQLite format 3\x00"
_URI_WAL = "?mode=ro"
_URI_IMMUTABLE = "?mode=ro&immutable=1"

class _DbSnapshot(NamedTuple):
    main: tuple               # (大きさ, 更新時刻 ns, 先頭 100 バイト)
    journal: tuple | None     # 無ければ None。あれば (大きさ, 更新時刻 ns, b"")
    wal: tuple | None         # 無ければ None。あれば (大きさ, 更新時刻 ns, 先頭 32 バイト)
    shm: bool                 # あるかどうか

def _aux_state(path: str, head_len: int) -> tuple | None
def _db_snapshot(path: str) -> _DbSnapshot
def _is_wal(head: bytes) -> bool
def read_history_db(path: str, query)
```

`_aux_state`（補助ファイル 1 つの様子）:

- `os.stat(path)` の後、`open(path, "rb")` で開き、`head_len` バイト読む（0 なら読まない）
- どちらかで `FileNotFoundError` → `None`。`PermissionError` → `HistoryError("permission")`。そのほかの `OSError` → `HistoryError("os_error")`
- 返すのは `(st.st_size, st.st_mtime_ns, 読んだバイト列)`

`_db_snapshot`:

- 本体は今までと同じ（`FileNotFoundError` → `not_found`、`PermissionError` → `permission`、そのほか → `os_error`）
- `journal` は `_aux_state(path + "-journal", 0)`、`wal` は `_aux_state(path + "-wal", 32)`、`shm` は `_aux_state(path + "-shm", 0) is not None`

`_is_wal`: 3.1 のとおり（`len(head) >= 20 and head[:16] == _SQLITE_MAGIC and head[19] == 2`）。

`read_history_db` の手順:

1. `before = _db_snapshot(path)`
2. 3.2 の表を上から順に当てはめる。開かない行に当たったら、その種類の `HistoryError` を投げる
3. 3.4 の URI と `timeout=0` で開き、`query(lambda sql: conn.execute(sql).fetchall())` を呼ぶ。`sqlite3.Error` は `query_failed`、`query` が投げた `HistoryError` はそのまま通す。`finally` で必ず閉じる（ここは今までと同じ）
4. `_db_snapshot(path) != before` なら `changed`

決まり:

- `mode=ro` だけの URI を使うのは 3.2 の 4 に当たったときだけ。ほかの所で使わない
- 接続そのものは `query` に渡さない。`BEGIN` などの SQL を実行部から足さない
- 補助ファイルを作る・消す・写す・書き込み用に開く処理を書かない
- 標準出力、標準エラー出力には何も書かない
- `System` のメソッド、`history.DB_PATH` は変えない
- docstring の「mode=ro&immutable=1 で開き」は、方式で開き方が変わることが分かる文に直す

## 5. エラーと権限不足のときの振る舞い

終了コードと出力の形は変えない。増えるのは理由の種類 2 つだけ。

| 起きたこと | 結果 |
|---|---|
| 本体が無い、読めない | 今までどおり `not_found`、`permission`、`os_error` |
| 補助ファイルがあるのに読めない（root なしなど） | `permission`（今までは `os.stat` しかしていなかった） |
| 補助ファイルの `os.stat` や読み取りがそのほかの理由で失敗 | `os_error`（今までと同じ） |
| WAL 方式で `-shm` が無い、`-wal` が無い | `no_shm`、`no_wal` |
| 開けない、ロックが取れない、問い合わせが失敗 | `query_failed`（待たない） |
| 読んでいる間に様子が変わった | `changed` |

root なしで実行したとき: 本体・`-shm`・`-wal` が読めれば、root のときと同じに読める（2.2。このとき SQLite は `-shm` を書き換えない）。読めないものがあれば `permission` で代わりの判定になる。どちらでも `not_root` の注意は今までどおり出る。

## 6. テストの方針

標準ライブラリと `unittest` だけ。データベースは一時ディレクトリの中に作り、リポジトリには置かない。中身はすべて架空。

### 6.1 `-wal` が残った状態の作り方

Python の `sqlite3` は、最後の接続を閉じると `-wal` を本体に書き戻して `-wal` と `-shm` を消す。そこで、`tests/test_runner.py` に次の関数を作る（手元で動くことを確かめた）。

```python
def make_wal_db(directory):
    """directory の下に、-wal に記録が残った WAL 方式のデータベースを作り、本体のパスを返す。"""
```

1. `directory/src/history.sqlite` を書き込み用に開く。`PRAGMA journal_mode=WAL` と `PRAGMA wal_autocheckpoint=0` を実行する
2. `recorded.make_upgrade_history_db(conn, {1: (10, 20, 1, [6])})` で 1 番の処理を作り、`rpm` に `item_id` が 1 の行（名前は `bash`）を 1 つ足して確定する
3. `PRAGMA wal_checkpoint(TRUNCATE)` を実行する（ここまでの中身が本体に入り、`-wal` が空になる）
4. 2 番の処理（`dt_begin` 30、`dt_end` 40、`state` 1）と、その `trans_item`（`action` 6）を足して確定する。この記録は `-wal` の中にしかない
5. 接続を開いたまま、`history.sqlite`、`-shm`、`-wal` を `directory/db/` へ `shutil.copy` で写す
6. 接続を閉じ、`directory/db/history.sqlite` を返す

この作りで、1 番の処理の名前は `{"bash"}`、最後に更新した日は 40、本体だけを読むと 20 になる。補助ファイルが欠けた組み合わせは、写した後で `os.remove` するか、空のファイルに置き換えて作る。

### 6.2 `tests/test_runner.py` で確かめること

番号は task-issue-25.md の 3.4 の番号。

| 番号 | 確かめること |
|---|---|
| 1 | `make_wal_db` のデータベースで、`query_first_transaction` が `{"bash"}`、`query_last_upgrade` が 40 を返す。別に、本体だけを `mode=ro&immutable=1` でテストから直接開くと 20 になること（`-wal` の中の記録を読んでいる証拠） |
| 2 | 1 の読み取りの前後で、ディレクトリのファイルの一覧が同じ。本体と `-wal` の中身（全バイト）が同じ。`-shm` の中身は比べない |
| 3 | `-shm` を消すと `no_shm`。`-shm` も `-wal` も消したとき（WAL 方式で作って普通に閉じたデータベース）も `no_shm`。どちらもファイルの一覧が変わらない |
| 4 | `query` の中で本体に 1 バイト足す → `changed`。`query` の中で別の接続から書いて確定する（`-wal` が伸びる）→ `changed`。`query` の中で `os.utime` で `-wal` の更新時刻だけを 1 ナノ秒ずらす → `changed`。`query` の中で `-shm` を消す → `changed`。書く接続は `addCleanup` で閉じる |
| 5 | WAL 方式でないデータベース: `-journal` に中身 → `busy`。`-wal` に中身 → `busy`。どちらも空のファイル → 読める。補助ファイルが無い → 読めて、ファイルの一覧も本体の中身も変わらない |
| 6 | `-shm` があり `-wal` が無い → `no_wal` で、ファイルの一覧が変わらない。`-shm` があり `-wal` が 0 バイト → 読めて（`{"bash"}` と 20）、一覧が変わらない。`-shm` が 0 バイトで `-wal` に中身 → 読めて（40）、一覧が変わらない。WAL 方式で `-journal` に中身 → `busy` |
| そのほか | 開き方: WAL 方式のとき URI が `?mode=ro` で終わり `immutable` を含まない。WAL 方式でないとき `?mode=ro&immutable=1` で終わる。どちらも `uri=True` と `timeout=0` が渡る。WAL 方式で開いたときも、書き込みの SQL が失敗する。終わった後に接続が閉じている。`os.stat` を差し替えて `-shm` で `PermissionError` → `permission`。先頭 16 バイトがデータベースのものでなく 19 番目が 2 のファイル → `query_failed`（`no_shm` にならない） |

### 6.3 今あるテストの直し（理由つき）

| テスト | 直し | 理由 |
|---|---|---|
| `test_uri_has_both_options` | 名前を `test_uri_by_mode` などに変え、方式ごとの URI と `timeout=0` を確かめる（6.2 の「そのほか」） | 開き方が 1 通りという前提が無くなった。WAL 方式でないときに `mode=ro&immutable=1` であることは、引き続き確かめる |
| `test_busy` | 中身は変えなくても通る（`make_db` の既定は WAL 方式でない）。WAL 方式でないときの決まりであることが分かるように、名前か説明を直す。WAL 方式で `-wal` に中身があっても `busy` にならないことは 6.2 の 1 で確かめる | 「`-wal` に中身があれば止める」は WAL 方式でないときだけの決まりになった |
| `test_files_unchanged` の `wal=True` の部分 | WAL 方式で作って閉じたデータベース（補助ファイルが無い）は、読めるのではなく `no_shm` になる、に書き換える（6.2 の 3）。ファイルの一覧と本体が変わらないことは引き続き確かめる | 本人の決定（`-shm` が無いときは開かない）による |
| `test_history.py` の `reason_text` の種類の一覧、`test_check.py` の `test_fallback_each_kind`、`test_staleness.py` の種類の一覧 | `no_shm` と `no_wal` を足す | 理由の種類が増えた |

上のほかの今あるテストは、そのまま通ること。

### 6.4 `check` と `cli` を通した確かめ（3.4 の 8）

`tests/test_cli.py` に足す。`FakeSystem(history=HistoryError("no_shm"))` で、

- `check`（表）の出力の `[注意]` に、`history.reason_text("no_shm")` の文が出る
- `check --json` の `notices` の `history_fallback` の `message` に同じ文が入り、`checks.user_installed.method` が `from_repo_fallback`
- `no_wal` でも同じ
- 今ある「保証」などの言葉が無いことのテストに、この 2 つの場合を含める

## 7. design-issue-12.md から置き換わる点

| design-issue-12.md の場所 | 今まで | 今回から |
|---|---|---|
| 2.1 | 開き方は `mode=ro&immutable=1` の 1 通りだけ | 方式で 2 通り（この文書の 3.4） |
| 2.2 の「採らなかった案」の 1 つ目 | 先頭を読んで方式を見分ける案は採らない | 採る（3.1）。ただし当時の案とは逆で、WAL のときに `mode=ro`、WAL でないときに `immutable=1` |
| 2.3 の様子と手順 2 | 様子は 5 つの組。`-journal` か `-wal` に中身があれば止める | 様子は 3.3。止める条件は 3.2 |
| 2.3 の「分かっている限界」の 2 つ目 | 起きたら PM に返す | 実機で起き（#25）、本人が決めた |
| 3.3 の `_db_snapshot`、URI、`busy` の条件 | - | 4.2 |
| 5.2 の表 | `busy` は「`-journal` か `-wal` に中身がある」 | `busy` の条件を直し、`no_shm`、`no_wal` を足した |
| 7 の 3 と 8 | `mode=ro` だけの開き方を作らない。WAL を通して読む開き方は作らない | `mode=ro` だけの開き方は 3.2 の 4 のときだけ使う |
| 9 の J、task-issue-12.md・task-issue-13.md の実機確認のコマンド | `mode=ro&immutable=1` で数を出す | 検証用 VM は WAL 方式なので、このコマンドは本体だけを読み、`-wal` の中の記録を含まない。古い値が出ても不具合ではない |

design-issue-12.md の該当箇所に「#25 で変えた」の一文と、この文書への参照を足した。design-issue-13.md の 4.2（開き方の説明）にも同じ一文を足した。

## 8. 実装担当への指示

1. `tojimari/runner.py` を 4.2 のとおりに変える。`typing.NamedTuple` を使う（標準ライブラリ）。新しい依存は入れない
2. `tojimari/history.py` の `_REASONS` に、3.6 の 2 つを文言どおりに足す。SQL、読み取りの関数、`busy` などの今ある文言は変えない
3. 3.2 の表の順と条件を変えない。特に、WAL 方式で `-shm` か `-wal` のファイルが無いときは `sqlite3.connect` を呼ばない
4. `sqlite3.connect` には必ず `uri=True` と `timeout=0` を渡す
5. 6 のテストを書く・直す。task-issue-25.md の 3.4 の 1〜9 が全部あること。リポジトリの最上位で `python3 -m unittest` が全部通ること
6. テストが作るファイルは一時ディレクトリの中だけ。書く接続を開いたままにするテストは、`addCleanup` で必ず閉じる
7. `check.py`、`notices.py`、`table.py`、`cli.py`、`tests/recorded.py` の `FakeSystem` は変えない。出力の形（項目名、構造、終了コード）を変えない
8. 作らないもの: #26 に関わる変更、補助ファイルを作る・消す・写す処理（テスト用データを作る所は除く）、待ち合わせやリトライ、データベースのパスを変える指定、SQLite のエラーの種類ごとの出し分け、`readonly_shm` などの文書に無い URI の指定
9. テスト用データは全部架空にする。実機の生の情報を入れない
10. この文書のとおりに作れない所が出たら、自分で決めずに、どこが作れないかを返す
11. 手元には dnf も実機のデータベースも無い。10 の表は確かめられないので、確かめたと書かない

## 9. 分かっている限界と、採らなかった案

### 9.1 限界

- **補助ファイルが無いときは、いつも代わりの判定になる**: WAL 方式のデータベースが普通に閉じられて `-shm` も `-wal` も無いとき、今までは読めていた（`immutable=1` で本体だけを読めば正しく、何も作られない）が、今回から `no_shm` で代わりの判定になる。本人の決定（`-shm` が無いときは開かない）をそのまま守った。検証用 VM では dnf が動いていなくても 3 つとも残っていた（#25）ので、普段は当たらない見込み。当たるようなら、「`-shm` が無く `-wal` も無い・空のときは今までの読み方で読む」に変えるかを本人に確かめる（PM に返す）
- **確かめてから開くまでの間に補助ファイルが消えると、SQLite がファイルを作りうる**: 様子を取った直後、開く前に、dnf の最後の接続が閉じて `-shm` と `-wal` が消えた場合。標準ライブラリの `sqlite3` では防げない。読んだ後の確かめで `changed` になり、結果は捨てる。作られるのは空の `-wal` と作り直された `-shm` で、履歴の中身は変わらない
- **更新時刻の細かさ**: `-wal` の同じ大きさの中での書き込みは、更新時刻でしか分からない（2.2）。ファイルシステムが時刻を進める間隔より短い間の書き込みは見逃しうる。見逃しても、SQLite が確定済みの中身だけを読ませるので、壊れた中身を読むことは無い。1 回の表示が、その瞬間より少し前の状態になるだけ
- **ロック**: WAL 方式では、読む側は書く側を待たせない。ただし、ほかに開いている接続が無いとき、SQLite は開いた直後に `-shm` を作り直す間だけロックを取る。その一瞬に dnf が開こうとすると、dnf の側が少し待つことがありうる。逆に Tojimari の側がロックを取れなければ、待たずに `query_failed` で代わりの判定になる
- **SQLite の版**: 2 の結果は手元の 3.45.1 のもの。AlmaLinux 10.2 の版では確かめていない（10 で確かめる）

### 9.2 採らなかった案

- **`-shm` が無く `-wal` も無い・空のときは `immutable=1` で読む**: 正しく読めて何も作られないが、本人の決定の文言（`-shm` が無いときは開かない）と食い違うので、設計では決めない（9.1 の 1 つ目）
- **URI に `readonly_shm=1` を足す**: 手元では、root でも `-shm` を作らず書き換えずに `-wal` の中身まで読めた。ただし SQLite の文書に載っていない指定で、版によって動きが変わりうる。本人が決めたのは「dnf と同じ正規の読み方」なので採らない。`-shm` に触れないことを優先したくなったときの候補として残す
- **実行部で `BEGIN` を投げて、問い合わせ全体を 1 つの読み取りにまとめる**: SQL を足すことになり、読んでいる間ロックを持ち続ける。問い合わせは、1 番の処理（古くて変わらない）と、SELECT 1 つ（最後に更新した日）だけなので、要らない
- **SQLite の「ロックが取れない」を `busy` に出し分ける**: 起きるのは一瞬の重なりだけで、テストで再現しにくい。`query_failed` のままにする
- **WAL 方式でないときも `mode=ro` で開く**: 3.5 のとおり

## 10. 実機での確認（PR に書く手順）

task-issue-25.md の 7 の手順に、次を足す。どれも読むだけ。出るのは固定のパス、大きさ、ハッシュ値、版の番号で、ホスト名や利用者名は出ない。dnf を動かしていないときに行う。

| 記号 | コマンド | 確かめること |
|---|---|---|
| A | `python3 -c "import sqlite3; print(sqlite3.sqlite_version)"` | SQLite の版（手元は 3.45.1） |
| B | `sudo stat -c '%n %s' /var/lib/dnf/history.sqlite*` と `sudo sha256sum /var/lib/dnf/history.sqlite /var/lib/dnf/history.sqlite-wal` を、`sudo python3 -B -m tojimari check` の前と後に実行する | ファイルの名前の一覧が同じ。本体と `-wal` の大きさとハッシュ値が同じ（`-shm` は比べない） |
| C | `sudo python3 -B -m tojimari check` | 後から入れたものが 15 件（spec-1.1.md の 7）。最後に更新した日が出る。`[注意]` に `history_fallback` の文が無い |
| D | `sudo python3 -B -m tojimari check --json` | `checks.user_installed.method` が `history` |
| E | `python3 -B -m tojimari check`（root なし）の前後で `sudo stat -c '%n %s' /var/lib/dnf/history.sqlite*` | ファイルの一覧が変わらない。履歴が読めるか、「読む権限が無い」の注意で代わりの判定になるかのどちらか（ファイルの権限しだい） |

見込みと違ったとき:

- B でファイルが増えた、本体か `-wal` が変わった → 2 の結果が AlmaLinux の SQLite の版に当てはまっていない。結果を伝えてほしい（設計を直す）
- C で「補助ファイル（-shm）が無かった」などの注意が出る → 9.1 の 1 つ目。`stat` の結果と一緒に伝えてほしい

# 設計: 古さの表示（issue #13、1.1-B）

- 作成日: 2026-11-22
- 書いた人: テックリード
- 関連: [task-issue-13.md](task-issue-13.md)（要件）、[output-1.1.md](output-1.1.md) の 2.4・2.7・3.4（注意、JSON、表）、[design-issue-12.md](design-issue-12.md)（dnf 履歴の開き方。今回もそのまま使う）、[design-issue-5.md](design-issue-5.md)（土台の設計）
- 位置付け: JSON、表、注意の形は output-1.1.md のまま変えない。この文書は「どう作るか」だけを決める。要件に書かれていない細部は 8 に、手元で確かめられていないことは 9 にまとめた

## 1. 全体の形

design-issue-12.md の一方向の流れのまま、モジュールを 2 つ足す。

```
実行部（runner）           外部コマンド、OS、データベースのファイルに触れるのはここだけ
   ↓ 文字列 / 行
読み取り部                 決めた形のものを、データに直す。何も実行しない
  packages                 dnf のセキュリティ更新の問い合わせの形と、その読み取りを足す
  history                  「最後に版を上げた処理」の SQL と行の読み取りを足す
  rpmver（新しく作る）     rpm の版の比べ方（文字列の計算だけ）
   ↓ データ
組み立て
  staleness（新しく作る）  checks.staleness の 3 項目の組み立てと、取れなかった理由
  check                    staleness を呼び、レポートと notices に足す
   ↓ レポート
出力（cli / table）        table に [古さ] を足す。cli は変えない
```

- `check.py` に 3 項目を全部足すと長くなり、重点リスト・後から入れたものと混ざって読みにくくなるので、古さの組み立ては `staleness.py` に分ける
- 版の比べ方は、問い合わせの形でも組み立てでもない純粋な計算で、1.1 のほかの所（版の並び）でも後で使えるので `rpmver.py` に分ける
- 新しい依存は無い。足す標準ライブラリは `re`（パッケージ名の形の確かめ）と `functools`（`cmp_to_key`）だけ

## 2. セキュリティ更新

### 2.1 dnf の呼び方（決めたこと）

最大 5 回、次の形で呼ぶ。違うのは絞り込みの指定 1 つだけ。

```
/usr/bin/dnf repoquery --upgrades --cacheonly --quiet
    --setopt=*.skip_if_unavailable=0
    <絞り込み>
    --queryformat "%{name}\n"
```

| 回 | 絞り込み | 取るもの |
|---|---|---|
| 1 | `--security` | セキュリティ更新が出ている名前の集まり（S） |
| 2〜5 | `--sec-severity=Critical`、`=Important`、`=Moderate`、`=Low`（`--security` は付けない） | その重要度の勧告が出ている名前の集まり |

- 名前の重要度は Tojimari の側で決める。重い順（Critical、Important、Moderate、Low）に見て、「その重要度の集まり」と S の両方に入っている名前を、まだ割り当てていなければその重要度にする。どれにも当たらなかった S の名前は `unspecified`
- 件数（`total`）は S の名前の数。重要度ごとの数の合計はいつも `total` と一致する
- S が空なら 2〜5 は呼ばない（0 件の `ok`）。更新が済んでいる普段の状態では dnf の呼び出しが 1 回で済む
- どれか 1 回でも失敗したら、そこで止めて残りは呼ばず、全体を `unavailable` にする（task-issue-13.md の 3.1 の 5）
- 引数はすべて Tojimari が決めた固定の文字列。外から来た文字列を引数に入れない

### 2.2 理由

**`--security` と `--sec-severity` を同じ呼び出しに並べない。** task-issue-13.md の 2 は「`--security` に、重要度ごとに `--sec-severity` を足す」としているが、dnf 4 はこの 2 つを「どちらかに当たるもの」（和）として扱うと見込んでいる。その場合、並べると重要度で絞られず、4 回ともセキュリティ更新の全部が返り、全部の名前が Critical に数えられてしまう。手元に dnf が無く確かめられないので、「両方に当たるもの」（積）であっても「どちらかに当たるもの」であっても同じ答えになるよう、1 回に 1 つの指定だけを渡し、重ね合わせは Tojimari の側で行う。取るもの（名前と重要度）は要件のままで、変えたのは呼び方だけ（8.1）。

**重要度の書き方は先頭だけ大文字（`Critical` など）。** dnf 4 の `--sec-severity` が受け付ける値はこの 4 つと見込んでいる。書き方が違っていた場合、dnf は引数の誤りとして 0 でない終了コードで終わるので、`unavailable` になる（黙って 0 件にはならない）。

**`--setopt=*.skip_if_unavailable=0`。** dnf は、リポジトリの設定で `skip_if_unavailable` が有効だと、キャッシュの無いリポジトリを飛ばして終了コード 0 で終わる。そのままだと「0 件」に見えるので、この実行のときだけ全部のリポジトリ（`*`）で無効にし、キャッシュが 1 つでも無ければ dnf が失敗するようにする。dnf の設定ファイルは変えない。値は大文字小文字の読み方に左右されない `0` にした。リポジトリごとの設定は全体の設定より優先されるので、`--setopt=skip_if_unavailable=0`（全体）ではなくリポジトリを指す `*.` の形にした。

**書式は名前だけ（`%{name}\n`）。** 件数は名前の数で、更新後の版は出さない（task-issue-13.md の 4）ため。同じ名前の版が複数返っても、名前の集まりにするので 1 つに数える。

**読み取りは厳しくする。** 空行は飛ばし、それ以外の行が 1 つでもパッケージ名の形（英数字で始まり、英数字と `.` `_` `+` `-` だけ）でなければ、読み取り失敗として `unavailable` にする。重点リストの読み取り（形の違う行は飛ばす）と違い、ここでは飛ばすと「0 件」に倒れるため。

**rpm の記録との突き合わせはしない。** `--upgrades` は dnf の決まりで「入っているものの更新」だけを返す。Tojimari の側でもう一度判定すると、dnf の判定とずれうる（task-issue-13.md の 2 で `updateinfo.xml` を直接読まないのと同じ理由）。

### 2.3 分かっている限界（出力の意味）

- 重ね合わせは名前の単位。ある名前にセキュリティの勧告（Moderate）と、重要度の付いたセキュリティ以外の勧告（Important）が同時に出ていると、その名前は Important に数えられる。セキュリティ以外の勧告に重要度が付くことは少ないと見込んでいる
- 数えられるのは、リポジトリが更新情報（勧告）を配っているものだけ。更新情報を配っていないリポジトリ（外部のリポジトリに多い）から入れたものは、更新が出ていてもここには出ない。この点を注意の文に足すかは PM が決める（10）
- 有効なリポジトリが 1 つも無いときは 0 件の `ok` になる。開発用の VM では考えにくいので、今回は扱わない

### 2.4 時間の見込み

- 1 回の `dnf repoquery --cacheonly` は、キャッシュの読み込みが大半で、数秒と見込んでいる（実測は 9 の D）。今までの 2 回（入れた元、後から入れたもの）に、普段は 1 回、セキュリティ更新があるときは 5 回が加わる。全体で 10〜30 秒の見込み
- 1 回ごとの上限は今までと同じ `DNF_TIMEOUT`（60 秒）。失敗したらそこで止めるので、dnf が固まっている場合の待ちは 60 秒で済む。5 回とも上限ぎりぎりで成功した場合は理屈の上で 300 秒かかるが、全体の締め切りを別に作ると実行部に時刻の管理が増えるので、今回は作らない。実測が長ければ見直す
- 4 回を同時に走らせることはしない（dnf を並べて動かしたときの振る舞いを確かめられないため）

## 3. 再起動待ち

### 3.1 版の比べ方（`rpmver.py`）

```python
def vercmp(a: str, b: str) -> int      # a が新しければ 1、同じなら 0、古ければ -1
def compare_evr(a, b) -> int           # epoch、version、release の順。a、b は .epoch .version .release を持つもの
```

`vercmp` は rpm の比べ方（rpmvercmp）の手順をそのまま書く。

1. 2 つが同じ文字列なら 0
2. どちらかに文字が残っている間、次を繰り返す
   1. 両方の先頭から、英数字（ASCII）でも `~` でも `^` でもない文字を飛ばす
   2. どちらかの先頭が `~` のとき: 片方だけなら `~` のあるほうが古い。両方なら 1 文字ずつ進めて 2 の先頭へ
   3. どちらかの先頭が `^` のとき: `^` でないほうが終わりに達していれば、`^` のあるほうが新しい。そうでなく片方だけなら、`^` のあるほうが古い。両方なら 1 文字ずつ進めて 2 の先頭へ
   4. どちらかが終わりに達していれば、繰り返しをやめる
   5. a の先頭が数字なら両方から数字の続きを、そうでなければ両方から英字の続きを切り出す
   6. b の切り出しが空なら（種類が違う）: 数字を切り出していたなら a が新しい、英字なら a が古い
   7. 数字なら、先頭の 0 を落とし、桁数の多いほうが新しい
   8. 文字列として比べ、違えばその結果を返す
3. 両方とも終わりなら 0。残っているほうが新しい

- 英数字の判定は ASCII だけにする（`str.isalnum` は全角なども真にするので使わない）
- `compare_evr` の epoch は、無ければ 0 として整数で比べる。同じなら version、次に release を `vercmp` で比べる
- `python3-rpm`（`rpm.labelCompare`）は標準ライブラリでないので使わない（マニフェストの 4）

この手順を手元で試しに書き、6.2 の表の組がすべて表のとおりになることを確かめた。ただし手元に rpm が無いので、rpm 本体の結果とは突き合わせていない（9 の E）。

### 3.2 判定（`staleness.build_reboot`）

入力は rpm の一覧（#5 の `parse_rpm_list` の結果）と、動いているカーネル（`system.running_kernel()`）だけ。

1. 動いているカーネルが取れていなければ `unknown`、`latest_kernel` は null
2. 「同じアーキテクチャの版」= 名前が `kernel` で、動いているカーネルの文字列が `.<その版の arch>` で終わるもの。1 つも無ければ `unknown`、`latest_kernel` は null
3. 2 の中で `compare_evr` がいちばん大きいものを `latest_kernel`（`version-release.arch`。epoch は付けない）とする
4. 2 の中で `version-release.arch` が動いているカーネルと一致するものを、動いている版とする。無ければ `unknown`（`latest_kernel` は 3 の値を入れる）
5. 3 が 4 より新しければ（`compare_evr` が 1）`pending`、そうでなければ `not_pending`

- `kernel-64k` やデバッグ用のカーネルで動いているときは、動いているカーネルの文字列の終わりがアーキテクチャでない（`+64k` などが付く）ので、2 で `unknown` になる（task-issue-13.md の 3.2 の 4）
- 今ある注意 `running_kernel_not_found` は変えない。`unknown` のときは両方出ることがある

## 4. 最後に更新した日

### 4.1 SQL と値（`history.query_last_upgrade`）

```python
LAST_UPGRADE_COLUMNS = {
    "trans": ("id", "dt_begin", "dt_end", "state"),
    "trans_item": ("trans_id", "action"),
}
TRANS_STATE_DONE = 1          # libdnf の TransactionState の DONE
ITEM_ACTION_UPGRADE = 6       # libdnf の TransactionItemAction の UPGRADE（上げた先の版の側）

def query_last_upgrade(execute) -> int | None
    """版を上げる項目を含み、最後まで終わった処理のうち、いちばん新しいものの時刻
    （UNIX 時刻、秒）。当てはまる処理が無ければ None。読めなければ HistoryError。"""
```

手順:

1. `LAST_UPGRADE_COLUMNS` の列があるかを、#12 と同じ `PRAGMA table_info` で確かめる。無ければ `HistoryError("missing_columns")`。#12 の確かめと同じ処理なので、内部の関数 1 つにまとめる（`query_first_transaction` の結果は変えない）
2. 次の SQL（定数）を投げる

```sql
SELECT trans.dt_begin, trans.dt_end FROM trans
WHERE trans.state = 1
  AND EXISTS (SELECT 1 FROM trans_item
              WHERE trans_item.trans_id = trans.id AND trans_item.action = 6)
```

3. 0 行なら `None`（「更新の記録が無い」）
4. 各行の時刻を決める。`dt_end` が使える値ならそれ、そうでなければ `dt_begin`。使える値とは、整数（真偽値は除く）で、0 より大きく 253402300799（9999 年の終わり）以下のもの。どちらも使えない行は捨てる
5. 残った時刻のいちばん大きいものを返す。行はあったのに 1 つも残らなければ `HistoryError("no_usable_time")`（「記録が無い」とは言えないので、確認できなかったとする）

決めた理由:

- **値の意味（1 と 6）。** libdnf が履歴に書く番号で、処理の状態は 0 = 不明、1 = 完了、2 = エラー、項目の動作は 1 = 入れる、2・3 = 版を下げる、4・5 = 置き換え、6 = 版を上げる（新しい側）、7 = 版を上げられる（古い側）、8 = 消す、9・10 = 入れ直す、11 = 理由の変更、と見込んでいる。手元に libdnf が無く、#10 で本人が確かめたのは列があることだけなので、値は実機確認（9 の F、task-issue-13.md の 7 の手順 6・7）で確かめる
- **6 だけを見る。** 版を上げた処理には 6 と 7 が対で入るので、6 があれば足りる
- **`trans_item.state` は使わない。** 処理が最後まで終わった（`trans.state` が 1）ことで足り、確かめきれていない値を 1 つ減らせる
- **「いちばん新しい」は時刻で決める**（id の大きさではなく）。出すのが時刻なので
- **時刻は秒の整数と見込む。** 範囲を決めておくので、日時への変換で例外は起きない

分かっている限界: kernel は古い版を残して新しい版を足す入れ方をするので、履歴では「入れる」（1）になると見込んでいる。kernel だけを上げた処理（6 の項目が 1 つも無い処理）は「更新した」に数えられない。普通の `dnf upgrade` は kernel 以外も一緒に上げるので、影響は小さいと見込む。要件の定義（版を上げる項目を含む処理）のとおりに作り、PM に伝える（10）。

### 4.2 データベースは #12 と別に開く

`System.history_last_upgrade()` は `read_history_db(history.DB_PATH, history.query_last_upgrade)` とし、#12 の `history_first_names()` とは別に開く（1 回の実行で最大 2 回開く）。

- 理由: 3 つを別々に取る（output-1.1.md の 2.7）ため。#12 は「後から入れたものの一覧が取れなければ履歴を開かない」作りで、1 回にまとめるとこの流れと失敗の扱いを組み替えることになる。まとめなければ #12 のコードと判定は 1 行も変わらない
- 開くのは `os.stat` 数回と読み取りだけで一瞬。開き方（`mode=ro&immutable=1`、前後の確かめ）は `read_history_db` をそのまま使うので、書き込みをしないことも #12 と同じ
  - #25 で変えた（2026-11-27）: WAL 方式のときは `mode=ro` だけで開き、`-wal` の中の記録も読む。既にある `-shm` に SQLite が触れることは受け入れる（[design-issue-25.md](design-issue-25.md)）。`read_history_db` をそのまま使うことは変わらない
- 2 回の間に dnf が履歴を書くと、2 つが別の時点を見ることはありうる。それぞれの中身は食い違わない

### 4.3 組み立て（`staleness.build_last_update`）

- 時刻があれば `ok`。`at` は UTC の ISO 8601（`generated_at` と同じ書き方）、`days_ago` は `now - at` の日数（切り捨て）。VM の時計のずれで `at` が `now` より先のときは 0 にする
- `None` なら `none`、`HistoryError` なら `unavailable`。どちらも `at` と `days_ago` は null

## 5. ファイルと関数

### 5.1 変えるファイル

| ファイル | すること |
|---|---|
| `tojimari/rpmver.py` | 新しく作る。3.1 |
| `tojimari/staleness.py` | 新しく作る。5.5 |
| `tojimari/packages.py` | セキュリティ更新の引数と読み取りを足す。5.2 |
| `tojimari/history.py` | `query_last_upgrade` と理由を足す。5.3 |
| `tojimari/runner.py` | `System` にメソッドを 2 つ足す。5.4 |
| `tojimari/check.py` | `staleness.collect` を呼び、`checks.staleness` と notices に足す。5.6 |
| `tojimari/notices.py` | 注意を 4 つ足す。`command_reason` を移す。5.7 |
| `tojimari/table.py` | `[古さ]` を足す。7.2 |
| `tests/recorded.py`、`tests/test_*.py` | 6 のとおり。`tests/test_rpmver.py`、`tests/test_staleness.py` を新しく作る |

`cli.py`、`__main__.py`、`__init__.py` は変えない。

### 5.2 `packages.py`

```python
SEVERITIES = ("Critical", "Important", "Moderate", "Low")    # dnf に渡す書き方。重い順

def dnf_security_upgrades_argv(severity: str | None) -> list[str]
    """None なら --security、SEVERITIES の値なら --sec-severity=<値>。それ以外は ValueError。"""

def parse_dnf_names(text: str) -> frozenset[str]
    """空行を飛ばし、名前の集まりを返す。名前の形でない行があれば ParseError。"""
```

- 引数の並びは 2.1 のとおり。`--queryformat` の値は本物の改行を含む `"%{name}\n"`（今ある `DNF_QUERYFORMAT` と同じ流儀）
- 名前の形は `re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", line)`。行の前後の空白は落とさない（空白を含む行は読み取り失敗にする）
- 0 行（空の出力）は空の集まりを返す（`parse_rpm_list` と違い、0 件は正しい結果）
- 今ある `_dnf_repoquery_argv`、`DNF_USERINSTALLED_ARGV`、`dnf_from_repo_argv` の結果は変えない

### 5.3 `history.py`

- `query_last_upgrade` と定数（4.1）を足す。`PRAGMA table_info` は固定の文字列の表（`_TABLE_INFO_SQL`）のまま使う
- `_REASONS` に `no_usable_time`: 「dnf 履歴の処理の時刻を読み取れなかった」を足す
- `HistoryError` の説明文を「dnf 履歴が取れなかった」だけにする（代わりの判定は #12 の側の話なので）
- 今までどおり `sqlite3`、`os`、`subprocess` を import しない

### 5.4 `runner.py`

```python
class System:
    def dnf_security_upgrades(self, severity=None) -> str   # packages.dnf_security_upgrades_argv(severity) を DNF_TIMEOUT で実行
    def history_last_upgrade(self)                          # read_history_db(history.DB_PATH, history.query_last_upgrade)
```

`run_command`、`read_history_db` は変えない。

### 5.5 `staleness.py`（組み立て。新しく作る）

```python
SEVERITY_KEYS = ("critical", "important", "moderate", "low", "unspecified")

def build_security_updates(security_names, severity_names) -> dict
    """security_names が None なら unavailable。severity_names は {"critical": 名前の集まり, ...}（4 つ）。"""

def build_reboot(installed, running_kernel) -> tuple[dict, str | None]
    """(reboot, unknown のときの理由)。3.2。"""

def build_last_update(timestamp, now) -> dict
    """timestamp が None なら none。4.3。"""

def collect(system, installed, running_kernel, now) -> tuple[dict, dict]
    """(checks.staleness, 理由の dict)。理由の dict のキーは
    "security_updates"、"reboot"、"last_update"。取れたものの値は None。"""
```

`collect` の決まり:

- 3 つを順に、それぞれ別の `try` で取る。1 つの失敗をほかに広げない。捕まえるのは `CommandError`、`packages.ParseError`、`history.HistoryError` だけ（ほかの例外は不具合なので隠さない）
- セキュリティ更新: `system.dnf_security_upgrades(None)` → `parse_dnf_names`。空でなければ `packages.SEVERITIES` の順に 4 回。JSON のキーは dnf の書き方を小文字にしたもの
- 理由の文は 7.3 の表の文だけにする。dnf の標準エラー出力、例外の文字列、パスを入れない
- `staleness.py` は `subprocess`、`sqlite3`、`os` を import しない

`build_security_updates` の結果:

- `ok`: `total`、`by_severity`（5 つのキーを `SEVERITY_KEYS` の順でいつもそろえる）、`packages`（`{"name", "severity"}`。重要度の重い順、同じ重要度の中では名前の文字列の昇順）
- `unavailable`: `{"status": "unavailable", "total": None, "by_severity": None, "packages": []}`

### 5.6 `check.py`

- `collect` の中で、後から入れたものの後に `staleness.collect(system, installed, running_kernel, now)` を呼ぶ。`checks` のキーの順は `focus_packages`、`user_installed`、`staleness`
- `_command_reason` は `notices.command_reason` に移し、`check.py` と `staleness.py` の両方から使う（`staleness.py` が `check.py` を import すると、互いに import し合うことになるため）。文は変えない
- 終了コード、`CheckError` は変えない

### 5.7 `notices.py`

`build_notices` に、名前付きの引数を 4 つ足す（今ある引数と順は変えない）。

```python
security_updates_ok: bool = False,
security_updates_problem: str | None = None,
reboot_problem: str | None = None,
last_update_problem: str | None = None,
```

並びは output-1.1.md の 2.4 の表の順（`user_installed_unavailable` の後に、下の表の順）。

| `id` | 出す条件 | 文言 |
|---|---|---|
| `security_updates_cache` | `security_updates_ok` が真 | セキュリティ更新の数は、dnf が手元に持っているリポジトリ情報（最後に取得した時点のもの）にもとづいており、最新とは限りません。Tojimari はリポジトリ情報を取り直しません。最新にするには、先に sudo dnf makecache を実行してください。 |
| `security_updates_unavailable` | `security_updates_problem` が `None` でない | リポジトリ情報を確認できなかったため（理由: <理由>）、セキュリティ更新があるかどうかは分かりません。「更新なし」という意味ではありません。dnf が手元にリポジトリ情報を持っていないときは、sudo dnf makecache を実行した後に確かめ直せます。 |
| `reboot_unknown` | `reboot_problem` が `None` でない | 再起動待ちかどうかを確認できませんでした（理由: <理由>）。「再起動待ちではない」という意味ではありません。 |
| `last_update_unavailable` | `last_update_problem` が `None` でない | dnf 履歴から最後に更新した日を確認できませんでした（理由: <理由>）。 |

## 6. テストの方針

- 標準ライブラリと `unittest` だけ。リポジトリの最上位で `python3 -m unittest` が全部通ること
- rpm、dnf を呼ばない。実機の `/var/lib/dnf/history.sqlite` を開かない
- テスト用データは全部架空。時刻は決めた UTC の日時から作る

### 6.1 `tests/recorded.py`

- `FakeSystem` に引数を 2 つ足す
  - `security`: `{None または重要度: 返す文字列か例外}`。既定は、S が `openssl-libs`、`git`、`bash`（空行まじり）、Important が `openssl-libs`、Moderate が `git` と `openssl-libs`、Critical と Low が空（→ openssl-libs は important、git は moderate、bash は unspecified）
  - `last_upgrade`: 返す整数、`None`、または例外。既定は 2026-11-20 10:00:00 UTC の UNIX 時刻（`datetime` から作る）
  - `dnf_security_upgrades(severity=None)` は、呼ばれた引数を順に `security_calls` に覚える
- 履歴のデータベースを作る関数に、処理ごとの `dt_begin`、`dt_end`、`state` と、項目ごとの `action` を入れられるようにする（テーブルを作る部分は今ある `make_history_db` と共通にする。今ある呼び方の結果は変えない）
- 既定の `FakeSystem` では `security_updates_cache` の注意が 1 つ増える。注意の数や並びを固定で見ている今あるテスト（`test_always_three_and_order`、`test_order_with_all`、`test_notice_order` など）と、`test_no_future_keys`（`staleness` が無いことを見ている）は、新しい決まりに合わせて書き換える。それ以外の今あるテストはそのまま通ること

### 6.2 確かめること

| テスト | 確かめること |
|---|---|
| `test_rpmver.py` | 下の表の組が、表のとおりになること。入れ替えると符号が逆になること。`compare_evr`: epoch が先（`1:1.0-1` は `2.0-1` より新しい）、epoch 無しは 0 と同じ、version が同じなら release で決まる（`55.el10` < `100.el10`、`55.el10` < `55.el10_0.1`） |
| `test_packages.py` | `dnf_security_upgrades_argv(None)` が絶対パス、`repoquery`、`--upgrades`、`--cacheonly`、`--quiet`、`--setopt=*.skip_if_unavailable=0`、`--security`、`--queryformat` と `"%{name}\n"` を含み、`--sec-severity` を含まないこと。重要度を渡すと `--sec-severity=<値>` を含み `--security` を含まないこと。知らない値（小文字の `critical` を含む）で `ValueError`。`parse_dnf_names`: 空行を飛ばす、重複は 1 つ、空の出力は空の集まり、空白やタブやコロンを含む行・`-` で始まる行で `ParseError`。今ある引数の並びが変わっていないこと |
| `test_history.py` | 6 の項目を含む完了の処理のうち、時刻がいちばん大きいものが返ること（id の順と時刻の順が違う組を入れる）。`state` が 1 でない処理は数えない。6 を含まない処理（1 だけ、7 だけ、8 だけ）しか無ければ `None`。処理が 1 件も無ければ `None`。`dt_end` が 0・NULL・文字列のとき `dt_begin` を使う。どちらも使えない行しか無ければ `no_usable_time`。`trans.state`、`trans.dt_end`、`trans_item.action` の列が無い、テーブルが無い → `missing_columns`。`reason_text("no_usable_time")`。`query_first_transaction` の今あるテストがそのまま通ること |
| `test_runner.py` | 一時ディレクトリのデータベースを `read_history_db(path, history.query_last_upgrade)` で読めて、前後でディレクトリのファイルの一覧が同じであること。`System` のメソッドは呼ばない |
| `test_staleness.py` | セキュリティ更新: 重要度ごとの数え分け、複数の重要度に当たる名前は重いほうだけ、どれにも当たらない名前は `unspecified`、S に無い名前が重要度の集まりにあっても数えない、合計が `total` と一致、並び、5 つのキーがそろう、0 件は `ok` で重要度の呼び出しをしない（`security_calls` が `[None]`）、1 回目・途中の回の `CommandError`（4 種類）と `ParseError` で `unavailable` になり、その後の回を呼ばない。再起動待ち: `pending`、`not_pending`、動いている版が記録に無い（`unknown` で `latest_kernel` は入る）、動いているカーネルが `None`、kernel が入っていない、アーキテクチャの違う版は比べない（新しい別アーキの版があっても `not_pending`）、`+64k` の付いた文字列は `unknown`、桁数の違う release（`9.el10` と `10.el10`）で文字列の順ではなく rpm の順になること。最後に更新した日: `ok` の `at` と `days_ago`（ちょうど 2 日、2 日に 1 秒足りない → 1、先の時刻 → 0）、`None` → `none`、`HistoryError` の各 `kind` → `unavailable` と理由。3 つのうち 1 つが失敗しても、ほかの 2 つが出ること（3 通り） |
| `test_check.py` | `checks` のキーの順。`staleness` のキーの順（`security_updates`、`reboot`、`last_update`）と各項目のキーの順が output-1.1.md の 2.7 のとおり。`reboot.running_kernel` が `system.running_kernel` と同じ。4 つの注意が条件どおりに出る・出ないことと並び。セキュリティ更新が `unavailable` でも重点リストと後から入れたものが今までどおりで、例外にならないこと。dnf の標準エラー出力がレポートに入らないこと |
| `test_table.py` | 7.2 のとおり。`[古さ]` が `[後から入れたもの]` の後、`[注意]` の前。output-1.1.md の 3.4 の例と同じレポートから、例と同じ行が出ること。0 件、`unavailable`（「0 件」「更新なし」が出ない）、`pending`・`not_pending`・`unknown`、値が null のとき `-`、`ok`・`none`・`unavailable`、長い名前で列がそろうこと、`staleness` が無いレポートで何も出さずに続くこと、今ある表の部分が変わらないこと |
| `test_cli.py` | `check --json` に `checks.staleness` があること。「保証」などの言葉が無いことの今あるテストに、新しい 4 つの注意と `[古さ]` を含めること |

`vercmp(a, b)` の組（3.1 の手順から決まる答え）:

| a | b | 結果 | a | b | 結果 |
|---|---|---|---|---|---|
| `1.0` | `1.0` | 0 | `1.0~rc1` | `1.0` | -1 |
| `1.0` | `2.0` | -1 | `1.0~rc1` | `1.0~rc2` | -1 |
| `2.0.1` | `2.0` | 1 | `1.0~rc1~git123` | `1.0~rc1` | -1 |
| `9` | `10` | -1 | `1.0^` | `1.0` | 1 |
| `5.5p1` | `5.5p2` | -1 | `1.0^git1` | `1.0` | 1 |
| `5.5p10` | `5.5p1` | 1 | `1.0^git1` | `1.0^git2` | -1 |
| `10xyz` | `10.1xyz` | -1 | `1.0^git1` | `1.01` | -1 |
| `xyz10` | `xyz10.1` | -1 | `1.0^20160101` | `1.0.1` | -1 |
| `xyz.4` | `8` | -1 | `1.0~rc1^git1` | `1.0~rc1` | 1 |
| `6.0.rc1` | `6.0` | 1 | `1.0^git1~pre` | `1.0^git1` | -1 |
| `10b2` | `10a1` | 1 | `10.0001` | `10.1` | 0 |
| `1.0aa` | `1.0a` | 1 | `10.0001` | `10.0039` | -1 |
| `1.0` | `1.0a` | -1 | `2_0` | `2.0` | 0 |
| `1.0a` | `1.0.1` | -1 | `a+` | `a_` | 0 |
| `4.999.9` | `5.0` | -1 | `+_` | `_+` | 0 |
| `6.12.0` | `6.9.0` | 1 | `8.p5.el10` | `8.el10` | 1 |

## 7. 出力の形

### 7.1 JSON

output-1.1.md の 2.7 のとおり。`schema_version` は 1 のまま（項目を足すだけ）。取れなかったときの形:

```json
"staleness": {
  "security_updates": {"status": "unavailable", "total": null, "by_severity": null, "packages": []},
  "reboot": {"status": "unknown", "running_kernel": null, "latest_kernel": null},
  "last_update": {"status": "unavailable", "at": null, "days_ago": null}
}
```

`last_update` が `none` のときも `at` と `days_ago` は null。

### 7.2 表（output-1.1.md の 3.4 に書かれていない細部）

- `checks` に `staleness` が無ければ何も出さない。あれば、前の表との間に空行 1 つ、見出しの行 `[古さ]`、続けて 3 項目をこの順に出す。`staleness` の中に無い項目の行は出さない
- 1 列目の幅は、3 つの行の見出しと「空白 2 つ + 名前」のうち、いちばん広い表示幅にそろえる。1 列目と 2 列目の間は空白 4 つ（3.4 の例と同じ並びになる）。行末の空白は付けない
- セキュリティ更新
  - `ok` で 1 件以上: `N 件（Critical a、Important b、Moderate c、Low d、重要度なし e）`。続けて `packages` の順に、空白 2 つ + 名前、重要度の表記
  - `ok` で `total` が 0: `0 件` だけ
  - `ok` 以外（`unavailable` と知らない値）: `確認できませんでした`。`total` や `packages` は見ない
  - 重要度の表記は `Critical`、`Important`、`Moderate`、`Low`、`重要度なし`。知らない値はそのまま出す
- 再起動待ち: `<状態>（動いている <running_kernel>、入っている最新 <latest_kernel>）`。状態は `pending` が「再起動待ち」、`not_pending` が「再起動待ちではない」、それ以外は「確認できませんでした」。null は `-`
- 最後に更新した日: `ok` は `YYYY-MM-DD HH:MM UTC（N 日前）`（見出しの時刻と同じ書き方）、`none` は「更新の記録がありません」、それ以外は「確認できませんでした」
- 表に出すのはレポートの中身だけ。表の側で数え直さない（件数は `total`、内訳は `by_severity` をそのまま出す）

### 7.3 取れなかったときの理由（注意に入れる文）

終了コードは変えない。今回足すものはどれも 0 のまま続ける。

| 項目 | 起きたこと | 理由の文 |
|---|---|---|
| セキュリティ更新 | dnf が無い、時間内に終わらない、終了コードが 0 でない、実行できない | 重点リストと同じ文（`command_reason("dnf", 60, err)`） |
| セキュリティ更新 | 名前の形でない行があった | dnf の出力を読み取れなかった |
| 再起動待ち | 動いているカーネルが取れない | 動いているカーネルを取得できなかった |
| 再起動待ち | 同じアーキテクチャの kernel が 1 つも無い | rpm の記録に、動いているカーネルと同じアーキテクチャの kernel が無かった |
| 再起動待ち | 動いている版が記録に無い | 動いているカーネルが、rpm の記録にある kernel の版の中に見つからなかった |
| 最後に更新した日 | `HistoryError` | `history.reason_text(err.kind)`（design-issue-12.md の 5.2 の表と、今回足した `no_usable_time`） |

キャッシュが無いときは、dnf が 0 でない終了コードで終わる見込みなので、理由は「dnf が終了コード N で終わった」になる。dnf の標準エラー出力は形を決められないので出力に入れず、そのかわり注意の文に `sudo dnf makecache` の案内を入れた（5.7）。

## 8. 要件に書かれていない細部（今回決めたこと）

JSON、表、注意の出す条件は変えていない。PM が要件や出力仕様に取り込むかを決める。

1. **dnf の呼び方。** task-issue-13.md の 2 と spec-1.1.md の 2.3 は「`--security` を重要度ごとに呼ぶ」と書いているが、`--security` だけの 1 回と、`--sec-severity` だけの 4 回に分け、重ね合わせを Tojimari の側で行う（2.2）。取るものと出力は同じ
2. **dnf の出力に読めない行が 1 つでもあれば `unavailable`**（2.2）
3. **S が空なら重要度の問い合わせをしない**（2.1）
4. **再起動待ちの「同じアーキテクチャ」は、動いているカーネルの文字列の終わりで決める**（3.2）
5. **`at` が今より先のとき `days_ago` は 0**（4.3）
6. **処理に使える時刻が無いときは `unavailable`**（`none` にしない。4.1）
7. **`security_updates_unavailable` の文に `sudo dnf makecache` の案内を足した**（5.7）
8. **履歴のデータベースは #12 と別に開く**（4.2）

## 9. 手元で確かめられていないこと（実機確認の手順に入れる）

手元（クラウド実行環境）には dnf、rpm、libdnf が無い。次は task-issue-13.md の 7 の手順に足す・置き換える。セキュリティ担当が PR を作るときに取り込む。どれも読むだけで、出るのはパッケージ名、数、時刻で、それ以外の実機の情報は出ない。

| 記号 | コマンド | 確かめること |
|---|---|---|
| A | `sudo dnf repoquery --upgrades --cacheonly --quiet --setopt='*.skip_if_unavailable=0' --security --queryformat $'%{name}\n' \| cat -A \| head -20; echo "exit=${PIPESTATUS[0]}"`（表の中なので `\|` と書いた。打つときは `|`。task-issue-13.md の 7 の手順 4 の呼び方はこれ） | 終了コードが 0。1 行に名前が 1 つ（空行が挟まるのは見込みどおり）。名前以外の行が出ない。名前が手順 3 の `dnf updateinfo list --security --cacheonly` のパッケージの名前の部分と合う |
| B | A の `--security` を `--sec-severity=Critical`、`=Important`、`=Moderate`、`=Low` に置き換えて 4 回 | 終了コードが 0 で、値ごとに結果が変わる。手順 3 の一覧の重要度と合う |
| C | A に `--sec-severity=Critical` を足して（`--security` と両方）1 回、A から `--security` を外して 1 回 | 両方を付けたときに、A と同じ（和）か、B の Critical と同じ（積）か。外したときにセキュリティ以外の更新も出るか。Tojimari の結果はどちらでも変わらないが、見込み（2.2）が合っていたかを知りたい |
| D | `time` を付けて A を 1 回 | かかった秒数（2.4 の見込みと比べる） |
| E | `rpm --eval '%{lua: print(rpm.vercmp("1.0~rc1", "1.0"), rpm.vercmp("1.0^git1", "1.01"), rpm.vercmp("10.0001", "10.1"), rpm.vercmp("xyz.4", "8"), rpm.vercmp("8.p5.el10", "8.el10"))}'` | `-1 -1 0 -1 1` と出る（6.2 の表と rpm 本体が合う） |
| F | task-issue-13.md の 7 の手順 7（`action` と `state` ごとの数）に続けて、同じ開き方で `select max(dt_end) from trans` | `trans.state` は 1 が大半、`trans_item.action` に 6 と 7 が同じくらいの数ある。`max(dt_end)` が 10 桁の数（秒）である。手順 6 の `dnf history list` と、Tojimari の「最後に更新した日」が合う |
| G | キャッシュの無い状態での確認（task-issue-13.md の 7 の末尾。行うかは本人が決める） | セキュリティ更新が「確認できませんでした」になり、`[注意]` に「dnf が終了コード 1 で終わった」と出る。「0 件」と出たら、`skip_if_unavailable` の指定が効いていないので知らせてほしい |

分かっていないことと、外れたときの動き:

- `repoquery` が `--security`、`--sec-severity` で絞るか → 絞られなければ、全部の更新がセキュリティ更新として出る（多すぎる側に外れる）。A〜C と手順 3 で分かる
- 重要度の書き方 → 違えば dnf が失敗し `unavailable` になる。B で分かる
- `--setopt=*.skip_if_unavailable=0` が効くか → 効かなければ、キャッシュの無いリポジトリが飛ばされ、少なすぎる側（0 件を含む）に外れる。これだけは黙って外れるので、G を行わない場合は、この点を確かめていないことを PR に書いておく
- root なしのときに dnf がどのキャッシュを見るか → 見えなければ `unavailable` になる見込み。手順 9 で分かる
- libdnf の値（1 と 6）→ 違えば「更新の記録がありません」か、違う日が出る。F と手順 6 で分かる
- kernel の更新が履歴で「入れる」になるか（4.1 の限界）→ F の数と `dnf history list` で分かる

## 10. PM に伝えること（設計では決めない）

どれも出力仕様を変えずに作れるので、差し戻しにはしない。本人に聞く必要のあるものは無い。

1. spec-1.1.md の 2.3 の取り方の文（「`--security` を重要度ごとに呼ぶ」）は、8 の 1 に合わせて直したほうが、文書と実装が食い違わない
2. 更新情報を配っていないリポジトリのものは数えられない（2.3）。「0 件」が「更新が無い」と読まれないよう、`security_updates_cache` の注意に一言足すかどうか
3. kernel だけを上げた処理は「最後に更新した日」に数えられない見込み（4.1）。実機確認の結果を見て、定義を見直すかどうか

## 11. 後で足すものとの関係（今回は作らない）

- 今動いているかの印（#14）は作らない
- 版の並び（output-1.1.md の 2.3 は文字列の昇順）を rpm の順に変えることは、今回の範囲の外。`rpmver.py` を使えば後で変えられるが、今回は再起動待ちの判定にだけ使う
- リポジトリ情報を取り直す指定、全体の締め切り時間、dnf の並列実行は作らない

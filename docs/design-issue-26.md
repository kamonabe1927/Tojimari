# 設計: Tojimari 自身を起動した sudo に「今動いている」の印を付けない（issue #26）

- 作成日: 2026-11-27
- 書いた人: テックリード
- 関連: [task-issue-26.md](task-issue-26.md)（要件）、[design-issue-14.md](design-issue-14.md) の 1・4.1・4.4・10（今回変える所）、[output-1.1.md](output-1.1.md) の 2.8
- 位置付け: 出力の形（JSON の項目、表、終了コード、注意の文言）は変えない。変えるのは、印のもとから外すプロセスの決め方と、rpm の記録を引く順番、テスト

差し戻しは無い。task-issue-26.md の要件で設計できる。
この文書の例に出てくるパスと pid はすべて架空のもの。

## 1. 変わること（まとめ）

- `processes.classify` に、`sudo` のパッケージが持つパスの集まり（`sudo_paths`）を渡す。`classify` は Tojimari 自身と子孫に加えて、Tojimari を起動した `sudo` までの列も外す
- `check._collect_running` の順番を「見回し → rpm → 見分け」に変える。今は「見回し → 見分け → rpm」
- rpm の記録で引くパスは、「候補のパス」から「実行ファイルを読めたすべてのプロセスのパス」に変える（新しい `processes.exe_paths`）
- `rpm` の呼び出しは今の 1 回のまま。`runner.py`、`packages.py`、`notices.py`、`table.py`、`cli.py` は変えない

## 2. `sudo` の見分けをどこで行うか

### 2.1 決めたこと

`classify` に `sudo_paths` を渡し、外す pid を `classify` の中で一度に決める。

```
check._collect_running
  ├─ system.process_scan()          … 今のまま
  ├─ processes.exe_paths(scan)      … rpm で引くパスの集まり（新しい）
  ├─ system.rpm_files()             … 今のまま（1 回）
  ├─ packages.parse_rpm_files(text, 引くパス)
  ├─ processes.sudo_paths(file_map) … sudo のパッケージが持つパス（新しい）
  ├─ processes.classify(scan, sudo_paths)
  └─ processes.build_marks(candidates, file_map)
```

### 2.2 理由

考えた形は 3 つ。

| 形 | 採る／採らない理由 |
|---|---|
| A. `classify` に `sudo_paths` を渡す（採る） | 外すプロセスを決める所が 1 か所のまま。外したプロセスは、Tojimari 自身と同じ所（判定のいちばん最初）で飛ばすので、`unreadable` の数え方が要件の 3.3（外したものは数に入れない）のとおりになる。`classify` は今までどおり何も実行せず、渡された値だけで決まるので、架空の値でテストできる |
| B. `classify` は変えず、返した候補から後で pid を引いて外す | 候補に pid を持たせることになり、`build_marks` に渡す形が変わる。また、列の間にあるプロセスが読めなかったとき、すでに `unreadable` に数えた後なので、数を引き直す処理が要る。外す決まりが 2 か所に分かれる |
| C. `classify` を 2 回呼ぶ（1 回目の候補で rpm を引き、2 回目で外す） | 祖先の `sudo` が候補に入らない形（ルートディレクトリが読めない、違う）では `sudo` のパスが引けず、見分けられない。同じ判定を 2 回行う理由も説明しにくい |

A では rpm の記録を先に引く必要があるので、順番が「見回し → rpm → 見分け」になる。困ることは無い。

- 見回しが失敗したら rpm を呼ばないことは変わらない（`exe_paths` は見回しの後）
- rpm が失敗したら `unavailable` で、印は付けず `unreadable` も `null` なので、`classify` を呼ぶ必要が無い（要件 3.2 の 3 つ目）
- 候補が 0 個でも rpm を呼ぶことは変わらない

### 2.3 rpm で引くパス（`exe_paths`）

実行ファイルを読めたすべてのプロセス（`exe_error` が `None` で `exe` が `None` でない）の、` (deleted)` を取り除いたパスの集まり。

- 今より増えるのは、Tojimari 自身と子孫、ルートディレクトリが違うか読めないプロセス、カーネルのスレッドでもゾンビでもないのに候補から外れていたもののパス。数十個ほどで、`parse_rpm_files` の時間と大きさは変わらない
- 増えたパスが印のもとになることは無い。`build_marks` は `classify` が返した候補のパスだけを `file_map` で引く
- 「候補のパスと祖先のパスだけ」に絞る形にしなかった理由: 絞るには `classify` の前に祖先を決めることになり、外す決まりがまた 2 か所に分かれる。全部引いても結果は同じ

### 2.4 `sudo` のパス（`sudo_paths`）

`file_map`（パス → 版のキーの集まり）のうち、名前が `sudo` の版を 1 つでも持つパスの集まり。

- 版のキーの形（先頭が名前）は `packages.version_key` が決めているので、名前で選ぶ関数は `packages.py` に置く（`paths_owned_by(file_map, name)`）。`processes.sudo_paths` はそれを `"sudo"` で呼ぶだけ
- パッケージの名前 `"sudo"` は `processes.py` の定数 `SUDO_PACKAGE` に置く。`check.FOCUS_PACKAGES` から取らない（`processes` は `check` を読み込まない。重点リストから `sudo` を外しても、この決まりは変わらない）
- `sudo` が入っていない、または `sudo` のプロセスが 1 つも動いていなければ空になり、今までどおり Tojimari 自身と子孫だけが外れる

## 3. 外す列の決め方（`processes._launch_chain`）

`stat` が読めたプロセスの `pid → ppid` の表（今の `ppids`）と、`pid → 実行ファイルのパス`（読めたものだけ。` (deleted)` を取り除いたもの）の表を使う。

1. `self_pid` の ppid から始める
2. 今見ている pid が、0、表に無い、すでに見た（`self_pid` を含む）のどれかなら止まる
3. その pid の実行ファイルのパスが `sudo_paths` にあれば `sudo`。パスが読めていなければ `sudo` とみなさない
4. すでに `sudo` を見つけた後で、`sudo` でないものに着いたら止まる（そのプロセスは列に入れない）
5. それ以外は列に足し、ppid へ進んで 2 に戻る
6. 止まったとき、`sudo` を 1 つも見つけていなければ、列は空にする

返すのは外す pid の集まり。`classify` は、これと今の「`self_pid` と子孫」を合わせて、判定のいちばん最初に飛ばす。

| 形（左が親） | 外すもの |
|---|---|
| シェル → `sudo` → Tojimari | `sudo` |
| シェル → `sudo` → `sudo` → Tojimari | `sudo` 2 つ |
| シェル → `sudo` → シェル → Tojimari | `sudo` と、間のシェル |
| `sudo` → シェル → `sudo` → Tojimari | Tojimari に近いほうの `sudo` だけ（いちばん近い `sudo` で列が決まり、続く `sudo` が無いので止まる） |
| シェル → Tojimari | 無し |
| 読めない祖先 → Tojimari（その上に `sudo`） | 読めない祖先と `sudo`（読めない祖先は `sudo` とみなさず通り過ぎる。`unreadable` には数えない） |

細部で決めたこと:

- 輪の止め方は「すでに見た pid に着いたら止まる」。`_descendants_of` は回数で止めているが、こちらは 1 本の列をたどるだけなので、見た pid の集まりで足りる
- `sudo` の見分けに、ルートディレクトリが同じかは使わない。要件 3.2 は実行ファイルのパスだけで見分けるとしている。ルートが違う祖先の `sudo` はもともと印のもとにならないので、外しても外さなくても印は変わらない。変わりうるのは「列がどこで止まるか」だけで、条件を足すと止まる所が遠くなる（外すものが増える）向きなので、足さない
- `stat` が読めない祖先がいると、そこで列が切れる（ppid が分からない）。その上の `sudo` は外れず、印が付く。root で動かしていれば `stat` は読めるので、`running_is_snapshot` の注意の範囲とする
- 列にあるプロセスの子で、Tojimari の祖先でも子孫でもないもの（例: 間のシェルが別に動かしているコマンド）は外さない。要件の「列」に当たらないため
- `su`、`pkexec`、`run0` は見分けない（要件 5）

## 4. 関数の決まり

```python
# packages.py（足す）
def paths_owned_by(file_map, name: str) -> frozenset[str]:
    """file_map のうち、名前が name の版を 1 つでも持つパスの集まり。"""

# processes.py
SUDO_PACKAGE = "sudo"

def exe_paths(scan: ProcessScan) -> frozenset[str]:
    """rpm の記録で引くパス。実行ファイルを読めたすべてのプロセスの、
    " (deleted)" を取り除いたパス。"""

def sudo_paths(file_map) -> frozenset[str]:
    """sudo のパッケージが持つパス。"""

def _launch_chain(self_pid, ppids, exes, sudo_paths) -> set[int]:
    """Tojimari の親から、いちばん近い sudo と、その上に続く sudo までの pid。
    sudo が無ければ空（3）。"""

def classify(scan: ProcessScan, sudo_paths=frozenset()) -> tuple[list[tuple[str, bool]], int]:
    """(候補の (パス, サービスか) の並び, unreadable の数)。"""
```

- `classify` の `sudo_paths` に既定値（空）を付ける。空なら今までと同じ結果になるので、今の `classify(scan)` のテストはそのまま通り、要件 3.4 の 10（今の結果が変わらないこと）をテストがそのまま示す。`check.py` が渡し忘れたときは、6.3 の check のテストが落ちる
- `build_marks`、`apply_marks`、`parse_stat`、`is_system_service`、`strip_deleted`、`_descendants_of` は変えない

`check._collect_running` の流れ:

1. `system.process_scan()`。`ScanError` なら今までどおり `unavailable`。rpm は呼ばない
2. `packages.parse_rpm_files(system.rpm_files(), processes.exe_paths(scan))`。`CommandError` と `ParseError` は今までどおり `unavailable`
3. `processes.classify(scan, processes.sudo_paths(file_map))`
4. `processes.build_marks(candidates, file_map)` → `(marks, {"status": "ok", "unreadable": 数}, None)`

## 5. 出力とエラー

- JSON、表、注意、終了コードは変えない。外したプロセスの数や名前は出さない
- 新しい失敗の種類は無い。`exe_paths`、`sudo_paths`、`_launch_chain` は渡された値を見るだけで、例外を出さない
- 実行ファイルのパスと pid を、JSON、表、注意、例外の文に入れないことは変わらない

## 6. テストの方針

値はすべて架空のもの（今の `tests/recorded.py` の `make_proc`、`make_scan`、`RPM_FILES`）。実機の `/proc` と rpm を前提にしない。括弧の中の番号は task-issue-26.md の 3.4 の番号。

### 6.1 `tests/test_processes.py`

`classify(scan, SUDO)`（`SUDO = frozenset({"/usr/bin/sudo"})`）で確かめる。新しいクラス `ClassifyLaunchChainTest` にまとめる。

- `sudo` → Tojimari: 親の `sudo` が候補に無い（1）
- 上に加えて、祖先でない別の `sudo`（ppid が別）があるとき、そのパスが候補に 1 つ残る（2）
- `sudo` → `sudo` → Tojimari: 両方とも候補に無い（3）
- `sudo` → シェル → Tojimari: シェルも `sudo` も候補に無い（4）
- sshd にあたるもの → シェル → `sudo` → Tojimari: シェルと sshd にあたるものは候補に残る（5）
- シェル → Tojimari（`sudo` なし）: `sudo_paths` を渡してもシェルが候補に残る（6）
- `sudo` → シェル → `sudo` → Tojimari: 遠いほうの `sudo` とシェルは候補に残る（3 の表の 4 行目）
- 祖先の `sudo` の `exe` が `/usr/bin/sudo (deleted)`: 外れる（7）
- `sudo` → 実行ファイルが読めない祖先（`exe_error="permission"`）→ Tojimari: `sudo` も外れ、`unreadable` は 0（8、要件 3.3）
- `sudo` が無く、読めない祖先だけがあるとき: 外れず、`unreadable` は 1（8 の裏。今の数え方が変わらないこと）
- 祖先の `stat` が `None`: そこで止まり、その上の `sudo` は候補に残る
- ppid の輪（Tojimari の親と祖父が互いを親に持つ。`sudo` なし／輪の中に `sudo` あり）: 止まり、結果が決まる（9）
- 列の間のシェルの、別の子（Tojimari の祖先でも子孫でもない）は候補に残る
- `sudo_paths` が空なら、`sudo` → Tojimari でも親の `sudo` が候補に残る（既定値の意味）

今のテストの直し:

- `ClassifyKeepTest.test_parent_and_grandparent_of_self_are_kept` は、`sudo` を経ない形に置き換える（6）。名前も `test_ancestors_kept_without_sudo` のように直す
- ほかの `classify(scan)` のテストは変えない（10）

足すテスト:

- `exe_paths`: 読めたパスが入る、` (deleted)` を取り除く、`exe_error` のあるものは入らない、Tojimari 自身とルートが違うプロセスのパスも入る
- `sudo_paths`: `sudo` の版を持つパスだけが入る、ほかのパッケージのパスは入らない、空の `file_map` なら空

### 6.2 `tests/test_packages.py`

- `paths_owned_by`: 名前が合う版を持つパス、合わないパス、1 つのパスを 2 つの版（片方だけ名前が合う）が持つとき入る、空

### 6.3 `tests/test_check.py`

- `running_system()` は今の形（`sudo`（pid 100）→ Tojimari）のまま使う。`RunningTest.test_marks` の `sudo` の期待値を `(False, False)` に直す（11 の 1）
- 足す: `running_system()` のプロセスに、祖先でない `sudo`（別の pid、ppid は 1）を加えた形で、`sudo` の版が `(True, False)`、`unreadable` が 0（11 の 2）。`running_system` にプロセスを足せる引数（例: `extra=()`）を付けてよい
- 足す: シェル（`/usr/bin/bash`）→ Tojimari の形で `sudo` のプロセスが別にあるとき、`sudo` の版が `(True, False)`（`sudo` を経ない起動では外さない）
- ほかのテスト（`unavailable`、注意の順、パスや pid が出ないこと）は期待値を変えない

### 6.4 `tests/test_table.py`

- `running_report()` は `sudo` → Tojimari の形なので、今の `RunningMarkTest.test_running_only_mark_in_focus`（`sudo` の行に印）が落ちる。`running_report()` に祖先でない `sudo`（別の pid、ppid は 1）を足して、このテストの期待値はそのままにする（重点リストの「今動いている」だけの印を確かめるテストなので）
- 足す: 祖先でない `sudo` が無い形（`sudo` → Tojimari だけ）で、表の `sudo` の行に「<- 今動いている」が無いこと

### 6.5 変えないテスト

`tests/test_runner.py`、`tests/test_cli.py`、`tests/test_notices.py` ほかは変えない。ここに書いた以外の期待値を変える必要が出たら、実装を止めてテックリードに戻す。

## 7. 手元で確かめられていないこと

クラウド実行環境は AlmaLinux ではなく、`sudo` も rpm の記録も無い。次は実機確認（8）で確かめる。

- AlmaLinux 10 の `sudo` のプロセスの `/proc/<pid>/exe` が、rpm の記録にある `sudo` のパッケージのパスと文字どおり一致すること（design-issue-14.md の 2.2 の限界と同じ。一致しなければ見分けられず、今までどおり印が付く）
- `sudo` が端末（pty）を使って 2 段に重なる形で、両方が外れること（手順 1 で印が付かなければ確かめられる）

## 8. 実機確認の手順（PR に書く。本人にお願いすること）

task-issue-26.md の 7 の 3 つに、手順 4 を足す。実行結果を issue や PR に貼るときは、実機の生の情報（ホスト名、利用者名、パスなど）を置き換える。

| 手順 | すること | 見込み |
|---|---|---|
| 1 | ほかに `sudo` を動かしていないときに `sudo python3 -B -m tojimari check` | 重点リストの `sudo` の行に「今動いている」が付かない。`openssh-server`、`systemd` などほかの印は今までどおり |
| 2 | 別の端末で `sudo sleep 300` を動かしたまま、`sudo python3 -B -m tojimari check` | 重点リストの `sudo` の行に「今動いている」が付く |
| 3 | ほかに `sudo` を動かしていないときに `sudo python3 -B -m tojimari check --json` | `checks.running_processes.status` が `ok`、`unreadable` が 0。`sudo` の版の `running` が false |
| 4（足す） | ほかに `sudo` を動かしていないときに `sudo sh -c 'python3 -B -m tojimari check'` | 手順 1 と同じ（間に `sh` があっても `sudo` に印が付かない） |

手順 1 で印が付いたままのときは、7 の 1 つ目（パスが一致しない）が考えられる。そのときは issue に結果を書いてもらい、PM が次の対応を決める。

## 9. 文書の直し

- [design-issue-14.md](design-issue-14.md) の冒頭、1（全体の形）、4.1 の表の 1、4.4、10.2（`_collect_running` の流れ）、10.3（`classify` のテスト、check のテスト）に、「#26 で変えた」の一文とこの文書への参照を足した
- 要件の側（spec-1.1.md、output-1.1.md、requirements.md、task-issue-14.md）は PM が直し済み。設計から足す直しは無い

## 10. 実装担当への指示

### 10.1 変えるファイル

| ファイル | 変更 |
|---|---|
| `tojimari/packages.py` | `paths_owned_by(file_map, name)` を足す（4）。`version_key` の近くに置く。ほかは変えない |
| `tojimari/processes.py` | `SUDO_PACKAGE`、`exe_paths`、`sudo_paths`、`_launch_chain` を足し、`classify` に `sudo_paths=frozenset()` を足す（3、4）。`classify` の中で、今の `excluded` に `_launch_chain` の結果を合わせる。判定の順番（design-issue-14.md の 4.1）のほかの所は変えない |
| `tojimari/check.py` | `_collect_running` を 4 の流れに直す。返す値の形、理由の文字列、`_RUNNING_UNAVAILABLE` は変えない |
| `tests/test_processes.py` | 6.1 |
| `tests/test_packages.py` | 6.2 |
| `tests/test_check.py` | 6.3 |
| `tests/test_table.py` | 6.4 |

`runner.py`、`notices.py`、`table.py`、`cli.py`、`history.py`、`staleness.py`、`rpmver.py`、`display.py`、`tests/recorded.py` の `RPM_FILES` と `FakeSystem` は変えない。

### 10.2 守ること

- 新しい依存を入れない。外部コマンドの呼び出しを増やさない（`rpm_files` は 1 回のまま）。`/proc` の読み方（`runner.scan_processes`）を変えない
- プロセス名（`stat` の括弧の中）で `sudo` を見分けない。パスを決め打ちで持たない（`"/usr/bin/sudo"` をコードに書かない。テストの架空の値としては書いてよい）
- `processes.py` は今までどおり何も実行せず、ファイルも読まない。`check` を読み込まない
- 実行ファイルのパスと pid を、JSON、表、注意、例外の文に入れない
- テストの値は架空のものだけにする。実機の生の情報を入れない
- コードのコメントと文書に、セキュリティを担保・保証すると読める表現を入れない

### 10.3 確かめる順番

1. 何も変える前に、リポジトリの最上位で `python3 -m unittest` がすべて通ることを見る（今は 360 件）
2. `packages.paths_owned_by` とそのテスト（6.2）
3. `processes.py` の 4 つと `classify` の引数、そのテスト（6.1）。この時点で、今の `classify(scan)` のテストは `test_parent_and_grandparent_of_self_are_kept` の置き換えのほかは手を入れずに通ること
4. `check._collect_running` と、`tests/test_check.py`（6.3）、`tests/test_table.py`（6.4）
5. `python3 -m unittest` がすべて通ること（12）
6. `tojimari/` の中に `"/usr/bin/sudo"` の文字列が無いこと、`stat` の括弧の中の名前を読む所が増えていないことを見る
7. 作業ブランチにコミットする（push はしない）。コミットメッセージとテストに実機の生の情報を入れない

6.5 のとおり、ここに書いた以外の今のテストの期待値を変える必要が出たら、実装を止めてテックリードに戻す。

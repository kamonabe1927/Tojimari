# 設計: 重点リストの表示と 1.1 の土台（issue #5）

- 作成日: 2026-11-21
- 書いた人: テックリード
- 関連: [task-issue-5.md](task-issue-5.md)（要件）、[output-1.1.md](output-1.1.md)（コマンド、JSON、表、終了コード、notices）、[spec-1.1.md](spec-1.1.md)
- 位置付け: 要件と出力仕様は変えない。この文書は「どう作るか」だけを決める。出力仕様に書かれていない細部は 7 にまとめた

## 1. 全体の形

情報の流れは一方向にする。

```
実行部（runner）         外部コマンドと OS への問い合わせ。ここだけが subprocess と os を使う
   ↓ 文字列
読み取り部（packages）   決めた形の文字列を、版の一覧や対応表に直す。何も実行しない
   ↓ データ
組み立て（check）        JSON と同じ形の dict（以下「レポート」）を 1 つ作る
   ↓ レポート
出力（cli / table）      レポートを JSON にするか、表にする
```

- 表はレポートだけを元に作る。表のために別の問い合わせをしない（表だけに出る情報を作らないため。output-1.1.md の 3.2）
- 実行部は 1 つのオブジェクトにまとめ、テストでは丸ごと差し替える（rpm、dnf、uname を実際に呼ばない）
- 依存は標準ライブラリだけ。使うのは `argparse`、`dataclasses`、`datetime`、`json`、`os`、`subprocess`、`sys`、`unicodedata`、テストで `unittest`、`io`

## 2. ファイルの分け方

```
tojimari/
  __init__.py     中身は説明の docstring だけ
  __main__.py     起動。標準出力と標準エラー出力を UTF-8 にして cli.main() を呼ぶ
  cli.py          引数、出し分け、終了コード
  runner.py       実行部
  packages.py     読み取り部（rpm と dnf の問い合わせの形と、その読み取り）
  check.py        重点リストの定義、レポートの組み立て
  notices.py      表示の注意の文言と、出す条件
  table.py        レポートから表を作る
tests/
  __init__.py     空
  recorded.py     記録出力（テスト用データ）と、差し替え用の実行部
  test_packages.py
  test_check.py
  test_table.py
  test_cli.py
  test_runner.py
.gitignore        __pycache__/ と *.pyc
```

理由:

- 問い合わせの書式（queryformat）と読み取りを同じ `packages.py` に置く。書式を変えたら読み取りも変えることになるので、離すとずれる
- `packages.py` は重点リストを知らない。後で足す「後から入れたもの」も同じ rpm の一覧と同じ版の要素を使うため
- `check.py` は 1 ファイルにする。確認が増えて長くなったら、そのときに分ける（今は分けない）
- シェルスクリプトの起動用ファイル、設定ファイル、`pyproject.toml` は作らない（配布方法が未決のため）

## 3. 外部コマンドの呼び方

### 3.1 共通

- シェルを通さず、引数の配列で呼ぶ（`shell=False`）。標準入力は閉じる（`stdin=subprocess.DEVNULL`）
- コマンドは絶対パスで呼ぶ（`/usr/bin/rpm`、`/usr/bin/dnf`）。`PATH` の並びによって別の実行ファイルを呼ばないため。対象は AlmaLinux だけなので場所は固定でよい（実機確認の A）
- 引数に利用者の入力を入れない。渡すのは固定の書式と、固定の重点リストの名前だけ
- 標準出力だけを読む。標準エラー出力は読み取りに使わない
- 標準出力は UTF-8 として読み、読めないバイトは置き換える（`errors="replace"`）
- タイムアウト: rpm は 30 秒、dnf は 60 秒
- 環境変数は足さない・変えない（メッセージを読み取らないので、言語の設定に左右されない）

### 3.2 rpm

```
/usr/bin/rpm -qa --queryformat '%{NAME}\t%|EPOCH?{%{EPOCH}}:{}|\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n'
```

- `\t` と `\n` は rpm に解釈させる（Python の文字列では `"\\t"`、`"\\n"`。バックスラッシュと文字の 2 文字を渡す）
- 名前を引数に渡さず、全部の一覧を取って Python の側で名前を絞る。入っていないパッケージを rpm のメッセージや終了コードで判定しないため（task-issue-5.md の 3.3）。後で足す「後から入れたもの」でも同じ一覧を使える
- epoch は条件式 `%|EPOCH?{...}:{}|` で、無いときは空文字にする。`%{EPOCH}` をそのまま使うと、無いときの表示（`(none)` になる見込み）に頼ることになるため
- 1 行は 5 項目（タブ区切り）: 名前、epoch、version、release、arch

読み取りの決まり（`parse_rpm_list`）:

- 空行は飛ばす
- 項目が 5 つでない行、名前・version・release のどれかが空の行、epoch が空でも数字でもない行が 1 つでもあれば、読み取りの失敗とする（想定した形で出ていないので、一部だけ信じることをしない）
- arch は中身を問わない（`gpg-pubkey` のように arch を持たない記録があるため。重点リストには関係しない）
- epoch が空文字なら `None`、それ以外は文字列のまま持つ（`"0"` と書かれていれば `"0"`）
- 1 行も読めなければ失敗とする（動いている AlmaLinux で rpm の記録が空になることはない）

### 3.3 dnf

```
/usr/bin/dnf repoquery --installed --cacheonly --quiet --queryformat <書式> kernel openssh-server openssh openssl-libs glibc sudo systemd polkit
```

書式は `%{name}<TAB>%{epoch}<TAB>%{version}<TAB>%{release}<TAB>%{arch}<TAB>%{from_repo}<改行>`。`<TAB>` と `<改行>` は本物のタブ文字と改行文字を引数に入れる（Python の文字列では `"\t"`、`"\n"`）。

- `--cacheonly`: 通信を起こさない（task-issue-5.md の 3.3）
- `--quiet`: 標準出力に問い合わせの結果以外が混ざりにくくする
- 区切りに本物のタブを使う理由: dnf が書式の中の `\t` を解釈するかを手元で確かめられない。本物の文字なら解釈に頼らない
- 末尾に本物の改行を入れる理由: dnf 4 は 1 件ごとに改行を足す見込みだが、足さない版でも 1 件 1 行になるようにするため。足す版では空行が挟まるので、読み取りで空行を飛ばす
- 名前を引数に渡して絞る（出力を小さくするため）。名前以外のもの（provides など）に当たって余分な行が出ても、下の突き合わせで使われないだけなので害はない

読み取りの決まり（`parse_dnf_from_repo`）:

- 空行と、項目が 6 つでない行は飛ばす（失敗にしない。dnf が結果以外の行を標準出力に出しても続けるため）
- 結果は「版のキー → 入れた元」の対応表。版のキーは `(name, epoch, version, release, arch)` で、epoch は無ければ `"0"` にそろえる（rpm は無い epoch を空で、dnf は `0` で出す見込みのため。rpm の側も同じ関数でキーを作る）
- `from_repo` が空文字なら `None`（その版は入れた元が分からない）
- 何が入っているかは rpm の一覧だけで決める。dnf の結果は入れた元を引くためだけに使い、dnf にしか無い版は表示しない

## 4. 関数の分担

型の書き方は Python 3.11 で動く範囲にする（`X | None`、`list[str]`、`dataclass` は可。3.12 以降だけの書き方は使わない。8 を参照）。

### 4.1 `runner.py`（実行部）

```python
class CommandError(Exception):
    """外部コマンドを実行できなかった、または失敗した。"""
    kind: str          # "not_found" | "timeout" | "exit_status" | "os_error"
    returncode: int | None   # kind が "exit_status" のときだけ入る
    stderr_tail: str   # 標準エラー出力の末尾（最大 5 行）。無ければ空文字

def run_command(argv: list[str], timeout: float) -> str:
    """argv を実行し、標準出力を文字列で返す。終了コードが 0 でなければ CommandError。"""

class System:
    """実機への問い合わせをまとめたもの。テストではこのクラスごと差し替える。"""
    def rpm_list(self) -> str            # packages.RPM_LIST_ARGV を 30 秒で実行
    def dnf_from_repo(self, names) -> str  # packages.dnf_from_repo_argv(names) を 60 秒で実行
    def running_kernel(self) -> str | None  # os.uname().release。取れなければ None
    def is_root(self) -> bool            # os.geteuid() == 0
    def now(self) -> datetime            # datetime.now(timezone.utc)
```

- `run_command` の対応: `FileNotFoundError` → `not_found`、`subprocess.TimeoutExpired` → `timeout`、そのほかの `OSError`（実行権限が無いなど）→ `os_error`、終了コードが 0 以外 → `exit_status`
- `System` は状態を持たない。`rpm_list` と `dnf_from_repo` は `CommandError` をそのまま上に投げる
- `running_kernel` は `OSError` と `AttributeError` を捕まえて `None` を返す

### 4.2 `packages.py`（読み取り部）

```python
RPM_LIST_ARGV: list[str]                       # 3.2 のとおり
def dnf_from_repo_argv(names: list[str]) -> list[str]   # 3.3 のとおり

class ParseError(Exception): ...

@dataclass(frozen=True)
class PackageVersion:
    name: str
    epoch: str | None
    version: str
    release: str
    arch: str

def parse_rpm_list(text: str) -> list[PackageVersion]            # 失敗は ParseError
def parse_dnf_from_repo(text: str) -> dict[tuple, str | None]     # 失敗しない
def version_key(name, epoch, version, release, arch) -> tuple     # epoch の None と "" を "0" にそろえる
def format_evr(pkg: PackageVersion) -> str                        # "version-release" か "epoch:version-release"
def version_entry(pkg: PackageVersion, from_repo: str | None) -> dict
```

- `version_entry` は output-1.1.md の 2.3 の要素を、表の順のキー（`name`、`epoch`、`version`、`release`、`arch`、`evr`、`from_repo`）で返す。`is_running_kernel` はここでは付けない（kernel だけの項目なので `check.py` が足す）。後で足す「後から入れたもの」もこの関数を使う
- このモジュールは `subprocess` と `os` を import しない

### 4.3 `check.py`（組み立て）

```python
FOCUS_PACKAGES: list[tuple[str, str]]   # (名前, 選んだ理由)。spec-1.1.md の 2.2 の順と文言

class CheckError(Exception):
    """出力そのものができない（終了コード 1 にする）。"""

def collect(system) -> dict                      # レポート全体（output-1.1.md の 2.1）
def build_focus_packages(installed, from_repo_map, running_kernel) -> dict   # 2.2 の形
```

`collect` の手順:

1. `system.rpm_list()` → `parse_rpm_list`。`CommandError` か `ParseError` なら `CheckError` にして投げる（理由の文と、`stderr_tail` があればそれを含める）
2. `system.dnf_from_repo(名前の一覧)` → `parse_dnf_from_repo`。`CommandError` なら対応表は無しとし、理由（5.2）を覚えて続ける
3. `system.running_kernel()`、`system.is_root()`、`system.now()` を取る
4. `build_focus_packages` で `checks.focus_packages` を作る
5. `notices.build_notices` で `notices` を作る
6. output-1.1.md の 2.1 のキーの順で dict を組み立てて返す

`build_focus_packages` の決まり:

- `FOCUS_PACKAGES` の順に、名前が完全に一致する版を集める（`kernel-core` などは `kernel` に含めない）
- 版の並びは `(version, release, arch)` の文字列の昇順
- 版が 1 つ以上あれば `status` は `installed`、無ければ `not_installed` で `installed` は空配列
- `name` が `kernel` の版にだけ `is_running_kernel` を付ける。`running_kernel` が `None` でなく、`f"{version}-{release}.{arch}"` と等しければ true
- `from_repo_available` は 5.2 のとおり

`reason` の文言は spec-1.1.md の 2.2 の表のとおり（`openssh-server` と `openssh` はどちらも「外から届く入口」）。

### 4.4 `notices.py`

```python
def build_notices(is_root: bool, from_repo_problem: str | None, running_kernel_found: bool) -> list[dict]
```

- 出す条件と並びは output-1.1.md の 2.4 のとおり。`history_fallback` は今回作らない
- 文言は 7.3 のとおり。文言はこのモジュールの定数として持つ

### 4.5 `table.py`

```python
def render_table(report: dict) -> str     # 末尾に改行 1 つ
def display_width(text: str) -> int       # east_asian_width が "W" "F" "A" なら 2、ほかは 1
```

- 入力はレポートの dict だけ。実行部も読み取り部も import しない
- `report["format"]` が `"tojimari-check"` でない、または `schema_version` が 1 でないときは `ValueError`（output-1.1.md の 2.5 の読む側の決まり）
- `checks` に `focus_packages` が無ければ、その表を出さない（「確認していない」と扱う）。知らないキーは無視する
- 見た目の細部は 7.1

### 4.6 `cli.py` と `__main__.py`

```python
def main(argv=None, system=None, stdout=None, stderr=None) -> int
```

- `argparse` で `prog="tojimari"`、サブコマンドは `check` だけ（必須）、`check` のオプションは `--json` だけ
- 引数の誤りは argparse の既定の動き（標準エラー出力に使い方、終了コード 2）に任せる
- `system` が `None` なら `runner.System()` を使う。`stdout`、`stderr` が `None` なら `sys.stdout`、`sys.stderr`
- 流れ: `collect(system)` → 出力する文字列を最後まで作る → 1 回で書き出す → 0 を返す。文字列を作り終えるまで標準出力に何も書かない（途中で失敗したときに中途半端な出力を残さないため）
- `CheckError` を捕まえたら、標準エラー出力に `tojimari: ` で始まる理由を出し、標準出力には何も書かずに 1 を返す
- JSON は `json.dumps(report, ensure_ascii=False, indent=2)` に改行 1 つ。キーの並びは dict を作った順（`sort_keys` を使わない）
- `__main__.py` は、`sys.stdout` と `sys.stderr` に `reconfigure` があれば `encoding="utf-8"` にしてから `sys.exit(main())` を呼ぶ（sudo で言語の設定が変わっても日本語を出せるようにするため）

## 5. エラーと権限不足のときの振る舞い

### 5.1 rpm（全体を失敗にする）

次のどれでも `CheckError` とし、終了コード 1、標準出力は空、理由を標準エラー出力に出す。

| 起きたこと | 標準エラー出力の理由（意味） |
|---|---|
| `/usr/bin/rpm` が無い | rpm コマンドが見つからない |
| 時間内に終わらない | rpm の問い合わせが 30 秒で終わらなかった |
| 終了コードが 0 でない | rpm の問い合わせが終了コード N で失敗した |
| 実行できない（`OSError`） | rpm を実行できなかった |
| 出力が決めた形でない、1 行も無い | rpm の出力を読み取れなかった |

- rpm の標準エラー出力の末尾（最大 5 行）があれば、理由の後に続けて標準エラー出力に出す。利用者の端末に出すだけで、JSON には入れない

### 5.2 dnf（入れた元を null にして続ける）

次のどれでも `from_repo_available` を false、全部の版の `from_repo` を null にし、`from_repo_unavailable` の notice を出して続ける。終了コードは 0。

| 起きたこと | notice に入れる理由の要約 |
|---|---|
| `/usr/bin/dnf` が無い | dnf コマンドが見つからない |
| 時間内に終わらない | dnf が 60 秒で終わらなかった |
| 終了コードが 0 でない（キャッシュが無いなど） | dnf が終了コード N で終わった |
| 実行できない（`OSError`） | dnf を実行できなかった |
| 入っている版が 1 つ以上あるのに、対応表のどの行とも突き合わなかった | dnf の出力に該当する版が無かった |

- 理由の要約は Tojimari が決めた上の文だけにする。dnf の標準エラー出力は JSON にも表にも入れない（形を決められない文字列を出力に混ぜないため）
- dnf は成功し、一部の版だけ突き合わなかった、または `from_repo` が空だったときは、`from_repo_available` は true のまま、その版の `from_repo` だけ null にする（表では `-`）
- 重点リストが 1 つも入っていないとき（突き合わせる版が無いとき）は、dnf が成功していれば `from_repo_available` は true

### 5.3 権限不足（root なし）

- root なしでも止めない。`run.is_root` を false にし、`not_root` の notice を出す
- root なしで dnf が失敗したら 5.2 のとおり続ける。root なしで rpm が失敗したら 5.1 のとおり失敗にする（rpm の記録は通常 root なしでも読める）
- root かどうかで問い合わせの内容を変えない

### 5.4 そのほか

- 動いているカーネルが取れないとき: `system.running_kernel` は null、kernel の版の `is_running_kernel` はすべて false、`running_kernel_not_found` の notice を出す。kernel が入っていないときも同じ notice を出す
- 想定していない例外は捕まえない（Python の既定どおり、トレースバックと終了コード 1）。握りつぶして正常に見せないため

## 6. テストの方針

- `unittest` だけを使う。リポジトリの最上位で `python3 -m unittest` を実行すると全部通ること
- 記録出力は `tests/recorded.py` に Python の文字列の定数として置く。タブは `"\t"` と書く
  - ファイルではなく定数にする理由: 区切りがタブであることを差分で目で確かめられ、エディタや道具がタブを空白に変えても気づけるため
  - 値は架空のものにする（output-1.1.md の 3.1 の例の版を使う）。実機の出力を元にするときは、置き換えてから同じ形で足す
- `tests/recorded.py` に差し替え用の `FakeSystem` を置く。`rpm_list`、`dnf_from_repo`、`running_kernel`、`is_root`、`now` を持ち、返す値か投げる例外をコンストラクタで受け取る。`now` は固定の時刻を返す
- `test_runner.py` だけは本物の `subprocess` を使うが、呼ぶのは `sys.executable`（テストを動かしている python3 自身）だけにする。rpm、dnf、uname は呼ばない
- テストは通信しない、リポジトリの外に書かない

記録出力として用意するもの（`tests/recorded.py`）:

| 名前 | 中身 |
|---|---|
| `RPM_ALL_INSTALLED` | 重点リスト 8 件が全部ある。kernel は 2 世代、openssl-libs は epoch `1`、重点リスト以外（`bash`、`kernel-core`、arch が `(none)` の `gpg-pubkey`）も混ざる |
| `RPM_PARTIAL` | polkit と openssh-server が無い |
| `RPM_MULTI_ARCH` | glibc が `x86_64` と `i686` の両方ある |
| `RPM_MALFORMED` | 項目が足りない行が混ざる |
| `DNF_ALL` | `RPM_ALL_INSTALLED` の重点リストの版に対応する行。epoch が無いものは `0`。空行が挟まる形 |
| `DNF_PARTIAL` | 一部の版の行が無い、または `from_repo` が空 |
| `DNF_NOISE` | 項目が 6 つでない行が混ざる |

確かめること（task-issue-5.md の 3.5 を満たす）:

| ファイル | 確かめること |
|---|---|
| `test_packages.py` | `RPM_LIST_ARGV` と `dnf_from_repo_argv` が 3 のとおりの配列であること（書式の文字列を含めて固定する）。`parse_rpm_list` が epoch なし（`None`）、epoch あり、arch 違い、`(none)` の arch を読めること。項目が足りない行、空の出力、数字でない epoch で `ParseError`。`parse_dnf_from_repo` が空行と形の違う行を飛ばすこと、`from_repo` が空なら `None`、epoch `0` の行が rpm の epoch なしの版と同じキーになること。`format_evr` の 2 通り |
| `test_check.py` | 全部入っているとき（8 件が決めた順、全部 `installed`）。一部が無いとき（`not_installed` と空配列）。kernel 2 世代で 1 つが動いているとき（その版だけ true、notice なし）。どれとも一致しないとき、`running_kernel` が `None` のとき（全部 false、`running_kernel_not_found`）。`kernel-core` を kernel に含めないこと。版の並び。dnf が取れたとき（`from_repo` が入る、`from_repo_available` が true）。dnf が `CommandError` の各種類のとき、どの版とも突き合わないとき（false、全部 null、`from_repo_unavailable` に理由の要約）。一部だけ突き合わないとき（true のまま、その版だけ null）。root のときとそうでないとき（`not_root` の有無）。常に出る 3 つの notice と並び。レポートの最上位のキーの順、`format`、`schema_version`、`generated_at` の形、版の要素のキーの順、`is_running_kernel` が kernel の版にだけあること。`user_installed` などの後で足すキーが無いこと。rpm が `CommandError`、`ParseError` のとき `CheckError` |
| `test_table.py` | `display_width`（半角、全角）。全部の行の列の位置が表示幅でそろうこと。版が複数のとき 2 行目から名前と状態が空くこと。`<- 動いている` が動いている版の行だけに付くこと。入っていない行、入れた元が null のときの `-`。「動いているカーネル」の行（null のとき `-`）。先頭に `not_a_guarantee` の文があり `[注意]` に重ねて出ないこと。`[注意]` にそれ以外の notice が全部出ること。レポートにある名前、`evr`、arch、`from_repo` が全部表に出ること（表と JSON の中身が同じ）。`format` や `schema_version` が違うと `ValueError`。`focus_packages` が無いレポートで表を出さずに続くこと |
| `test_cli.py` | `check` で表、`check --json` で JSON が出て終了コード 0。JSON を `json.loads` で読め、`collect` の結果と同じであること。rpm が失敗したとき、`--json` の有無どちらでも終了コード 1、標準出力が空、標準エラー出力に理由があること。引数なし、知らないサブコマンド、知らないオプションで終了コード 2（`SystemExit` の `code` を見る） |
| `test_runner.py` | `run_command` が標準出力を返すこと、標準エラー出力を混ぜないこと、終了コードが 0 でないとき `exit_status` と `returncode`、無いコマンドで `not_found`、短いタイムアウトで `timeout`。どれも `sys.executable -c ...` で起こす |

- 出力に「保証」「担保」「安全です」のように、安全を請け合うと読める言葉が無いことを、notice の文言と表の全文に対して確かめるテストを 1 つ入れる（`not_a_guarantee` の「安全であることを示すものではありません」は打ち消しなので、言葉の一覧は「保証」「担保」「安全です」「守られています」とする）

## 7. 出力仕様に書かれていない細部（今回決めたこと）

output-1.1.md の決定は変えていない。読み取りに幅がある所を次のように決めた。意味が変わる所があれば、PM が output-1.1.md に取り込むかを決める。

### 7.1 表

- 1 行目は `Tojimari check  YYYY-MM-DD HH:MM UTC`（`generated_at` から作る。秒は出さない）
- 列は「パッケージ」「状態」「バージョン」「アーキ」「入れた元」。各列の幅は、見出しと中身のうち一番広い表示幅。列の間は空白 2 つ
- 入っていない行は、バージョンの列に `-` を 1 つ出し、その右は出さない（output-1.1.md の 3.1 の例のとおり）
- 入っている版の入れた元が null なら `-`
- `<- 動いている` は、入れた元の列の後ろに空白 2 つを空けて付ける
- 「動いているカーネル: 」の値が null なら `-`
- `[注意]` は、`not_a_guarantee` 以外の notice を並びのまま `- 文言` で 1 行ずつ出す。折り返しはしない
- 各行の末尾の空白は削る。区切りの空行は 1 行

### 7.2 JSON

- インデントは空白 2 つ、日本語はそのまま出す（`\u` の形にしない）
- `epoch` は rpm が出した文字列のまま（`"1"`）。明示的に `0` と記録されていれば `"0"` で、`evr` は `0:...` になる

### 7.3 notice の文言

| `id` | 文言 |
|---|---|
| `not_a_guarantee` | この表示は確認の補助であり、安全であることを示すものではありません。 |
| `scope` | 表示対象は dnf（rpm）で入れたものと重点リストだけです。パッケージ管理の外で個別にビルド・配置したもの、pip などの言語ごとのパッケージ管理で入れたもの、Docker コンテナの中身は表示しません。表示されないことを「入っていない」と扱わないでください。 |
| `running_is_snapshot` | 「今動いている」はその瞬間の様子です。印がないことを「使っていない」と扱わないでください。 |
| `not_root` | root なしで実行したため、見えた範囲だけを表示しています。sudo を付けて実行することを勧めます。 |
| `from_repo_unavailable` | 入れた元のリポジトリを取得できませんでした（理由: <5.2 の要約>）。入れた元は表示していません。 |
| `running_kernel_not_found` | 動いているカーネルが、rpm の記録にある kernel の版の中に見つかりませんでした。 |

## 8. Python の版

- AlmaLinux 10.2 の python3 と、作業環境の Python 3.11 の両方で動かす
- 3.12 以降だけの書き方を使わない（`type` 文、`def f[T]` の形、f 文字列の中で外側と同じ引用符を使う書き方、`itertools.batched` など）。時刻は `datetime.timezone.utc` を使う
- AlmaLinux 10.2 の python3 の版は手元で確かめていない（実機確認の A）

## 9. 手元で確かめられていないこと（実機確認の手順に入れる）

task-issue-5.md の 5 の手順に、次を足す・置き換える。セキュリティ担当が PR を作るときに取り込む。

| 記号 | コマンド | 確かめること |
|---|---|---|
| A | `python3 --version; ls -l /usr/bin/rpm /usr/bin/dnf` | python3 の版が 3.11 以上。rpm と dnf が `/usr/bin` にある |
| B | `rpm -qa --queryformat '%{NAME}\t%\|EPOCH?{%{EPOCH}}:{}\|\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n' \| grep -P '^(kernel\|openssl-libs\|glibc)\t' \| cat -A`（表の中なので `\|` と書いた。打つときは `|`） | 1 件 1 行で、項目の間が `^I`（タブ）、行末が `$`。epoch の無い行は名前の後が `^I^I` で、`(none)` と出ない。openssl-libs は epoch の数字が出る |
| C | `dnf repoquery --installed --cacheonly --quiet --queryformat $'%{name}\t%{epoch}\t%{version}\t%{release}\t%{arch}\t%{from_repo}\n' kernel openssh-server openssh openssl-libs glibc sudo systemd polkit \| cat -A; echo "exit=${PIPESTATUS[0]}"`（task-issue-5.md の 5 の手順 6 をこれに置き換える） | 終了コードが 0。1 件ごとに 6 項目がタブ区切りで出る（間に空行があってもよい）。epoch の無いものが `0` と出る。最後の項目が `baseos` などのリポジトリ名で、手順 1 の「入れた元」と一致する |
| D | C を sudo なしでも実行する | 同じ結果になるか、失敗するか。失敗するなら、手順 5 の表で入れた元が `-` になり、取得できなかった旨の注意が出ること |
| E | C の実行中に通信が起きないこと（ネットワークを切った状態で C を実行する） | 終了コードが 0 で、同じ結果が出る。失敗するなら終了コードと標準エラー出力の要点を伝える |
| F | `git status --ignored`（手順 7 をこれに置き換える） | `__pycache__` などができていない（`.gitignore` に入れるため、`--ignored` を付けないと見えない） |

分かっていないことと、外れたときの動き:

- rpm の条件式や `\t` の解釈が見込みと違う → 読み取りが失敗し、終了コード 1 になる（誤った表は出ない）。B で分かる
- dnf の `--cacheonly` がキャッシュ無しで失敗する、`%{from_repo}` が使えない、タブや改行の出方が違う → 入れた元がすべて `-` になり、注意が出る（ほかの表示は出る）。C、D、E で分かる
- dnf が入れた元の分からない版に空文字以外（何かの決まった文字列）を出す → その文字列がそのまま表示される。C で見つけたら直す
- root なしの dnf が、利用者ごとのキャッシュの場所（`/var/tmp` の下など）に書くことがありうる。Tojimari 自身の書き込みではないが、D で気づいたら伝えてもらう
- C が失敗する場合の次の候補は `--disablerepo='*'` を足すこと（入っているものだけを見るので、リポジトリの情報が要らない見込み）。今回は入れない。実機の結果を見てから決める

## 10. 後で足すものとの関係（今回は作らない）

- 「後から入れたもの」: `parse_rpm_list` の一覧と `version_entry` をそのまま使い、`checks.user_installed` を足す
- 「古さ」: `checks.staleness` を足す。通信が要る問い合わせは `System` にメソッドを足す
- 「今動いているかの印」: `version_entry` が返す dict に項目を足す
- どれも、今回は置き場所があるだけで、関数もキーも作らない

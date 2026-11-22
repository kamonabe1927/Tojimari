# 設計: 外部コマンド由来の文字列の制御文字を、表と標準エラー出力でそのまま端末に出さない（issue #16）

- 作成日: 2026-11-22
- 書いた人: テックリード
- 要件: [task-issue-16.md](task-issue-16.md)
- 土台: [design-issue-5.md](design-issue-5.md) の 3.1・5・6、[design-issue-15.md](design-issue-15.md)（`CommandError.timeout` と理由の文言はそのまま使い、触らない）、[output-1.1.md](output-1.1.md) の 1.3 と 3.2

差し戻しは無い。設計を止める矛盾は見つからなかった。
ただし、要件の前提に事実と違うところが 1 つある（JSON の DEL と C1）。今回の範囲（表と標準エラー出力）は変えずに進め、7 に書いて PM に返す。

変えるのは見せ方だけ。JSON の中身、文言、終了コード、表の列と並びは変えない。新しい依存は無い（標準ライブラリだけ）。
置き換えは「端末の表示が変わらないように見える形にする」もので、これで安全になるとは書かない。

## 1. 全体の形

```
tojimari/display.py   … 置き換えと上限の関数はここだけ（何も import しない）
  ├─ table.render_table(report)
  │    入口で、レポートの写しを作り、中の文字列の値をすべて置き換える。
  │    その後ろ（列の幅、行の組み立て）は、写しだけを見る
  └─ check._rpm_failure_message(err)
       Tojimari の文はそのまま。stderr_tail の各行にだけ、置き換えと上限をかける
            └─ cli.main は、受け取った文を今のまま標準エラー出力に書く
```

## 2. 決めたこと

### 2.1 置き換えと上限の関数を置くモジュール

新しく `tojimari/display.py` を作り、次の 3 つと定数 1 つを置く。

```python
STDERR_LINE_LIMIT = 200

def replace_controls(text: str) -> str: ...
def replace_controls_deep(value): ...
def replace_and_clip(text: str, limit: int = STDERR_LINE_LIMIT) -> str: ...
```

- `display.py` は、ほかの `tojimari` のモジュールを import しない（標準ライブラリだけ）。表（`table.py`）と理由の文（`check.py`）の両方から使うので、どちらかに置くと、もう一方がそれを import する向きができてしまうため
- 採らなかった案

| 案 | 採らない理由 |
|---|---|
| `table.py` に置く | `check.py` が表のモジュールを import することになる。確認の組み立てが表に頼る向きは今は無く、作りたくない |
| `runner.py` に置く | 実行部は「外部コマンドと OS への問い合わせ」だけを持つ（[design-issue-5.md](design-issue-5.md) の 3.1）。見せ方の決まりを混ぜない |
| `notices.py` に置く | 注意の文と ID を持つところで、表の値の見せ方とは役目が違う |

- `display_width` は `table.py` に置いたままにする（動かさない）。今回要らない移動で、振る舞いを変えない変更を増やさないため
- モジュールと関数の名前に「safe」「sanitize」のような、安全になると読める言葉を使わない

### 2.2 関数の決まり

`replace_controls(text)`

- 対象は、符号位置が U+0000〜U+001F、U+007F、U+0080〜U+009F の文字。判定は `ord(c) < 0x20 or 0x7f <= ord(c) <= 0x9f`
- 対象の文字を `\x` と 16 進の小文字 2 桁（`f"\\x{ord(c):02x}"`）にする。ほかの文字（逆斜線、全角、U+202E、U+2028 など）は変えない
- 対象の文字が無ければ、入力と同じ文字列を返す

`replace_controls_deep(value)`

- `dict` は、値だけを置き換えた新しい `dict` を返す（キーは変えない。順番は保つ）
- `list` と `tuple` は、要素を置き換えた新しい `list` を返す
- `str` は `replace_controls` の結果を返す
- それ以外（`int`、`bool`、`None` など）はそのまま返す
- 入力は書き換えない

`replace_and_clip(text, limit)`

- 入力は置き換える前の 1 行。出力は、置き換えて、長ければ切った 1 行
- 数え方は、置き換えた後の文字数（Unicode の符号位置の数）。`\x1b` は 4 文字、全角 1 文字は 1 文字と数える
- 元の文字を 1 つずつ見て、その文字の置き換えた後の形（1 文字か 4 文字）を足していく。足すと `limit` を超える文字に当たったら、そこで止める。こうすると、置き換えた形の途中では切れない
- 止めたときは、後ろに印 ` ...（残り {n} 文字を省略）` を付ける。`n` は、置き換えた後の全体の文字数から、残した文字数を引いた数。印は上限に数えない
- 置き換えた後が `limit` 文字以下なら、置き換えただけの文字列を返す（印は付けない）

参考の書き方（このとおりでなくてよいが、振る舞いは同じにする）。

```python
def _piece(c: str) -> str:
    o = ord(c)
    return f"\\x{o:02x}" if o < 0x20 or 0x7F <= o <= 0x9F else c


def replace_controls(text: str) -> str:
    return "".join(_piece(c) for c in text)


def replace_and_clip(text: str, limit: int = STDERR_LINE_LIMIT) -> str:
    pieces = [_piece(c) for c in text]
    total = sum(len(p) for p in pieces)
    if total <= limit:
        return "".join(pieces)
    kept = []
    used = 0
    for p in pieces:
        if used + len(p) > limit:
            break
        kept.append(p)
        used += len(p)
    return "".join(kept) + f" ...（残り {total - used} 文字を省略）"
```

### 2.3 標準エラー出力の 1 行の上限（値、数え方、印）

| 決めること | 決めた内容 |
|---|---|
| 値 | 200 |
| 数え方 | 置き換えた後の文字数（符号位置の数） |
| 切る位置 | 元の文字の切れ目。置き換えた形（`\x1b` の 4 文字）の途中では切らない |
| 印 | ` ...（残り {n} 文字を省略）`（先頭は半角の空白 1 つと点 3 つ）。上限に数えない |
| かける相手 | rpm の標準エラー出力の末尾の各行だけ。Tojimari の文にはかけない |

- 値の理由: rpm の失敗の文は、ふつう 1 行に収まる長さ。200 あれば読むのに足り、最悪でも 5 行 × （200 文字 + 印）で端末の 1 画面に収まる程度になる
- 数え方の理由: 上限の目的は、出る量を抑えること。列を揃えるためではないので、表示幅（`display_width`）は使わない。文字数なら、端末の幅の決まり（曖昧幅など）に左右されず、テストで数を確かめやすい
- 印に残りの文字数を入れる理由: どれだけ省いたかが読む人に分かる。数は置き換えた後の文字数（上限と同じ数え方）
- 元の出力に、たまたま `\x1b` という 4 文字（逆斜線、x、1、b）が入っていたときは、ふつうの 4 文字として数え、その途中で切れることがある。途中で切らないと決めたのは、Tojimari が置き換えた形だけ

### 2.4 置き換えと上限をかける段

**表は `table.render_table` の入口、標準エラー出力は `check._rpm_failure_message` でかける。`runner` と `cli` は変えない。**

表（`render_table`）

- `format` と `schema_version` を確かめた直後に、`report = display.replace_controls_deep(report)` として写しに差し替える。その後ろの処理は今のまま
- 理由
  - 値を使うところごとに置き換えを書くと、書き忘れが起きる（今でも、版、アーキ、入れた元、動いているカーネル、古さの名前と重要度など 10 か所を超える）。入口で 1 回なら、確認が増えても（1.2、1.3）書き忘れようがない
  - 列の幅は、いつも置き換えた後の文字列で数えることになる（依頼の 5、要件 3.2 の 2）。置き換える前の文字列を `display_width` に渡す道が残らない
  - 渡されたレポートは書き換えない（要件 3.1 の 4）。`cli` は同じレポートを JSON にも使うが、`render_table` が受け取った辞書に手を入れないので影響しない
- 知っておくこと: 逆斜線を置き換えないので、置き換えた後に同じ文字列になる別々の値がありうる（例: ESC を含む名前と、`\x1b` という 4 文字を含む名前）。表の「同じ名前の 2 行目は空ける」と件数の数え方は置き換えた後の名前で行うので、この重なりのときだけ JSON とずれうる。rpm のパッケージ名では起こらない組み合わせで、表は確認の補助、元の値は JSON にある（要件 3.1 の 3）ので、このままとする

標準エラー出力（`_rpm_failure_message`）

- 今の `msg += "\n" + err.stderr_tail` を、`stderr_tail` を `"\n"` で分け、各行に `display.replace_and_clip` をかけて `"\n"` でつなぎ直したものに変える
- 分けるのは `split("\n")`。`splitlines()` は使わない。`splitlines()` は `\r` や U+0085 なども行の区切りとして消してしまい、「区切りの `\n` だけを残し、ほかは見える形にする」（要件 3.3 の 1）にならないため。`runner._tail` を通った文字列は `\n` だけでつながっているので、実行のときの行の数は今と同じ（最大 5 行）
- 理由（ほかの段を採らない理由）

| 段 | 採る／採らない理由 |
|---|---|
| `runner`（`_tail`） | 採らない。実行部が見せ方を持つことになる。`CommandError.stderr_tail` の中身（生の末尾）が変わり、`_tail` を変えない（要件 4）にも反する |
| `cli`（書く直前） | 採らない。`cli` が受け取るのは 1 つの文で、どこまでが Tojimari の文で、どこからが外部コマンド由来かを知らない。全体に上限をかけると Tojimari の文も切りうる。分けて渡すには `CheckError` の形を変える必要があり、`str(CheckError)` を確かめている今のテストが変わる |
| `check`（`_rpm_failure_message`） | 採る。Tojimari の文と外部コマンド由来の行をつなぐのがここで、境目を知っているのはここだけ。制御文字が無く短い行なら結果は今と一字一句同じで、今のテストがそのまま通る |

- `CheckError` の文は、標準エラー出力にだけ使う表示用の文（JSON には出ない）。なので、ここで置き換えるのは「表示の直前」（要件 3.1 の 4）に当たる
- これからの決まりとして、`CheckError` の文に外部コマンド由来の文字列を入れるときは、入れるところで `display` の関数を通す。`CheckError` の説明の文字列（docstring）にこの 1 行を足す
- もう 1 つの `CheckError`（`rpm の出力を読み取れませんでした`）は Tojimari の文だけなので変えない

### 2.5 `[注意]` の文にも置き換えをかけるか

**かける。** 2.4 の表の入口の置き換えは `notices` を含むレポート全体が相手なので、`[注意]` の文と先頭の `not_a_guarantee` の一文にも同じ置き換えがかかる。

- 今の注意の文は Tojimari が組み立てた文で、制御文字は無い（`notices.command_reason` は標準エラー出力を入れない）。なので見た目は 1 文字も変わらない
- 理由: 後で注意の理由に外部由来の値が入る変更があっても、表の側は直さずに済む。`[注意]` だけを外す分けを作るほうが手数が多い
- `notices.py` は変えない。JSON の `notices` も変えない

### 2.6 幅の数え方（依頼の 5）

- `display_width` は変えない（`W`、`F`、`A` を 2 桁）。呼ぶのは、2.4 の写しの値だけになる
- 置き換えた形は ASCII だけなので、1 文字 1 桁。C1 の文字（U+0080〜U+009F）は置き換えた後に残らないので、幅の数え方の分かれ目にならない
- #15 の `CommandError.timeout`、`_rpm_failure_message` の Tojimari の文、`notices.command_reason` には触らない

## 3. ファイルごとの変更

| ファイル | 変えること |
|---|---|
| `tojimari/display.py`（新しい） | 2.1・2.2 の定数と関数 |
| `tojimari/table.py` | `from tojimari import display` を足す。`render_table` の入口の 1 行（2.4）。ほかの関数は変えない |
| `tojimari/check.py` | `display` を import する。`_rpm_failure_message` の `stderr_tail` をつなぐところ（2.4）。`CheckError` の docstring に 1 行 |
| `tests/test_display.py`（新しい） | 5.1 |
| `tests/test_table.py`、`tests/test_check.py`、`tests/test_cli.py` | 5.2〜5.4 のテストを足す。今あるテストは変えない |
| `docs/output-1.1.md` | 6 の文を足す |
| `tojimari/runner.py`、`cli.py`、`notices.py`、`packages.py`、`staleness.py`、`history.py`、`processes.py`、`rpmver.py`、`tests/recorded.py` | 変えない |

## 4. エラーと権限不足のときの振る舞い

- 終了コード、どの失敗でどの文を出すかは変えない。変わるのは、終了コード 1 のときの rpm の末尾の行の見せ方だけ
- 一般ユーザーで実行したときの振る舞いは変えない（置き換えは権限に関係しない）
- `replace_controls_deep` は、知らない型をそのまま返す。レポートに無い型が来ても例外にしない
- 想定外の例外のトレースバック（[design-issue-5.md](design-issue-5.md) の 5.4）は扱わない

## 5. テストの方針

- rpm と dnf は実行しない。値はすべて架空のものにし、実機の出力は新しく使わない
- 制御文字は、テストの中で値に足す（`tests/recorded.py` の定数は変えない。`FakeSystem` の引数と、テストの中で作るレポートで足りる）
- 「制御文字が無い」の確かめは、テストの側で独立に書く（`display` の関数を使って確かめない）。例: `[c for c in text if c != "\n" and (ord(c) < 0x20 or 0x7f <= ord(c) <= 0x9f)]` が空であること
- `tests/test_check.py` と `tests/test_runner.py` の途中にある `if __name__ == "__main__":` とその後ろは触らない。足すテストは、今あるクラスに入れるか、その `if` より前に新しいクラスを置く

### 5.1 `tests/test_display.py`

`replace_controls`

- `\x00`、`\t`、`\n`、`\r`、`\x08`、`\x1b`、`\x1f` が、それぞれ `\x00`、`\x09`、`\x0a`、`\x0d`、`\x08`、`\x1b`、`\x1f`（逆斜線で始まる 4 文字）になる
- `\x7f` と C1（`\x80`、`\x9b`、`\x9f`）が 4 文字の形になる。16 進は小文字
- 境目: U+0020（空白）、U+007E、U+00A0 は変わらない
- 全角文字、ASCII の普通の文字、逆斜線（`a\b` や、4 文字の `\x1b`）、U+202E、U+2028 は変わらない
- 空文字列は空文字列

`replace_controls_deep`

- 入れ子の `dict`・`list` の中の文字列が置き換わる。`int`、`bool`、`None` はそのまま。キーは変わらない。キーの順番が保たれる
- 入力が書き換わらない（先に `copy.deepcopy` した写しと、呼んだ後の入力が等しい）

`replace_and_clip`

- ちょうど 200 文字の行は、そのまま（印なし）
- 201 文字の ASCII の行は、先頭 200 文字と ` ...（残り 1 文字を省略）`
- `"a" * 199 + "\x1b" + "b"` は、`"a" * 199` と ` ...（残り 5 文字を省略）`（置き換えた形の途中で切らない）
- ESC が 100 個の行（置き換えた後は 400 文字）は、`\x1b` が 50 個と ` ...（残り 200 文字を省略）`（上限は置き換えた後にかける）
- 全角 201 文字の行は、先頭 200 文字と残り 1 文字の印（文字数で数える）
- `limit` を渡したとき、その値で切る
- 結果に、対象の制御文字が無い

### 5.2 `tests/test_table.py`

- 記録出力から作ったレポートの写しに、制御文字を含む架空の値を足して `render_table` に渡す。足すところは、重点リストの版・アーキ・入れた元、`system.running_kernel`、後から入れたものの名前・版・アーキ・入れた元、古さのセキュリティ更新の名前と重要度（知らない重要度の名前）、再起動待ちの `running_kernel` と `latest_kernel`、`notices` の 1 つの `message`。足す文字は、ESC、`\n`、`\r`、`\t`、`\x08`、`\x7f`、`\x9b` を取り混ぜる
- 出力に、行の区切りの `\n` 以外の対象の文字が 1 つも無い
- 行の数が、制御文字を足す前のレポートの出力と同じ（値の中の `\n` が行を増やさない）
- 置き換えた形（例: `\x1b`）が出力にある
- 列が揃う: 制御文字を足した版の行と、ほかの行で、アーキの列の始まりが見出しの「アーキ」と同じ桁。後から入れたものの表でも同じ
- `render_table` が入力を書き換えない（呼ぶ前の `copy.deepcopy` と等しい）
- 制御文字が無いレポートの出力が変わらないことは、今あるテストが通ることで確かめる

### 5.3 `tests/test_check.py`（`ErrorTest`）

- `stderr_tail="error: \x1b[31mdb\r\x08"` の `exit_status` で、文の 1 行目が `rpm の問い合わせが終了コード 1 で失敗しました` のまま、2 行目が `error: \x1b[31mdb\x0d\x08`（置き換えた形）
- `stderr_tail` が 5 行のとき、文は 6 行（`split("\n")` で数える）。`\r` が行を増やさない
- 201 文字を超える行が、印つきで切られる。同じ `stderr_tail` の短い行は切られない
- `timeout` の文（`rpm の問い合わせが 30 秒で終わりませんでした`）の後ろでも、同じ置き換えになる
- 今ある `test_rpm_stderr_tail_in_message`、`test_rpm_timeout_stderr_tail` はそのまま通る

### 5.4 `tests/test_cli.py`

- 標準エラー出力: `FakeSystem(rpm=CommandError("exit_status", returncode=1, stderr_tail=...))` で、`stderr_tail` に ESC、`\r`、`\x08`、`\x9b` と、200 文字を超える行を入れる。`["check"]` と `["check", "--json"]` の両方で、終了コードが 1、標準出力が空、標準エラー出力に行の区切りの `\n` 以外の対象の文字が無い、1 行目が `tojimari: rpm の問い合わせが終了コード 1 で失敗しました`、長い行に印がある
- JSON: `FakeSystem(kernel="6.12.0-55.el10.aarch64\x1b[2J", dnf=recorded.DNF_ALL.replace("baseos", "base\x1b[31mos"))` で、`["check", "--json"]` の標準出力が `json.dumps(check.collect(同じ FakeSystem), ensure_ascii=False, indent=2) + "\n"` と等しい。`json.loads` した `system.running_kernel` が、足した値そのまま（ESC を含む）
- 表: 同じ `FakeSystem` で `["check"]` の標準出力に、行の区切りの `\n` 以外の対象の文字が無く、`\x1b[2J`（置き換えた形）が「動いているカーネル:」の行にある

## 6. `docs/output-1.1.md` に足す文

実装と同じ PR で足す（振る舞いと文書が同じときに変わるようにする）。

- 冒頭の「更新」の行の先頭に、`2026-11-22 表と標準エラー出力で、外部コマンド由来の制御文字を見える形に置き換える決まりを足した（issue #16、1.3・3.2）。要件は [task-issue-16.md](task-issue-16.md)。` を足す
- 1.3 の「1 のときは、理由を標準エラー出力に出す。…」の下に 1 行: `- 理由のうち外部コマンドの出力から来た行は、制御文字を見える形に置き換え、1 行の長さに上限を付ける（3.2）`
- 3.2 の最後に、次を足す

```
- 表に出す値のうち、制御文字（C0 の U+0000〜U+001F、DEL の U+007F、C1 の U+0080〜U+009F。改行、タブ、復帰を含む）は、`\x` と 16 進の小文字 2 桁の形（例: ESC は `\x1b`、改行は `\x0a`）に置き換えて出す。端末の表示が変わらないように、見える形にするためのもの。表の改行は行の区切りだけになる
- 置き換えるのは C0、DEL、C1 だけ。それ以外の文字（Unicode の書式の文字の U+202E、行の区切りの U+2028・U+2029 など）は置き換えない
- 逆斜線 `\` そのものは置き換えない。値にもとから `\x1b` という文字の並びがあると、置き換えた形と見分けがつかない。読み分けが要るときは JSON を見る（JSON の値は書き換えない）
- 列の幅は、置き換えた後の文字列で数える
- 終了コード 1 のときに標準エラー出力に出す理由（1.3）のうち、rpm の標準エラー出力の末尾（最大 5 行）の各行にも、同じ置き換えをかける。行の区切りの改行だけはそのまま出す
- その各行は、置き換えた後の文字数で 200 文字までとする。超えた分は出さず、行の終わりに ` ...（残り N 文字を省略）` を付ける（N は省いた文字数）。置き換えた形の途中では切らない。Tojimari の文（`rpm の問い合わせが終了コード 1 で失敗しました` など）は切らない
```

## 7. 範囲の外で気づいたこと（PM に返す）

要件の 2 に「JSON の値は、`json.dumps` が制御文字を `\u001b` の形で出すので、JSON 側は変えない」とある。クラウド実行環境の Python 3.11 で確かめたところ、今の呼び方（`ensure_ascii=False`）では次のとおりだった。

- C0（U+0000〜U+001F）は `\u001b` の形で出る
- DEL（U+007F）と C1（U+0080〜U+009F）は、そのままの文字で出る

つまり、`tojimari check --json` を端末にそのまま出すと、DEL と C1 は生の文字で端末に届く。
今回は、issue と要件が JSON を変えないと決めている（要件の 4、終わりの条件の「`--json` の出力は変更の前と同じ」）ので、JSON には手を入れない。扱うかどうか（例: 別の issue にする）は PM が決める。この設計は、どちらに決まっても変わらない。

## 8. 実装担当への指示

作業ブランチは今のブランチ。新しい依存は入れない。rpm と dnf は実行しない。

1. `tojimari/display.py` を作る
   - 先頭の説明: `"""外部コマンド由来の文字列を、表示の前に見える形にする。何も実行しない。"""` のような 1 行（「安全」と読める言葉を使わない）
   - `STDERR_LINE_LIMIT = 200`、`replace_controls`、`replace_controls_deep`、`replace_and_clip` を 2.2 のとおりに書く。ほかの `tojimari` のモジュールを import しない
2. `tojimari/table.py`
   - `from tojimari import display` を足す
   - `render_table` の `schema_version` の確かめの直後に `report = display.replace_controls_deep(report)` を入れる。ほかは変えない（`display_width` も動かさない）
3. `tojimari/check.py`
   - import を `from tojimari import display, history, notices, packages, processes, staleness` にする
   - `_rpm_failure_message` の最後を次の形にする。Tojimari の文の 4 つの枝は 1 文字も変えない

     ```python
     if err.stderr_tail:
         lines = [display.replace_and_clip(line) for line in err.stderr_tail.split("\n")]
         msg += "\n" + "\n".join(lines)
     return msg
     ```

   - `CheckError` の docstring に、「文に外部コマンド由来の文字列を入れるときは、入れるところで display の関数を通す」を足す
4. テストを 5.1〜5.4 のとおりに足す。今あるテストは 1 つも変えない。`tests/recorded.py` は変えない
5. `docs/output-1.1.md` に 6 の文を足す。ほかの節は変えない
6. `runner.py`、`cli.py`、`notices.py` は変えない。差分にこれらが出たら、やり直す
7. リポジトリの最上位で `python3 -m unittest` を実行し、すべて通ることを確かめる
8. 確かめること
   - `git diff` に、実機の生の情報（ホスト名、ユーザー名、アドレス、ホームのパス）が無い
   - コード、テスト、文書に、「安全になる」「防げる」「無害」と読める言葉を足していない
   - 制御文字はテストのソースに生で書かず、`"\x1b"` のような書き方にする（ファイルの中身に生の制御文字を入れない）

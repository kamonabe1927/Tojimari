# 設計: 今動いているかの印（issue #14、1.1-C）

- 作成日: 2026-11-22
- 書いた人: テックリード
- 要件: [task-issue-14.md](task-issue-14.md)。出力の形は [output-1.1.md](output-1.1.md) の 2.3・2.4・2.8・3.5
- 土台: [design-issue-5.md](design-issue-5.md)、[design-issue-12.md](design-issue-12.md)、[design-issue-13.md](design-issue-13.md)（分け方はそのまま守る）

差し戻しは無い。PM が直した要件（ルートディレクトリで見分ける、サービスの判定、`sudo` の親を除かない）で設計できる。
この文書の例に出てくるパス、pid、cgroup のパスはすべて架空のもの。

## 1. 全体の形

```
check.collect
  ├─ system.process_scan()   … /proc を 1 回見回し、生の値を返す（runner.py）
  ├─ processes.classify()    … 除くもの・読めなかった数・結びつける候補を決める（新モジュール）
  ├─ system.rpm_files()      … rpm -qa のファイル一覧を 1 回だけ取る（runner.py）
  ├─ packages.parse_rpm_files() … 候補のパスを持つ版だけを取り出す
  └─ processes.apply_marks() … 重点リストと後から入れたものの版に印を付ける
```

- `runner.py` は実行と読み取りだけ（解釈しない）。解釈は新しい `tojimari/processes.py` に置く。`processes.py` は何も実行せず、`/proc` も読まない
- 順番は「見回し → rpm」。見回しが失敗したら rpm は呼ばない（数秒かかる呼び出しを無駄にしない）。Tojimari は外部コマンドを 1 つずつ終わるまで待つので、見回しの瞬間に Tojimari の子プロセスは居ない見込みだが、要件どおり除く処理は入れる（4.4）
- 新しい依存は無い。使うのは `os` と、#5 と同じ `/usr/bin/rpm` だけ

## 2. 実行ファイルからパッケージの版を引く方法（決め直し）

### 2.1 決めたこと

前回の提案どおり、**`rpm -qa --queryformat` でファイル一覧を 1 回取り、その中から引く**。`rpm -qf` は使わない。

```python
RPM_FILES_ARGV = [
    "/usr/bin/rpm",
    "-qa",
    "--queryformat",
    "P\\t%{NAME}\\t%|EPOCH?{%{EPOCH}}:{}|\\t%{VERSION}\\t%{RELEASE}\\t%{ARCH}\\n"
    "[F\\t%{FILENAMES}\\n]",
]
```

出力は、版ごとに「`P` の行が 1 つ、その版が持つパスの数だけ `F` の行」が続く形になる。

```
P<TAB>examplepkg<TAB><TAB>1.0<TAB>1.el10<TAB>aarch64
F<TAB>/usr/bin/example
F<TAB>/usr/share/doc/examplepkg/README
```

- `P` の行の中身は、#5 の `RPM_LIST_ARGV`（実機で確かめ済みの形）の先頭に `P` と TAB を足しただけ。配列の繰り返し（`[...]`）の中には `%{FILENAMES}` だけを置く。繰り返しの中に名前や epoch の条件式を入れる書き方（`%{=NAME}` など）は、実機で確かめていない形を増やすので使わない
- 読み取り（`packages.parse_rpm_files`）は、候補のパス（見回しで得た実行ファイルのパスの集まり）に一致する `F` の行だけを残し、`パス → 版のキーの集まり` を返す。1 つのパスを複数の版が持てば、すべての版が入る（要件 3.1 の 2）

### 2.2 理由（`rpm -qf` を採らない理由）

| 取り方 | 採らない／採る理由 |
|---|---|
| `rpm -qf` をパスごとに呼ぶ | どのパッケージも持たないパス（手でビルドしたものなど。普通にある）で終了コードが 0 以外になり、rpm のデータベースが読めないなどの本当の失敗と終了コードで区別できない。区別するには rpm が出す文（言語の設定で変わる）を読むことになり、「形を推測で作らない」に反する。本当の失敗を「持ち主なし」と読み違えると、動いているのに印が無い表示になる。また呼ぶ回数が実行ファイルの種類の数（数十〜百数十）になり、合計の時間に上限を付けにくい |
| `rpm -qf` に複数のパスをまとめて渡す | 答えの行に聞いたパスが入らず、持ち主なしの文と、複数の版が持つときの複数行が混ざるので、どの行がどのパスの答えかを取り違えうる（PM の申し送りの懸念のとおり） |
| `rpm -qa` のファイル一覧（採る） | 呼び出しが 1 回で、成功と失敗が終了コードだけで決まる。行の形は Tojimari が決める。`rpm -qf` と違い、聞いたパスそのものにファイルシステムで触らない（`rpm -qf` はパスを確かめに行くので、ネットワーク越しの置き場所などで待たされうる） |

どちらの取り方でも変わらない限界: rpm の記録のパスと `/proc/<pid>/exe` のパスが文字どおり一致したときだけ結びつく。`/proc/<pid>/exe` はリンクをたどり終えた実際のパスなので、rpm の記録がリンクを通るパス（例: `/bin/...`）で書かれたファイルは結びつかない。AlmaLinux 10 のパッケージは実行ファイルを `/usr/bin` などの実際のパスで記録している見込みで、実機確認（9）の sshd、systemd、htop で確かめる。

### 2.3 失敗の扱い

| 起きたこと | 扱い |
|---|---|
| rpm が見つからない、30 秒で終わらない、終了コードが 0 以外、実行できない（`CommandError`） | `checks.running_processes` を `unavailable` にする。理由は `notices.command_reason("rpm", 30, err)`。標準エラー出力は注意に入れない（#13 と同じ） |
| 出力が決めた形でない（`ParseError`）: 空でない行が `P` TAB でも `F` TAB でも始まらない、`P` の行の項目が 5 つでない・名前や version や release が空・epoch が数字でない、`P` の行より前に `F` の行がある、`P` の行が 1 つも無い | `unavailable`。理由は「rpm の出力を読み取れなかった」 |
| 候補のパスをどの版も持たない | 失敗ではない。そのプロセスは印のもとにならないだけ |

- 形の合わない行を読み飛ばさずに全体を `unavailable` にするのは、#5 の `parse_rpm_list` と同じ考え方（分からない形を推測で読まない）。改行を含むファイル名を持つパッケージが 1 つでもあるとこの確認が丸ごと `unavailable` になるが、黙って誤った結びつけをするよりよいと判断した
- `F` の行のパスの中身は確かめない（TAB より後ろをそのままパスとする）。候補のパスと文字どおり一致するかだけを見るので、変わった値があっても誤って結びつかない
- `unavailable` でも、ほかの確認は続け、終了コードは 0（要件 3.3 の 4）

### 2.4 時間と大きさの見込み

- 呼び出しは 1 回で、時間の上限は今の `RPM_TIMEOUT`（30 秒）をそのまま使う。上限は変えない
- 見込み: 出力は入っているファイルの数だけの行（数十万行、数十 MB）になり、rpm はすべての版の記録を読むので、`rpm -qa`（#5）より長く数秒かかる。30 秒には収まる見込みだが、手元に AlmaLinux が無く確かめられていない。実機確認（9 の手順 A）で時間と大きさを本人に測ってもらう
- 30 秒に近い、または超えるようなら、上限を黙って延ばさず、テックリードに戻して取り方を決め直す（そのときも表示は `unavailable` になるだけで、ほかの確認は続く）
- 読み取りは、出力の全体を行のリストに分けずに 1 行ずつ進める（`io.StringIO` で回すなど）。数十万個の文字列を一度に持たないため。`run_command` は変えない

## 3. `/proc` の見回し（`runner.py` が返す生の値）

### 3.1 返す形

`processes.py` に形だけを定義し、`runner.py` が詰めて返す（`history.HistoryError` を `runner.py` が投げるのと同じ向きの依存）。

```python
@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    stat: str | None                 # /proc/<pid>/stat の中身。読めなければ None
    exe: str | None                  # os.readlink("/proc/<pid>/exe") の値
    exe_error: str | None            # None | "gone" | "permission" | "other"
    root: tuple[int, int] | None     # os.stat("/proc/<pid>/root") の (st_dev, st_ino)
    root_error: str | None           # None | "gone" | "permission" | "other"
    cgroup: str | None               # /proc/<pid>/cgroup の中身。読めなければ None

@dataclass(frozen=True)
class ProcessScan:
    self_pid: int                    # os.getpid()
    own_root: tuple[int, int]        # os.stat("/") の (st_dev, st_ino)
    processes: list[ProcessInfo]

class ScanError(Exception):
    """/proc を見回せなかった。"""
```

### 3.2 読み方（`runner.scan_processes(proc_dir="/proc", root_dir="/")`）

1. `os.stat(root_dir)` で自分のルートを取る。`os.listdir(proc_dir)` で名前を取り、ASCII の数字だけの名前を pid とする。どちらかが `OSError` なら `ScanError`
2. pid ごとに、`stat` → `exe` → `root` → `cgroup` の順に 1 回ずつ読む。4 つは別々に `try` で囲み、1 つが読めなくても残りを読む
3. `OSError` の分け方: `FileNotFoundError` と `ProcessLookupError` は `"gone"`、`PermissionError` は `"permission"`、そのほかは `"other"`。`stat` と `cgroup` は理由を分けず `None` にする
4. `stat` と `cgroup` はバイト列で読み、UTF-8（`errors="replace"`）で文字列にする。プロセス名に UTF-8 でない値がありうるため
5. 読むのはこの 4 つだけ。`/proc/<pid>/cmdline` と `environ` は読まない（コマンドの引数や環境変数に秘密の値が入りうるため。禁止事項 1 の考え方）

`System.process_scan()` は `scan_processes()` を呼ぶだけ。`proc_dir` と `root_dir` を引数にするのは、テストで一時ディレクトリに作った架空の木を読ませるため。

## 4. 解釈（`processes.py`）

### 4.1 判定の順番（`classify`）

プロセスごとに上から順に見て、最初に当たったところで決める。

| 順 | 条件 | 扱い |
|---|---|---|
| 1 | pid が `self_pid`、または ppid をたどると `self_pid` に着く（4.4） | 除く。数えない |
| 2 | `stat` が読めて、カーネルのスレッドかゾンビ（4.2） | 除く。数えない |
| 3 | `exe_error` が `"gone"` | 除く。数えない（見回しているあいだに終わったもの。`stat` が読めなかったカーネルのスレッドもここに入る） |
| 4 | `exe_error` が `"permission"` か `"other"` | `unreadable` に 1 足す。結びつけない |
| 5 | `root_error` が `"gone"` | 除く。数えない |
| 6 | `root_error` が `"permission"` か `"other"` | `unreadable` に 1 足す。結びつけない |
| 7 | `root` が `own_root` と違う（4.3） | 除く。数えない（コンテナや chroot の中） |
| 8 | それ以外 | 候補にする。パスは末尾の ` (deleted)` を 1 つ取り除いたもの（4.5）、サービスかどうかは 4.6 |

- 1 つのプロセスが `unreadable` に数えられるのは 1 回だけ（4 で数えたら 6 は見ない）
- `"other"`（権限以外の読み取りの失敗）も `unreadable` に数える。「読めなかったので印のもとにできず、実は動いているかもしれない」という注意の意味に合うため。注意の文は「権限が無くて」のままにする（めったに起きず、文を分けるほどではない）
- root なしのとき、コンテナの中のほかの利用者のプロセスは 4 で `unreadable` に数えられる（ルートを比べる前に実行ファイルが読めないため）。数が多めに出る向きなので、注意の意味は誤らない

### 4.2 カーネルのスレッドとゾンビの除き方

`/proc/<pid>/stat` から見分ける。`stat` はほかの利用者のプロセスでも読める。

- 読み方（`parse_stat`）: 最後の `)` より後ろを空白で分ける。プロセス名（2 番目の項目）は括弧で囲まれ、空白や括弧を含みうるので、先頭からは分けない。後ろの 1 番目が状態、2 番目が ppid、7 番目が flags（全体では 3、4、9 番目）。形が合わなければ `None`（その場合 ppid も不明として扱う）
- カーネルのスレッド: flags に `PF_KTHREAD`（`0x00200000`）が立っている
- ゾンビ: 状態が `Z`（終わっていて実行ファイルを持たない）。`X` も同じ扱い

理由:

- `exe` が読めないことだけでは見分けられない。root ならカーネルのスレッドは「無い」と返るが、root なしだと「権限が無い」と返ることがあり、数百個のカーネルのスレッドが `unreadable` に数えられてしまう（要件 3.3 の 3「カーネルのスレッドはこの数に入れない」に反する）
- 「pid が 2 か、ppid が 2」で見分ける方法も考えたが、慣習に頼るので、カーネルが持つ印（flags）を使う。`cmdline` が空かで見る方法は、3.2 の 5 の理由で採らない
- クラウド実行環境（AlmaLinux ではない Linux）の `/proc` では、この読み方でカーネルのスレッドが分かれることを確かめた。AlmaLinux の実機では、実機確認（9 の手順 B）で確かめる

分かっている限界: スレッドの親（最初のスレッド）だけが終わり、残りのスレッドが動き続けているプロセスは、ゾンビに見えるので印のもとにならない。めったに無く、`running_is_snapshot` の注意の範囲とする。

### 4.3 ルートディレクトリの比べ合わせ

- 比べるのは `(st_dev, st_ino)` の組。`ProcessInfo.root == ProcessScan.own_root` なら同じルート
- 自分の側は `os.stat("/")`（見回しの最初に 1 回）。相手の側は `os.stat("/proc/<pid>/root")`（リンクをたどった先、つまりそのプロセスのルートディレクトリそのものの値）。`os.lstat` は使わない（リンク自身の値になり、比べられない）
- 読めないとき: `"permission"` と `"other"` は `unreadable` に数えて結びつけない。`"gone"` は終わったものとして数えない（4.1 の 5、6）
- マウントの名前空間は見ない。`PrivateTmp=` などで名前空間だけが違う systemd のサービスは、ルートのディレクトリが同じなので 7 に当たらず、候補になる
- Tojimari 自身が chroot の中で動かされたときは、その chroot と同じルートのプロセスだけが候補になる（要件の「Tojimari と違うルート」のとおり）

### 4.4 Tojimari 自身と子孫の除き方

- 自分: `ProcessScan.self_pid`（`os.getpid()`）と同じ pid
- 子孫: `stat` が読めたプロセスの `pid → ppid` の表を作り、各プロセスから ppid を上へたどる。`self_pid` に着けば子孫。ppid が 0、表に無い、または表の大きさの回数たどっても着かなければ子孫でない（輪になっていても止まる）
- 親や祖先（`sudo`、シェル）は除かない。たどるのは下から上への向きで、`self_pid` より上は見ない
- `stat` が読めなかったプロセスは ppid が分からないので、子孫として除けない。Tojimari の子は同じ利用者で動くので `stat` は読める見込みで、また 1 の順番のとおり見回しの瞬間に子は居ない見込み

### 4.5 ` (deleted)` の扱い

- `exe` の末尾が ` (deleted)`（先頭に空白 1 つ）なら、それを 1 回だけ取り除いたパスで引く（要件 3.1 の 4）
- 本当に ` (deleted)` で終わる名前のファイルとは見分けられない。その場合はどの版も持たないパスになるだけで、誤った印にはならない

### 4.6 システムのサービスの判定（`is_system_service(cgroup の中身)`）

1. 中身を行に分け、`0::` で始まる行（cgroup v2 の行）を 1 つ探す。無ければ偽
2. `0::` より後ろをパスとし、`/` で分けて空でない部分を並べる
3. 最初の部分が `user.slice` なら偽
4. どれかの部分が `user@` で始まり `.service` で終わるなら偽
5. どれかの部分が `.service` で終わるなら真。それ以外は偽

- `cgroup` が `None`（読めなかった）なら偽。候補にはする（要件 3.2 の 4）
- 4 は、PM が任せた細かな判定。利用者ごとの systemd（`user@<数字>.service`）は systemd が `/user.slice` の下に置くので 3 で足りる見込みだが、置き場所によらず「利用者ごとの systemd とその下はシステムのサービスに数えない」という要件の意味を守るために足した。外す向きの判定なので、誤って印を付けることは無い
- `Delegate=yes` の子の cgroup（`/system.slice/<名前>.service/<子>`）は 5 で真になる
- 真にならないもの: ログインのセッション（`session-*.scope`）、root が手で動かした `*.scope`、PID 1 の systemd 自身（`/init.scope`）。PID 1 は「systemd が起動したサービス」ではないので偽でよい。`systemd` のパッケージには、同じパッケージが持つサービス（journald など）のプロセスから印が付く
- コンテナの中の systemd が作る `.service`（ホストから見ると `…/<コンテナの cgroup>/system.slice/<名前>.service`）は 5 だけなら真になるが、ルートが違うので 4.1 の 7 で先に除かれる
- 消された cgroup はパスの末尾に ` (deleted)` が付く。そのときは最後の部分が `.service` で終わらなくなり偽になりうる。まもなく終わるプロセスなので、そのままにする

### 4.7 印を付ける（`build_marks`、`apply_marks`）

- `build_marks(候補, パス → 版のキーの集まり)` は `版のキー → サービスか（真偽）` を返す。キーがあれば `running` は真。同じ版に複数のプロセスが結びつけば、1 つでもサービスなら真
- 版のキーは `packages.version_key(name, epoch, version, release, arch)`（#5 と同じ。epoch 無しは `"0"` と同じに扱う）
- `apply_marks(focus, user_installed, marks)` は、重点リストの各版と、後から入れたものの各版に `running` と `systemd_service` を足す。`marks` が `None`（`unavailable`）なら両方 `null`
- 項目は版の要素の最後に足す（kernel の版では `is_running_kernel` の後ろ）。output-1.1.md の 2.3 の表の順
- kernel の版は特別扱いしない。`kernel` のパッケージは実行ファイルを持たないので、自然に `false` になる

## 5. 出力

### 5.1 `checks.running_processes`

`checks` の中の順は `focus_packages`、`user_installed`、`staleness`、`running_processes`。

| 場合 | `status` | `unreadable` | 各版の印 |
|---|---|---|---|
| 見回しと rpm が成功 | `ok` | 数（0 以上） | 真偽 |
| `ScanError` | `unavailable` | `null` | `null` |
| rpm の `CommandError`、`ParseError` | `unavailable` | `null` | `null` |

### 5.2 注意（`notices.py`）

- `RUNNING_IS_SNAPSHOT` の後ろに 2 文を足す: 「Docker コンテナの中で動いているものには印を付けません。印は実行ファイルのパスで付けるため、更新した後に再起動していないプロセスは、新しい版の印として出ます。」
- `RUNNING_UNAVAILABLE`: 「動いているプロセスを確認できなかったため（理由: {reason}）、今動いているかの印を付けていません。「どれも動いていない」という意味ではありません。」
- `RUNNING_PARTIAL`: 「{count} 個のプロセスは、権限が無くて実行ファイルかルートディレクトリを読めなかったため、印のもとにしていません。印の無い版の中にも、動いているものがありえます。」
- 理由の文: `/proc` を見回せなかったときは「/proc を読み取れなかった」、rpm は 2.3 のとおり
- 出す順は、output-1.1.md の 2.4 の表の順（`last_update_unavailable` の後ろに `running_unavailable`、`running_partial`）
- 注意の文に、パス、pid、サービスの名前を入れない

### 5.3 表（`table.py`）

- 印の文言: `<- 今動いている（systemd のサービス）`（`systemd_service` が真）、`<- 今動いている`（`running` だけ真）。`false` と `null` は何も付けない
- 付け方は、今の kernel の `<- 動いている` と同じ（行の終わりに空白 2 つを挟んで足す）。後から入れたものの表にも同じ付け方で足す
- kernel の印とプロセスの印が同じ行に並ぶことは無い見込みだが、もし両方が真なら kernel の印を先にして両方を付ける（どちらかを黙って捨てない）
- 版の要素に `running` が無い JSON（#13 までの出力）を渡されても、印を付けずに表を出す（`.get` で読む）

## 6. 要件に書かれていない細部（今回決めたこと）

- 見回し → rpm の順にし、見回しが失敗したら rpm を呼ばない（1）
- `rpm -qa`（#5 の一覧）とファイル一覧は別々に呼ぶ。ファイル一覧の `P` の行から #5 の一覧を作り直すことはしない（ファイル一覧が失敗しても、重点リストなどの表示を続けるため）
- 権限以外の読み取りの失敗も `unreadable` に数える（4.1）
- 利用者ごとの systemd の判定を 1 つ足した（4.6 の 4）
- `cmdline` と `environ` は読まない（3.2 の 5）

## 7. 仕様の文書の直し

- [spec-1.1.md](spec-1.1.md) の 2.4 の 1 つ目の項目は「`rpm -qf` でパッケージに紐づけ」と書いていた。目的（動いているプロセスの実行ファイルを rpm の記録でパッケージに結びつける）は変えず、取り方だけが変わるので、「rpm の記録でパッケージに紐づけ」に直し、取り方の項目に `rpm -qa` のファイル一覧を使うことと理由の場所（この文書の 2）を足した
- [requirements.md](requirements.md) の「使われているかの表示（2026-11-20）」は決めた経緯の記録なので、そのままにする。その下の「取り方（2026-11-22）」は「rpm の `--queryformat` 付きの問い合わせ」と書いてあり、食い違わない

## 8. 手元で確かめられていないこと

クラウド実行環境には AlmaLinux も rpm の記録も無い。次は実機確認（9）で本人に確かめてもらう。

- `RPM_FILES_ARGV` の出力が 2.1 の形になること、時間と大きさ（2.4）
- rpm の記録のパスが `/proc/<pid>/exe` のパスと一致すること（2.2 の限界）
- `stat` の flags でカーネルのスレッドが分かれること（4.2）
- ホストのサービスのルートが `/` と同じで、コンテナの中のプロセスのルートが違うこと（4.3）

## 9. 実機確認の手順への申し送り（PM の 7 に足す・置き換える）

[task-issue-14.md](task-issue-14.md) の 7 の表を元にし、次を足す・置き換える。セキュリティ担当が PR を作るときに整える。出力を貼るときは置き換えてから貼る（禁止事項 7）。

| 手順 | コマンド | 正しいときの表示 |
|---|---|---|
| A（足す） | `time rpm -qa --queryformat 'P\t%{NAME}\t%|EPOCH?{%{EPOCH}}:{}|\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n[F\t%{FILENAMES}\n]' \| cut -c1-2 \| sort \| uniq -c` | 行の先頭が `P` と TAB、`F` と TAB の 2 種類だけ。`P` の数が `rpm -qa \| wc -l` と同じ。かかった時間が 30 秒より十分に短い（時間と、`... \| wc -c` の大きさを PR に書いてもらう） |
| B（足す） | sudo なしで `python3 -B -m tojimari check --json` を実行し、`checks.running_processes.unreadable` を見る。あわせて `ps -e --no-headers -o ppid \| grep -cvw 2` | `unreadable` が、カーネルのスレッド以外のプロセスの数（後ろのコマンドのおおよその数）以下であること。カーネルのスレッド（数百個）が数に入っていないことの確かめ |
| 5a（置き換え） | `PrivateTmp=yes` か `ProtectSystem=` のあるサービスを 1 つ選び（例: `systemctl show -p PrivateTmp,ProtectSystem,MainPID systemd-logind`。違えば別のサービスでよい）、その MainPID で `sudo readlink /proc/<MainPID>/ns/mnt /proc/1/ns/mnt` と `sudo stat -L -c '%d %i' / /proc/<MainPID>/root` | `readlink` の 2 行は違い（マウントの名前空間が別）、`stat` の 2 行は同じ（ルートは同じ）。この前提が成り立てば、外さないことは単体テストで確かめている |
| 7（置き換え） | Docker が動いていれば、`sudo docker run --rm -d almalinux:10 sleep 300` の後に、`sudo stat -L -c '%d %i' / /proc/$(pgrep -n -x sleep)/root`（本人の判断で行う。取得の通信が起きる。ホストでほかに `sleep` を動かしていないこと） | 2 行が違う（コンテナの中のプロセスはルートが違う）。この前提が成り立てば、結びつけないことは単体テストで確かめている |

- 5a と 7 を置き換える理由: PM の元の手順は、選んだパッケージが重点リストにも後から入れたものにも無いと表で確かめられない。判定そのものは単体テストで確かめ、実機では判定の前提（ルートが同じ・違う）だけを確かめる形にした。Tojimari に途中の結果を出す機能は足さない（パスを出さない決まりのため）
- PM の手順 2 の「`systemd` にも印が付く」は、`systemd` の行に「今動いている（systemd のサービス）」が付くことを指す（4.6 のとおり、同じパッケージのサービスのプロセスから付く）

## 10. 実装指示

### 10.1 変えるファイル

| ファイル | 変更 |
|---|---|
| `tojimari/processes.py`（新しく作る） | `ProcessInfo`、`ProcessScan`、`ScanError`、`parse_stat`、`is_system_service`、`strip_deleted`、`classify`、`build_marks`、`apply_marks`。標準ライブラリの `dataclasses` と `tojimari.packages` だけを使う。`runner` を読み込まない（循環を避ける）。何も実行せず、ファイルも読まない |
| `tojimari/packages.py` | `RPM_FILES_ARGV` と `parse_rpm_files(text, wanted)` を足す。`P` の行の項目の確かめは `parse_rpm_list` と同じ決まりなので、共通の小さな関数に切り出して両方から使う（`parse_rpm_list` の結果は変えない） |
| `tojimari/runner.py` | `scan_processes(proc_dir="/proc", root_dir="/")` と、`System.process_scan()`、`System.rpm_files()` を足す。`processes` を読み込む。解釈はしない |
| `tojimari/check.py` | `_collect_running(system)` を足し、`collect` から呼ぶ。`checks.running_processes` を足し、`processes.apply_marks` で印を付け、`notices.build_notices` に理由と数を渡す |
| `tojimari/notices.py` | 5.2 の文言と、`build_notices` の引数 `running_problem: str \| None = None`、`running_unreadable: int = 0`（既定値つき。今の呼び出しを壊さない） |
| `tojimari/table.py` | 5.3 の印。`_focus_rows` の 2 つ目の値を「付ける印の文字列（無ければ空）」に変え、後から入れたものの行にも同じ形で印を付ける |
| `tests/recorded.py` | `RPM_FILES`（架空の記録出力）と、`FakeSystem` の引数 `processes`、`rpm_files` |
| `tests/test_processes.py`（新しく作る）、`tests/test_packages.py`、`tests/test_runner.py`、`tests/test_check.py`、`tests/test_table.py` | 10.3 |

`cli.py`、`history.py`、`staleness.py`、`rpmver.py` は変えない。

### 10.2 関数の決まり

```python
# packages.py
def parse_rpm_files(text: str, wanted) -> dict[str, frozenset[tuple]]:
    """wanted（パスの集まり）にあるパスだけを残し、パス → 版のキーの集まりを返す。
    形が合わなければ ParseError（2.3）。"""

# processes.py
def parse_stat(text: str) -> tuple[str, int, int] | None:      # (状態, ppid, flags)
def is_system_service(cgroup_text: str | None) -> bool:
def strip_deleted(path: str) -> str:
def classify(scan: ProcessScan) -> tuple[list[tuple[str, bool]], int]:
    """(候補の (パス, サービスか) の並び, unreadable の数)。4.1 の順で決める。"""
def build_marks(candidates, file_map) -> dict[tuple, bool]:    # 版のキー → サービスか
def apply_marks(focus: dict, user_installed: dict, marks: dict | None) -> None:

# check.py
def _collect_running(system) -> tuple[dict | None, dict, str | None]:
    """(marks, checks.running_processes, unavailable のときの理由)。"""
```

`_collect_running` の流れ:

1. `system.process_scan()`。`processes.ScanError` なら `unavailable`（理由「/proc を読み取れなかった」）で返す。rpm は呼ばない
2. `processes.classify(scan)`
3. `system.rpm_files()` → `packages.parse_rpm_files(text, 候補のパスの集まり)`。`CommandError` と `ParseError` は 2.3 のとおり `unavailable`。候補が 0 個でも rpm は呼ぶ（rpm に問い合わせられないのに `ok` と出さないため）
4. `processes.build_marks` → `({...}, {"status": "ok", "unreadable": 数}, None)`

守ること:

- 実行ファイルのパス、pid、cgroup のパスを、JSON、表、注意、例外の文のどれにも入れない
- `runner.scan_processes` は読むだけ。書き込み、シグナル、`systemctl` の呼び出しをしない。`cmdline` と `environ` を読まない
- 新しい依存を入れない。`RPM_TIMEOUT` を変えない

### 10.3 テストの観点

値はすべて架空のものにする（パス、pid、cgroup のパス、`st_dev` と `st_ino`）。実機の `/proc` と rpm を前提にしない。

`tests/recorded.py`:

- `FakeSystem(processes=None, rpm_files=RPM_FILES)`。`processes` の既定は「プロセスが 0 個の `ProcessScan`」。どちらも値が例外なら投げる（今の `_give` と同じ）。`rpm_files` が呼ばれたかを記録する
- `RPM_FILES` は、今の `RPM_ALL_INSTALLED` と後から入れたものの記録に合う版の `P` の行と、架空の `F` の行（sshd、sudo、systemd とそのサービスの実行ファイル、htop など）

`tests/test_processes.py`:

- `parse_stat`: 普通の行、プロセス名に空白と `)` を含む行、形が合わない行（`None`）
- `classify`
  - 結びつける: 同じルートの普通のプロセス。マウントの名前空間だけが違う想定のもの（ルートの値が同じ）。Tojimari の親（`self_pid` の ppid にあたる `sudo`）と、そのまた親
  - 除く（数えない）: `self_pid`、`self_pid` の子と孫（ppid をたどる）、カーネルのスレッド（flags）、ゾンビ（状態 `Z`）、`exe_error` が `gone`、`root_error` が `gone`、ルートが違う（`st_dev` だけ違う、`st_ino` だけ違う、の両方）
  - `unreadable` に数える: `exe_error` が `permission`、`root_error` が `permission`、両方が `permission` のとき 1 回だけ数える、`other`
  - root なしを想定した場合: カーネルのスレッドの `exe_error` が `permission` でも数えない
  - `stat` が `None` のプロセス（除かれず、`exe` が読めれば候補になる）、ppid が輪になっていても止まる
  - ` (deleted)` を取り除いたパスが候補になる
- `is_system_service`: `/system.slice/<名前>.service`（真）、`Delegate` の子（`/system.slice/<名前>.service/<子>`、真）、`/user.slice/.../session-<数字>.scope`（偽）、`/user.slice/.../user@<数字>.service/app.slice/<名前>.service`（偽）、`user.slice` の外に置かれた `user@<数字>.service` の下（偽）、`/init.scope`（偽）、`/system.slice/<名前>.scope`（偽）、`0::` の行が無い（偽）、`None`（偽）、cgroup v1 の行が混ざった中身から `0::` の行を選ぶ
- `build_marks` と `apply_marks`: 1 つのパスを 2 つの版が持つとき両方に印、同じ版にサービスとそうでないプロセスがあるとき `systemd_service` が真、`cgroup` が読めないプロセスは `running` だけ真、どの版も持たないパス、`marks` が `None` のとき両方 `null`、kernel の版は `false`、`systemd_service` が真なら `running` も真

`tests/test_packages.py`:

- `RPM_FILES_ARGV` の中身（`/usr/bin/rpm`、`-qa`、`--queryformat` と決めた文字列）
- `parse_rpm_files`: 普通の出力、`wanted` に無いパスは残さない、epoch あり・無し、ファイルを持たない版、同じパスを持つ 2 つの版、空行は飛ばす、2.3 の `ParseError` の各場合

`tests/test_runner.py`:

- `scan_processes` に一時ディレクトリの架空の木を渡す（数字の名前のディレクトリに `stat`、`cgroup` のファイルと、`exe`、`root` のシンボリックリンク）。数字でない名前を飛ばす、`exe` が無いと `gone`、`root` のリンク先が別のディレクトリなら値が `own_root` と違い、同じディレクトリなら同じ
- 権限の失敗は、今の `test_aux_stat_os_error` と同じやり方（`mock.patch`）で `PermissionError` を起こして確かめる（クラウド実行環境は root で動くため、ファイルの権限では起こせない）
- `proc_dir` が無いとき `ScanError`
- `System().process_scan()` が例外を出さずに `ProcessScan` を返す（中身は確かめない。実機の値をテストの期待値にしない）
- 木の前後でファイルが増えていないこと（書き込まない）

`tests/test_check.py`、`tests/test_table.py`:

- sshd にあたるプロセス（サービス）と htop にあたるプロセス（セッション）を渡し、JSON の版の `running`・`systemd_service` と、`checks.running_processes` の形（キーと順）、表の印を確かめる。`sudo` を親に持つ `self_pid` を渡し、`sudo` の版の `running` が真で、Tojimari 自身の実行ファイルの版には印が付かないこと
- `unreadable` が 1 以上のとき `running_partial` の注意と数、0 のとき注意が出ない
- `ScanError` のとき: `unavailable`、`unreadable` が `null`、各版の印が `null`、`running_unavailable` の注意、`rpm_files` が呼ばれない、ほかの確認の結果はそのまま、表に印が無い
- `rpm_files` が `CommandError`（`timeout`、`exit_status`、`not_found`）、形の合わない出力のとき: 同じく `unavailable`
- 注意と表に、渡した架空のパスや pid が出ないこと
- 表は JSON と同じ中身（印の有無）になること。`running` の無い古い形の JSON でも表が出ること

既存のテスト:

- `FakeSystem` の既定（プロセス 0 個）では、どの版も `running`・`systemd_service` が `false`、`running_processes` が `ok`・0、足される注意は無く、表は今と同じになる。既存のテストで変えてよいのは、版の要素に 2 つの項目が足されたこと、`checks` に `running_processes` が足されたこと、`running_is_snapshot` の文が延びたことに合わせる直しだけ。それ以外の期待値を変える必要が出たら、実装を止めてテックリードに戻す
- `python3 -m unittest` がリポジトリの最上位ですべて通ること

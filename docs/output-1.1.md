# 1.1 出力仕様: コマンド、JSON、人が読む表

- 作成日: 2026-11-21（issue #5 で PM が決めた）
- 状態: 1.1 の出力の決定事項
- 更新: 2026-11-22 表と標準エラー出力で、外部コマンド由来の制御文字を見える形に置き換える決まりを足した（issue #16、1.3・3.2）。要件は [task-issue-16.md](task-issue-16.md)。2026-11-22 今動いているかの印（版の要素の `running`・`systemd_service`、`checks.running_processes`）の JSON、注意、表を足した（issue #14、2.3・2.4・2.8・3.5）。要件は [task-issue-14.md](task-issue-14.md)。2026-11-22 古さ（`checks.staleness`）の JSON、注意、表を足した（issue #13、2.4・2.7・3.4）。要件は [task-issue-13.md](task-issue-13.md)。2026-11-21 後から入れたもの（`checks.user_installed`）の JSON と表を足した（issue #12、2.6 と 3.3）。要件は [task-issue-12.md](task-issue-12.md)
- 位置付け: [spec-1.1.md](spec-1.1.md) の 6「1.1 で未決のこと」のうち、JSON の項目名と構造、人が読む表の見た目、コマンド名と起動のしかたを決める。1.1 の直後に足す FastAPI の画面も、この JSON を読んで表示する

## 1. コマンドと起動のしかた

### 1.1 決めたこと

- コマンド名は `tojimari`、1.1 の確認はサブコマンド `check` とする
- 起動はリポジトリを取得したディレクトリ（リポジトリの最上位）で次のように行う

```
sudo python3 -B -m tojimari check          # 人が読む表
sudo python3 -B -m tojimari check --json   # JSON
```

- オプションは `--json` だけ。付けなければ人が読む表、付ければ JSON を標準出力に出す。両方を一度に出すことはしない
- Tojimari 自身は書き込みを一切しない（ファイルも作らない）。外部への送信もしない

### 1.2 理由

- `tojimari`: プロジェクト名そのままで覚えやすい。パッケージ名の重複確認（PyPI など）は配布方法と合わせて未決のまま残すが、`python3 -m` で起動する今の形ならパッケージを登録しないので、重複の影響を受けない
- `check`: requirements.md の未決事項にある `tojimari apply` / `tojimari check` の案に合わせ、第1段階（現状チェック）を `check` とした。第2段階・第3段階のサブコマンドを後から足せる。1.2・1.3 の確認も `check` に足していく想定（オプションで絞るかは、そのときに決める）
- `python3 -m`: 配布方法が未決のため、インストールせずにリポジトリからそのまま動く形にした。シェルスクリプトの起動用ファイルも作らない（今は無くても困らず、置くものを増やさないため）
- `-B`: `sudo` で動かすと、`__pycache__` が root の持ち物として利用者のリポジトリの中に作られてしまう。それを避けるため
- `--json` だけ: 表と JSON の 2 つしか出さないので、`--format` のような汎用の指定より短く済む

### 1.3 終了コード

| コード | 意味 |
|---|---|
| 0 | 出力できた（入っていないパッケージがある、入れた元のリポジトリが取れなかった、などを含む） |
| 1 | 出力そのものができなかった（例: `rpm` コマンドが無い、rpm の問い合わせが失敗した） |
| 2 | 引数の誤り |

- 1 のときは、理由を標準エラー出力に出す。JSON を求められていても、中途半端な JSON は出さない
- 理由のうち外部コマンドの出力から来た行は、制御文字を見える形に置き換え、1 行の長さに上限を付ける（3.2）
- 入っていないパッケージがあることは、異常ではないので 0 とする

## 2. JSON の構造

### 2.1 全体

```json
{
  "format": "tojimari-check",
  "schema_version": 1,
  "generated_at": "2026-11-21T09:39:00Z",
  "run": {
    "is_root": true
  },
  "system": {
    "running_kernel": "6.12.0-55.el10.aarch64"
  },
  "checks": {
    "focus_packages": { }
  },
  "notices": [ ]
}
```

| 項目 | 型 | 内容 |
|---|---|---|
| `format` | 文字列 | 常に `"tojimari-check"`。この JSON が Tojimari の check の出力であることを示す |
| `schema_version` | 整数 | 構造の版。今回は `1`。項目を足すだけなら上げない。既存の項目の意味や型を変えるときだけ上げる |
| `generated_at` | 文字列 | 出力を作った時刻（UTC、ISO 8601、秒まで、末尾 `Z`） |
| `run.is_root` | 真偽 | root（実効 UID 0）で実行したか |
| `system.running_kernel` | 文字列 または null | 今動いているカーネルのリリース（`uname -r` と同じ値。Python の `os.uname().release`）。取れなければ null |
| `checks` | オブジェクト | 確認ごとの結果。キーは確認の名前（2.2 と 2.5） |
| `notices` | 配列 | 表示の注意（2.4） |

- ホスト名、ユーザー名、IP アドレスなど、確認に要らない実機の情報は入れない
- キーの並びは上の順に揃える（人が JSON を目で見たときに読みやすくするため。意味は持たせない）

### 2.2 `checks.focus_packages`（重点リスト）

```json
{
  "packages": [
    {
      "name": "kernel",
      "reason": "土台。動いている版と入っている版の両方を表示する",
      "status": "installed",
      "installed": [
        {
          "name": "kernel",
          "epoch": null,
          "version": "6.12.0",
          "release": "55.el10",
          "arch": "aarch64",
          "evr": "6.12.0-55.el10",
          "from_repo": "baseos",
          "is_running_kernel": true
        }
      ]
    },
    {
      "name": "polkit",
      "reason": "権限昇格につながる",
      "status": "not_installed",
      "installed": []
    }
  ],
  "from_repo_available": true
}
```

`packages` の各要素（重点リストの 1 項目）:

| 項目 | 型 | 内容 |
|---|---|---|
| `name` | 文字列 | 重点リストのパッケージ名 |
| `reason` | 文字列 | 選んだ理由（spec-1.1.md の 2.2 の表の文言） |
| `status` | 文字列 | `installed`（rpm の記録にある）、`not_installed`（rpm の記録にない） |
| `installed` | 配列 | 入っている版（2.3）。`not_installed` なら空配列 |

- `packages` の並びは spec-1.1.md の 2.2 の表の順（kernel、openssh-server、openssh、openssl-libs、glibc、sudo、systemd、polkit）に固定する
- `from_repo_available`: 入れた元のリポジトリを dnf から取得できたか。false のとき、各版の `from_repo` はすべて null になり、`notices` にその旨が入る
- 「入っていない」は、rpm の記録（rpm データベース）にその名前のパッケージが無いことだけを意味する。パッケージ管理の外で入れたものは見ていない

### 2.3 入っている版（パッケージの 1 版）

「後から入れたもの」の一覧（2.6）も、同じ形の要素を使う。

| 項目 | 型 | 内容 |
|---|---|---|
| `name` | 文字列 | パッケージ名 |
| `epoch` | 文字列 または null | epoch。無ければ null |
| `version` | 文字列 | version |
| `release` | 文字列 | release |
| `arch` | 文字列 | アーキテクチャ |
| `evr` | 文字列 | 表示用。`version-release`。epoch があれば `epoch:version-release` |
| `from_repo` | 文字列 または null | dnf が記録している、入れた元のリポジトリ。取れなければ null |
| `is_running_kernel` | 真偽 | **kernel の版にだけ付ける**。`version-release.arch` が `system.running_kernel` と一致すれば true |
| `running` | 真偽 または null | 今動いているプロセスの実行ファイルのパスを、この版が持っていれば true（2.8）。`checks.running_processes.status` が `unavailable` なら null |
| `systemd_service` | 真偽 または null | そのプロセスのうち、システムのサービスとして動いているものがあれば true（2.8）。true なら `running` も true。`checks.running_processes.status` が `unavailable` なら null |

- 同じ名前の版が複数あれば（kernel の複数世代、x86_64 と i686 の両方が入った glibc など）、すべて並べる。並びは rpm の比較ではなく、`version`、`release`、`arch` の文字列の昇順でよい（比較の正しさを 1.1 では求めないため。古さの判定は後の issue で扱う）
- `is_running_kernel` が true の版が 1 つもないとき（動いているカーネルが rpm の記録に無いとき）は、`notices` にその旨が入る

### 2.4 `notices`（表示の注意）

```json
[
  {"id": "not_a_guarantee", "message": "..."},
  {"id": "scope", "message": "..."}
]
```

| `id` | 出す条件 | 内容（文言は実装で整えてよいが、意味は変えない） |
|---|---|---|
| `not_a_guarantee` | 常に | この表示は確認の補助であり、安全であることを示すものではない |
| `scope` | 常に | 表示対象は dnf（rpm）で入れたものと重点リストだけ。パッケージ管理の外で個別にビルド・配置したもの、pip などの言語ごとのパッケージ管理で入れたもの、Docker コンテナの中身は表示しない。表示されないことを「入っていない」と扱わない |
| `running_is_snapshot` | 常に | 「今動いている」はその瞬間の様子。印がないことを「使っていない」と扱わない。Docker コンテナの中で動いているものには印を付けない。印は実行ファイルのパスで付けるので、更新した後に再起動していないプロセスは新しい版の印として出る（issue #14 で後ろの 2 文を足した） |
| `not_root` | `run.is_root` が false のとき | root なしで実行したため、見えた範囲だけを表示している。`sudo` での実行を勧める |
| `from_repo_unavailable` | `from_repo_available` が false のとき | 入れた元のリポジトリを取得できなかった（理由の要約を含める） |
| `running_kernel_not_found` | 動いているカーネルが、入っている kernel の版のどれとも一致しないとき、または取れなかったとき | 動いているカーネルが rpm の記録の中に見つからなかった |
| `history_fallback` | `checks.user_installed.method` が `from_repo_fallback` のとき（2.6） | dnf 履歴が取れず、入れた元のリポジトリが `anaconda` かによる代わりの判定を使ったため精度が落ちている（インストール後に更新した OS 標準が、後から入れたものに混ざりうる）。履歴が取れなかった理由の要約を含める |
| `user_installed_unavailable` | `checks.user_installed.status` が `unavailable` のとき（2.6） | 後から入れたものの一覧を取得できなかったため、確認できなかった。「後から入れたものは無い」という意味ではない。理由の要約を含める |
| `security_updates_cache` | `checks.staleness.security_updates.status` が `ok` のとき（2.7） | セキュリティ更新の数は、dnf が手元に持っているリポジトリ情報（最後に取得した時点のもの）にもとづき、最新とは限らない。Tojimari は取り直さない。最新にするには、先に `sudo dnf makecache` を実行する |
| `security_updates_unavailable` | `checks.staleness.security_updates.status` が `unavailable` のとき（2.7） | リポジトリ情報を確認できなかったため、セキュリティ更新の有無は分からない。「更新なし」という意味ではない。理由の要約を含める |
| `reboot_unknown` | `checks.staleness.reboot.status` が `unknown` のとき（2.7） | 再起動待ちかどうかを確認できなかった。「再起動待ちではない」という意味ではない。理由の要約を含める |
| `last_update_unavailable` | `checks.staleness.last_update.status` が `unavailable` のとき（2.7） | dnf 履歴から最後に更新した日を確認できなかった。理由の要約を含める |
| `running_unavailable` | `checks.running_processes.status` が `unavailable` のとき（2.8） | 動いているプロセスを確認できなかったため、今動いているかの印を付けていない。「どれも動いていない」という意味ではない。理由の要約を含める |
| `running_partial` | `checks.running_processes.unreadable` が 1 以上のとき（2.8） | N 個のプロセスは権限が無くて実行ファイルかルートディレクトリを読めなかったため、印のもとにしていない。印の無い版の中にも、動いているものがありうる |

- `scope`、`running_is_snapshot`、`not_root`、`history_fallback` は spec-1.1.md の「3. 表示の注意」にあたる
- `running_is_snapshot` は、#5 で今動いているかの印をまだ出さなかったときから出している（spec-1.1.md の 3 が「出力に必ず含める」としているため）
- 並びは表の順

### 2.5 後で足す項目の決まり

- 後で足す確認は、`checks` の下に新しいキーとして足す。予定しているキーは次のとおり
  - `user_installed`: 後から入れたもの（spec-1.1.md の 2.1）。2.6 に決めた（issue #12）
  - `staleness`: 古さ（spec-1.1.md の 2.3）。2.7 に決めた（issue #13）
- 今動いているかの印（spec-1.1.md の 2.4）は、2.3 の版の要素に項目を足す形にする（`running`、`systemd_service`）。見回しの結果は `checks.running_processes` に出す。2.3 と 2.8 に決めた（issue #14）。予定では「どちらも真偽」としていたが、見回しができなかったときに「動いていない」と区別するため null も取りうることにした
- 読む側（表の出力、1.1 の直後の画面）は次を守る
  - `checks` にキーが無いことを「確認して何も無かった」と扱わず、「この版では確認していない」と扱う
  - 知らない項目は無視する
  - `format` が `"tojimari-check"` でないとき、または `schema_version` が知らない値のときは、表示せずにその旨を出す
- 項目を足すだけなら `schema_version` は上げない。意味や型を変えるときは上げ、この文書に変えた理由を残す

### 2.6 `checks.user_installed`（後から入れたもの）

issue #12 で決めた。判定のしかたと、取れないときの扱いの要件は [task-issue-12.md](task-issue-12.md) の 3 にある。

```json
{
  "status": "ok",
  "method": "history",
  "packages": [
    {
      "name": "git",
      "epoch": null,
      "version": "2.47.1",
      "release": "1.el10",
      "arch": "aarch64",
      "evr": "2.47.1-1.el10",
      "from_repo": "appstream"
    }
  ]
}
```

| 項目 | 型 | 内容 |
|---|---|---|
| `status` | 文字列 | `ok`（判定できた。0 件のときも `ok`）、`unavailable`（後から入れたものの一覧を取得できず、判定できなかった） |
| `method` | 文字列 または null | 使った判定。`history`（dnf 履歴の 1 番の名前を除いた）、`from_repo_fallback`（履歴が取れず、`from_repo` が `anaconda` のものを除いた）。`status` が `unavailable` なら null |
| `packages` | 配列 | 後から入れたものの版。要素は 2.3 の形（`is_running_kernel` は付けない）。`status` が `unavailable` なら空配列 |

- `packages` の並びは、名前、version、release、arch の文字列の昇順。同じ名前の版が複数あれば、すべて並べる
- 版の値は rpm の記録から取る。`from_repo` は dnf の記録から取り、取れなければ null
- 重点リストに入っている名前でも、後から入れたものに当たれば、ここにも出す（重点リストは別枠のため）
- `status` が `unavailable` のとき、`packages` が空であることを「後から入れたものは無い」と扱わない。読む側は `status` を先に見る
- 今動いているかの印は、2.3 の `running`・`systemd_service` を各版に付ける（issue #14。`is_running_kernel` は付けない）

### 2.7 `checks.staleness`（古さ）

issue #13 で決めた。取り方と、取れないときの扱いの要件は [task-issue-13.md](task-issue-13.md) の 3 にある。

```json
{
  "security_updates": {
    "status": "ok",
    "total": 2,
    "by_severity": {
      "critical": 0,
      "important": 1,
      "moderate": 1,
      "low": 0,
      "unspecified": 0
    },
    "packages": [
      {"name": "openssl-libs", "severity": "important"},
      {"name": "vim-enhanced", "severity": "moderate"}
    ]
  },
  "reboot": {
    "status": "pending",
    "running_kernel": "6.12.0-50.el10.aarch64",
    "latest_kernel": "6.12.0-55.el10.aarch64"
  },
  "last_update": {
    "status": "ok",
    "at": "2026-11-20T10:00:00Z",
    "days_ago": 2
  }
}
```

`security_updates`（セキュリティ更新）:

| 項目 | 型 | 内容 |
|---|---|---|
| `status` | 文字列 | `ok`（dnf が手元に持っているリポジトリ情報で確認できた。0 件のときも `ok`）、`unavailable`（確認できなかった） |
| `total` | 整数 または null | セキュリティ更新が出ている、入っているパッケージの名前の数（勧告の数ではない）。`unavailable` なら null |
| `by_severity` | オブジェクト または null | 重要度ごとの名前の数。キーは `critical`、`important`、`moderate`、`low`、`unspecified`（重要度が書かれていないもの）で、いつも 5 つそろえる。1 つの名前はいちばん重い重要度にだけ数えるので、合計は `total` と一致する。`unavailable` なら null |
| `packages` | 配列 | 名前（`name`）と重要度（`severity`。`by_severity` のキーと同じ書き方）。並びは重要度の重い順、同じ重要度の中では名前の昇順。`unavailable` なら空配列 |

`reboot`（再起動待ち）:

| 項目 | 型 | 内容 |
|---|---|---|
| `status` | 文字列 | `pending`（動いているカーネルより新しい `kernel` の版が入っている）、`not_pending`（動いている版が、入っている同じアーキテクチャの `kernel` の中でいちばん新しい）、`unknown`（確認できなかった） |
| `running_kernel` | 文字列 または null | 動いているカーネル（`system.running_kernel` と同じ値） |
| `latest_kernel` | 文字列 または null | 入っている同じアーキテクチャの `kernel` のうち、いちばん新しい版（`version-release.arch`。比べ方は rpm の決まり）。`unknown` のときは、取れていれば入れ、取れなければ null |

`last_update`（最後に更新した日）:

| 項目 | 型 | 内容 |
|---|---|---|
| `status` | 文字列 | `ok`（見つかった）、`none`（dnf 履歴は読めたが、パッケージの版を上げた処理の記録が無い）、`unavailable`（dnf 履歴を読めなかった） |
| `at` | 文字列 または null | パッケージの版を上げた処理のうち、いちばん新しいものが終わった時刻（UTC、ISO 8601、秒まで、末尾 `Z`）。`ok` 以外は null |
| `days_ago` | 整数 または null | `generated_at` から `at` まで何日たったか（切り捨て）。`ok` 以外は null |

- 3 つは別々に取る。どれかが取れなくても、ほかは出す
- `security_updates.status` が `unavailable` のとき、読む側は「更新なし」と扱わない。`reboot.status` が `unknown` のとき、「再起動待ちではない」と扱わない
- 「パッケージの版を上げた処理」は、dnf 履歴で、版を上げる項目を 1 件以上含み、最後まで終わった処理（`dnf install` で依存の版が上がったものを含む）

### 2.8 今動いているかの印と `checks.running_processes`

issue #14 で決めた。取り方と、取れないときの扱いの要件は [task-issue-14.md](task-issue-14.md) の 3 にある。

印は、重点リスト（2.2）と後から入れたもの（2.6）の各版の要素に `running` と `systemd_service` として付ける（2.3）。見回し全体の結果は次のとおり出す。

```json
{
  "status": "ok",
  "unreadable": 0
}
```

| 項目 | 型 | 内容 |
|---|---|---|
| `status` | 文字列 | `ok`（動いているプロセスを見回し、rpm でパッケージに結びつけられた）、`unavailable`（見回しか rpm への問い合わせができなかった） |
| `unreadable` | 整数 または null | 権限が無くて実行ファイルかルートディレクトリを読めなかったプロセスの数。`unavailable` なら null |

- `running` の意味: その版が持つ実行ファイルのパスで、今動いているプロセスがある。更新で入れ替わった古い実行ファイルが動いているときも、今そのパスを持つ版に印が付く（更新前の中身かどうかは見分けない）
- `systemd_service` の意味: そのプロセスのうち、システムのサービス（cgroup のパスのどこかの部分が `.service` で終わり、`/user.slice` の下ではないもの。`Delegate=yes` のサービスの子の cgroup も含む）として動いているものがある
- 結びつけないもの: 実行ファイルの無いもの（カーネルのスレッドなど）、見回しているあいだに終わったもの、Tojimari 自身とその子プロセス、Tojimari と違うルートディレクトリで動いているもの（Docker コンテナの中など）。マウントの名前空間だけが違うもの（`PrivateTmp=` などのある systemd のサービス）は結びつける
- Tojimari の親（`sudo`）は除かない。`sudo` で実行すると、重点リストの `sudo` の版には `running` が true で出る。その瞬間に実際に動いているためで、誤りではない
- kernel の版の `running` は、プロセスの実行ファイルではないので、いつも false（`ok` のとき）。動いているカーネルは `is_running_kernel` で見る
- 実行ファイルのパス、pid、サービスの名前は出さない（パスに利用者の名前などが入りうるため。印に要るものだけを出す）
- `false` は「見えた範囲で、その瞬間に動いていなかった」という意味で、「使っていない」ではない。読む側は `status` と `unreadable` を先に見る

## 3. 人が読む表

### 3.1 見た目

次のような形とする（例の値は架空のもの）。

```
Tojimari check  2026-11-21 09:39 UTC
この表示は確認の補助であり、安全であることを示すものではありません。

[重点リスト]
パッケージ       状態          バージョン          アーキ   入れた元
kernel           入っている    6.12.0-50.el10      aarch64  baseos
                               6.12.0-55.el10      aarch64  baseos    <- 動いている
openssh-server   入っている    9.9p1-7.el10        aarch64  baseos
openssh          入っている    9.9p1-7.el10        aarch64  baseos
openssl-libs     入っている    1:3.5.1-3.el10      aarch64  baseos
glibc            入っている    2.39-43.el10        aarch64  baseos
sudo             入っている    1.9.15-8.p5.el10    aarch64  baseos
systemd          入っている    257-9.el10          aarch64  baseos
polkit           入っていない  -
動いているカーネル: 6.12.0-55.el10.aarch64

[注意]
- 表示対象は dnf（rpm）で入れたものと重点リストだけです。...
- 「今動いている」はその瞬間の様子です。...
```

### 3.2 決まり

- 上から、見出し（時刻は UTC）、`not_a_guarantee` の一文、確認ごとの表、`[注意]` の順に出す。`not_a_guarantee` は先頭に出すので `[注意]` には重ねて出さない
- 状態の表記: `installed` は「入っている」、`not_installed` は「入っていない」
- 版が複数あるときは、2 行目からパッケージ名と状態を空けて並べる
- kernel の動いている版の行には `<- 動いている` を付け、表の下に「動いているカーネル: ...」を出す
- 取れなかった値は `-` で表す（入れた元が取れないときも `-`）。空欄にしない
- 列は日本語の文字幅（全角は 2 桁）を考えて揃える（標準ライブラリの `unicodedata.east_asian_width` で足りる）
- 色や罫線の装飾は使わない（端末やリダイレクト先を選ばないため）
- 表に出す中身は JSON と同じものに限る。表だけに出る情報を作らない（画面と標準出力で内容がずれないようにするため）
- 表に出す値のうち、制御文字（C0 の U+0000〜U+001F、DEL の U+007F、C1 の U+0080〜U+009F。改行、タブ、復帰を含む）は、`\x` と 16 進の小文字 2 桁の形（例: ESC は `\x1b`、改行は `\x0a`）に置き換えて出す。端末の表示が変わらないように、見える形にするためのもの。表の改行は行の区切りだけになる
- 置き換えるのは C0、DEL、C1 だけ。それ以外の文字（Unicode の書式の文字の U+202E、行の区切りの U+2028・U+2029 など）は置き換えない
- 逆斜線 `\` そのものは置き換えない。値にもとから `\x1b` という文字の並びがあると、置き換えた形と見分けがつかない。読み分けが要るときは JSON を見る（JSON の値は書き換えない）
- 列の幅は、置き換えた後の文字列で数える
- 終了コード 1 のときに標準エラー出力に出す理由（1.3）のうち、rpm の標準エラー出力の末尾（最大 5 行）の各行にも、同じ置き換えをかける。行の区切りの改行だけはそのまま出す
- その各行は、置き換えた後の文字数で 200 文字までとする。超えた分は出さず、行の終わりに ` ...（残り N 文字を省略）` を付ける（N は省いた文字数）。置き換えた形の途中では切らない。Tojimari の文（`rpm の問い合わせが終了コード 1 で失敗しました` など）は切らない

### 3.3 後から入れたもの（issue #12 で足した）

重点リストの表の後、`[注意]` の前に出す（例の値は架空のもの）。

```
[後から入れたもの]  dnf 履歴の 1 番の名前を除いた 3 件
パッケージ       バージョン          アーキ   入れた元
gh               2.65.0-1            aarch64  gh-cli
git              2.47.1-1.el10       aarch64  appstream
htop             3.3.0-5.el10        aarch64  epel
```

- 見出しの後に、使った判定と件数を出す。件数はパッケージ名の数とする
  - `history` のとき: 「dnf 履歴の 1 番の名前を除いた N 件」
  - `from_repo_fallback` のとき: 「入れた元が anaconda のものを除いた N 件（代わりの判定）」。理由と精度の注意は `[注意]` の `history_fallback` に出す
- 0 件のときは、列の見出しを出さず「該当なし」と出す
- `status` が `unavailable` のときは、列の見出しを出さず「確認できませんでした」と出す。理由は `[注意]` の `user_installed_unavailable` に出す
- 版が複数あるときは、2 行目からパッケージ名を空けて並べる（重点リストと同じ）
- 取れなかった値は `-`、列の揃え方と装飾の決まりは 3.2 と同じ

### 3.4 古さ（issue #13 で足した）

後から入れたものの表の後、`[注意]` の前に出す（例の値は架空のもの）。

```
[古さ]
セキュリティ更新    2 件（Critical 0、Important 1、Moderate 1、Low 0、重要度なし 0）
  openssl-libs      Important
  vim-enhanced      Moderate
再起動待ち          再起動待ち（動いている 6.12.0-50.el10.aarch64、入っている最新 6.12.0-55.el10.aarch64）
最後に更新した日    2026-11-20 10:00 UTC（2 日前）
```

- 行の見出しは「セキュリティ更新」「再起動待ち」「最後に更新した日」の 3 つで、この順に出す
- セキュリティ更新
  - `ok` のとき: 件数と重要度ごとの内訳を 1 行に出し、続けて名前と重要度を 1 行ずつ、字下げして出す。重要度の表記は `Critical`、`Important`、`Moderate`、`Low`、`重要度なし`
  - 0 件のときは「0 件」とだけ出す（名前の行は出さない）
  - `unavailable` のときは「確認できませんでした」と出す（「0 件」「更新なし」とは出さない）。理由は `[注意]` の `security_updates_unavailable` に出す
  - 数が最後にリポジトリ情報を取得した時点のものであることは、`[注意]` の `security_updates_cache` に出す
- 再起動待ち
  - `pending` は「再起動待ち」、`not_pending` は「再起動待ちではない」、`unknown` は「確認できませんでした」と出す
  - 括弧の中に、動いている版と入っている最新の版を出す。取れなかった値は `-`
  - `unknown` の理由は `[注意]` の `reboot_unknown` に出す
- 最後に更新した日
  - `ok` は「YYYY-MM-DD HH:MM UTC（N 日前）」と出す
  - `none` は「更新の記録がありません」、`unavailable` は「確認できませんでした」と出す。`unavailable` の理由は `[注意]` の `last_update_unavailable` に出す
- 列の揃え方と装飾の決まりは 3.2 と同じ

### 3.5 今動いているかの印（issue #14 で足した）

重点リストと後から入れたものの表の、各版の行の終わりに印を付ける（例の値は架空のもの）。

```
[重点リスト]
パッケージ       状態          バージョン          アーキ   入れた元
kernel           入っている    6.12.0-55.el10      aarch64  baseos    <- 動いている
openssh-server   入っている    9.9p1-7.el10        aarch64  baseos    <- 今動いている（systemd のサービス）
openssh          入っている    9.9p1-7.el10        aarch64  baseos
...

[後から入れたもの]  dnf 履歴の 1 番の名前を除いた 3 件
パッケージ       バージョン          アーキ   入れた元
gh               2.65.0-1            aarch64  gh-cli
git              2.47.1-1.el10       aarch64  appstream
htop             3.3.0-5.el10        aarch64  epel      <- 今動いている
```

- `systemd_service` が true の版は「<- 今動いている（systemd のサービス）」、`running` だけが true の版は「<- 今動いている」を付ける。どちらも false の版には何も付けない（印の無いことの意味は `[注意]` の `running_is_snapshot` に出す）
- kernel の動いている版の「<- 動いている」（3.2）はこれまでどおり。kernel の版にはプロセスの印は付かないので、2 つが同じ行に並ぶことは無い
- `checks.running_processes.status` が `unavailable` のときは、どの版にも印を付けず、理由を `[注意]` の `running_unavailable` に出す
- 読めなかったプロセスがあるときは、`[注意]` の `running_partial` に数を出す
- 列の揃え方と装飾の決まりは 3.2 と同じ

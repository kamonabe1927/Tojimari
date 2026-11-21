# 1.1 出力仕様: コマンド、JSON、人が読む表

- 作成日: 2026-11-21（issue #5 で PM が決めた）
- 状態: 1.1 の出力の決定事項。後から入れたもの、古さ、今動いているかの印は、この文書の「後で足す項目」の決まりに沿って足す
- 更新: 2026-11-21 後から入れたもの（`checks.user_installed`）の JSON と表を足した（issue #12、2.6 と 3.3）。要件は [task-issue-12.md](task-issue-12.md)
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

後で足す「後から入れたもの」の一覧も、同じ形の要素を使う。

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
| `running_is_snapshot` | 常に | 「今動いている」はその瞬間の様子。印がないことを「使っていない」と扱わない |
| `not_root` | `run.is_root` が false のとき | root なしで実行したため、見えた範囲だけを表示している。`sudo` での実行を勧める |
| `from_repo_unavailable` | `from_repo_available` が false のとき | 入れた元のリポジトリを取得できなかった（理由の要約を含める） |
| `running_kernel_not_found` | 動いているカーネルが、入っている kernel の版のどれとも一致しないとき、または取れなかったとき | 動いているカーネルが rpm の記録の中に見つからなかった |
| `history_fallback` | `checks.user_installed.method` が `from_repo_fallback` のとき（2.6） | dnf 履歴が取れず、入れた元のリポジトリが `anaconda` かによる代わりの判定を使ったため精度が落ちている（インストール後に更新した OS 標準が、後から入れたものに混ざりうる）。履歴が取れなかった理由の要約を含める |
| `user_installed_unavailable` | `checks.user_installed.status` が `unavailable` のとき（2.6） | 後から入れたものの一覧を取得できなかったため、確認できなかった。「後から入れたものは無い」という意味ではない。理由の要約を含める |

- `scope`、`running_is_snapshot`、`not_root`、`history_fallback` は spec-1.1.md の「3. 表示の注意」にあたる
- `running_is_snapshot` は、今動いているかの印をまだ出さない今回も出す（spec-1.1.md の 3 が「出力に必ず含める」としているため）
- 並びは表の順

### 2.5 後で足す項目の決まり

- 後で足す確認は、`checks` の下に新しいキーとして足す。予定しているキーは次のとおり
  - `user_installed`: 後から入れたもの（spec-1.1.md の 2.1）。2.6 に決めた（issue #12）
  - `staleness`: 古さ（spec-1.1.md の 2.3）
- 今動いているかの印（spec-1.1.md の 2.4）は、2.3 の版の要素に項目を足す形にする（予定する名前: `running`、`systemd_service`。どちらも真偽。中身はその issue で決める）
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
- 今動いているかの印（1.1-C）は、2.5 のとおり後で版の要素に足す

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

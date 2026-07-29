# install_deb タスク

複数のUbuntuサーバへ `.deb` ファイルを転送・インストールするタスクです。
`files/downloads/` 以下にUbuntuバージョン別に配置したdebファイルを、各サーバのバージョンに合わせて自動選択してインストールします。

## 実行コマンド

```bash
uv run pyinfra inventories/inventory.py deploys/install_deb.py --data deb=<パッケージ名> [--dry-run]
```

## debファイルの配置

`files/downloads/` 以下にUbuntuバージョン別のディレクトリを作成してdebファイルを配置します。
全バージョン共通のファイルは `common/` に置きます。

```
files/downloads/
├── 20.04/
│   └── veracrypt-console-1.26.24-Ubuntu-20.04-amd64.deb
├── 22.04/
│   └── veracrypt-console-1.26.24-Ubuntu-22.04-amd64.deb
├── 24.04/
│   └── veracrypt-console-1.26.24-Ubuntu-24.04-amd64.deb
└── common/
    └── SentinelAgent_linux_x86_64_v25_2_2_14.deb
```

実行時はサーバのUbuntuバージョンを検出し、バージョン別フォルダを優先して使用します。バージョン別フォルダにファイルがない場合は `common/` にフォールバックします。

## オプション (--data)

| オプション | 必須 | デフォルト | 内容 |
| :--- | :---: | :--- | :--- |
| `deb` | Yes | — | インストールするパッケージ名（ファイル名の部分一致、大文字小文字不問） |
| `remote_tmp` | No | `/tmp` | リモートへの転送先ディレクトリ |

`deb` パラメータはファイル名に含まれる文字列で指定します。

| 指定例 | マッチするファイル |
| :--- | :--- |
| `deb=veracrypt-console` | `veracrypt-console-1.26.24-Ubuntu-22.04-amd64.deb` |
| `deb=SentinelAgent` | `SentinelAgent_linux_x86_64_v25_2_2_14.deb` |

## 事前確認（--dry-run）

`--dry-run` を付けると、SSHで接続した上でdebファイルの候補一覧を表示し、転送・インストールは行いません。

```bash
uv run pyinfra inventories/inventory.py deploys/install_deb.py --data deb=veracrypt-console --dry-run
```

出力例：

```
--> Preparing operation files...
    [ubuntu1] deb candidates for 'veracrypt-console':
    [ubuntu1]   20.04: veracrypt-console-1.26.24-Ubuntu-20.04-amd64.deb
    [ubuntu1]   22.04: veracrypt-console-1.26.24-Ubuntu-22.04-amd64.deb
    [ubuntu1]   24.04: veracrypt-console-1.26.24-Ubuntu-24.04-amd64.deb
    [ubuntu1]   common: (no match)
```

- **`(fallback)`**: バージョン別にファイルが存在する場合、commonはフォールバックとして表示されます
- **`(no match)`**: そのバージョンディレクトリに対象ファイルがないことを示します。バージョン別・commonの両方が `(no match)` の場合、そのUbuntuバージョンのサーバは実行時にエラーになります

## 実行ステージ

| ステージ | 内容 |
| :--- | :--- |
| `0.cleanup_askpass` | `/tmp` に残存する過去のsudo askpassファイルを確認・削除する |
| `1.detect` | `lsb_release` でUbuntuバージョンを検出し、使用するdebファイルを決定する |
| `2.upload` | debファイルをリモートの `remote_tmp`（デフォルト `/tmp`）に転送する |
| `3.install` | `dpkg` でインストールする。既にインストール済みの場合はスキップ |

全ステージ並列実行（ホスト間の依存なし）。

## 冪等性

- **2.upload**: ファイルチェックサムを比較し、同一ファイルが既に存在する場合は `No changes`
- **3.install**: `dpkg-query` で同バージョンが既にインストール済みの場合はスキップし "already installed." をログ出力

再実行しても安全です。

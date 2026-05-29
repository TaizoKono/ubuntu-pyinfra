# install_apt タスク

aptリポジトリからパッケージ名を指定してインストールするタスクです。
複数パッケージをカンマ区切りで一括指定できます。

## 実行コマンド

```bash
uv run pyinfra inventories/inventory.py deploys/install_apt.py --data pkg=<パッケージ名> [--dry-run]
```

## オプション (--data)

| オプション | 必須 | デフォルト | 内容 |
| :--- | :---: | :--- | :--- |
| `pkg` | Yes | — | インストールするパッケージ名。カンマ区切りで複数指定可 |

`apt-get update` はインストール前に常に実行されます。

## 使用例

```bash
# 1パッケージ
uv run pyinfra inventories/inventory.py deploys/install_apt.py --data pkg=curl

# 複数パッケージ
uv run pyinfra inventories/inventory.py deploys/install_apt.py --data pkg="curl,wget,jq"

# 事前確認（インストールは行わずパッケージ名のみ表示）
uv run pyinfra inventories/inventory.py deploys/install_apt.py --data pkg=curl --dry-run
```

## 冪等性

`dpkg-query` で各パッケージのインストール状態を確認し、既にインストール済みのパッケージはスキップします。

- 全パッケージがインストール済みの場合: `apt-get update` も含めすべてスキップ
- 一部がインストール済みの場合: 未インストール分のみ `apt-get install` を実行

再実行しても安全です。

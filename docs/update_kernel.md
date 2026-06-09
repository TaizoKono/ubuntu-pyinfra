# update_kernel タスク

複数のUbuntuサーバのカーネルを一括更新し、自動再起動・検証するタスクです。

## 実行コマンド

```bash
uv run pyinfra inventories/inventory.py deploys/update_kernel.py [--data kernel=<version>] [--dry-run]
```

## バージョン指定方式

カーネルバージョンは以下の優先度で指定します：

1. **CLIオプション** — 全ホスト共通バージョン
2. **ファイル** — ホスト別バージョン対応表（`files/kernel/targets.csv`）

どちらも未指定の場合はエラーになります。

### ファイルによる指定

`files/kernel/targets.csv` にホスト名とカーネルバージョンの対応を記載：

```csv
# hostname,kernel_version
ollo1,5.15.0-136-generic
ollo2,6.8.0-60-generic
ollo3,5.15.0-136-generic
```

テンプレートは [files/kernel/targets.csv.template](../files/kernel/targets.csv.template) を参考に作成してください。

## オプション (--data)

| オプション | 必須 | デフォルト | 説明 |
| :--- | :---: | :--- | :--- |
| `kernel` | No | targets.csv参照 | ターゲットカーネルバージョン（全ホスト共通） |

## 使用例

### 事前確認（–dry-runで更新内容を確認）

```bash
uv run pyinfra inventories/inventory.py deploys/update_kernel.py --data kernel=5.15.0-136-generic --dry-run
```

期待される出力例：

```
--> Preparing operation files...
    [ollo1] Current: 5.15.0-122-generic → Target: 5.15.0-136-generic (update needed)
    [ollo2] Current: 6.8.0-60-generic == Target: 6.8.0-60-generic → no update needed
```

### CLIでバージョン指定（全ホスト共通）

```bash
uv run pyinfra inventories/inventory.py deploys/update_kernel.py --data kernel=5.15.0-136-generic
```

### CSVファイルでホスト別指定

```bash
uv run pyinfra inventories/inventory.py deploys/update_kernel.py
```

## 処理フロー

| ステージ | 内容 |
| :--- | :--- |
| `0.pre_check` | 現在のカーネルバージョン・インストール済みカーネル一覧を取得。既に対象バージョンなら以降をスキップ |
| `1.install` | `apt-get install linux-image-<target> linux-headers-<target>` でカーネルをインストール |
| `2.reboot` | サーバを再起動し、新カーネルで起動させる |
| `3.post_check` | 起動中カーネルがターゲットと一致するか確認。エラーログをチェック |

## 冪等性

既に対象カーネルで起動中の場合、インストール・再起動をスキップします。再実行しても安全です。

## 注意事項

- **GPU サーバの Nvidia ドライバ**: 現在のバージョンではカーネル更新のみ対応。Nvidia ドライバの更新が必要な場合は手動で対応してください。将来的にタスク追加予定。
- **再起動**: 自動で再起動が行われます。本番環境では計画的な実行をお勧めします。
- **ディスク容量**: カーネルのインストールには約 1GB の空き容量が必要です。

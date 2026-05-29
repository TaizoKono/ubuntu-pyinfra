# Auto-Infra

Pyinfraを使用してUbuntuサーバ群を管理するツールです。

## タスク一覧

| タスク | 説明 | ドキュメント |
| :--- | :--- | :--- |
| `check_cve` | CVE脆弱性の検出・レポート・パッチ適用 | [docs/check_cve.md](docs/check_cve.md) |
| `install_deb` | debパッケージの転送・インストール | [docs/install_deb.md](docs/install_deb.md) |
| `install_apt` | aptリポジトリからパッケージをインストール | [docs/install_apt.md](docs/install_apt.md) |

## 基本的な使い方

```bash
uv run pyinfra inventories/inventory.py deploys/<タスク名>.py [--data オプション] [--dry-run]
```

## 前提条件

- **inventory.py**: `inventories/inventory.py.template` を参考に対象ホストとSudoパスワードを設定してください。
- **Ubuntu Pro**: CVEスキャンやパッチ適用には、対象サーバーがUbuntu Proに紐付いている必要があります。
- **S1 Token**: `check_cve` のSentinelOne APIモードを利用する場合、`files/check_cve/token` に有効なApiTokenを配置してください。

# Auto-Infra

Pyinfraを使用してUbuntuサーバ群を管理するツールです。

## タスク一覧

| タスク | 説明 | ドキュメント |
| :--- | :--- | :--- |
| `check_cve` | CVE脆弱性の検出・レポート・パッチ適用 | [docs/check_cve.md](docs/check_cve.md) |
| `install_deb` | debパッケージの転送・インストール | [docs/install_deb.md](docs/install_deb.md) |
| `install_apt` | aptリポジトリからパッケージをインストール | [docs/install_apt.md](docs/install_apt.md) |
| `update_kernel` | Ubuntuカーネルを更新して再起動 | [docs/update_kernel.md](docs/update_kernel.md) |

## セットアップ

1. **uvのインストール**: 本プロジェクトはパッケージ管理・実行に [uv](https://docs.astral.sh/uv/) を使用します。未導入の場合はインストールしてください。

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **リポジトリのclone**

   ```bash
   git clone <このリポジトリのURL>
   cd auto-infra
   ```

3. **依存関係のインストール**: `uv sync` を実行すると、`.python-version`(3.14)に沿ったPython環境と依存パッケージが自動的にセットアップされます。

   ```bash
   uv sync
   ```

4. **inventoryファイルの作成**: `inventories/inventory.py.template` をコピーして `inventories/inventory.py` を作成し、対象ホストを設定してください。このファイルは `.gitignore` で除外されているためコミットされません。

   ```bash
   cp inventories/inventory.py.template inventories/inventory.py
   ```

5. **(任意) S1 Tokenファイルの作成**: `check_cve` のSentinelOne APIモードを利用する場合のみ、`files/check_cve/token.template` をコピーして `files/check_cve/token` を作成し、有効なApiTokenを配置してください。こちらも `.gitignore` で除外されます。

   ```bash
   cp files/check_cve/token.template files/check_cve/token
   ```

## 基本的な使い方

```bash
uv run pyinfra inventories/inventory.py deploys/<タスク名>.py [--data オプション] [--dry-run]
```

## 前提条件

- **Ubuntu Pro**: CVEスキャンやパッチ適用には、対象サーバーがUbuntu Proに紐付いている必要があります。

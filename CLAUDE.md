# auto-infra リポジトリ概要

pyinfra を使って複数の Ubuntu サーバを一括操作するためのツール。SSH 経由でインベントリに定義した全ホストに対し、NTP確認・パッケージインストール・カーネル更新などのタスクを並列実行する。

## ブランチ構成

- **main**: 現在のカレントブランチ。CVE管理機能（`check_cve`）は別プロジェクトへ移行する方針となり、本プロジェクトからは削除済み。
- **s1**: SentinelOne (S1) の脆弱性管理機能と連携する `check_cve` タスクが残っている旧ブランチ。mainでの `check_cve` 削除に伴い役目を終えており、削除候補。差分は `git diff main s1` で確認可能。

## 技術スタック

- Python 3.14（`.python-version` で固定）、パッケージ管理・実行は `uv`（`uv sync` / `uv run`）。
- 依存: `pyinfra>=3.8.0`, `requests>=2.33.1`（`pyproject.toml`）。
- 実行コマンドの基本形: `uv run pyinfra inventories/inventory.py deploys/<タスク名>.py [--data key=value] [--dry]`

## ディレクトリ構成

```
deploys/<task>.py          # pyinfra deploy エントリポイント。local.include で tasks/<task>/main.py を読み込むだけの薄いラッパー
tasks/<task>/main.py       # 実際のタスクロジック（python.call / server.shell 等を定義）
docs/<task>.md             # タスクごとの利用者向けドキュメント（日本語）
inventories/inventory.py.template  # インベントリのテンプレート（実ファイルは.gitignore対象）
files/downloads/            # install_deb が参照する .deb 配置場所（Ubuntuバージョン別 + common）
output/<task>/              # 各タスクの実行結果CSV出力先（.gitignoreでコミット対象外）
README.md                   # セットアップ手順・タスク一覧
```

タスク追加時のパターンは一貫している: `deploys/foo.py` が `tasks/foo/main.py` を `local.include` するだけ、実装は `tasks/foo/main.py` 側。

## タスク一覧

| タスク | 概要 | sudo | 主な特徴 |
| :--- | :--- | :--- | :--- |
| `check_ntp` | NTP時刻同期状態の確認のみ | 不要 | chrony/systemd-timesyncd のオフセットを判定、CSV出力 |
| `install_apt` | aptパッケージの一括インストール | 要 | `--data pkg=` カンマ区切り指定、インストール済みはスキップ（冪等） |
| `install_deb` | .debファイルの転送・インストール | 要 | Ubuntuバージョン別ディレクトリから該当debを自動選択、バージョン一致ならスキップ |
| `update_kernel` | カーネル最新化＋自動再起動 | 要 | GA/HWE自動判定、GPUサーバはNvidiaドライバも更新、再起動要否を自動判定 |

## 共通実装パターン

- 各タスクの `main.py` は `python.call(function=...)` でステージを直列に並べる構成（`0.xxx`, `1.xxx`, ... と番号付きのnameで実行順を明示）。
- `sudo` を使うタスクは冒頭に `0.cleanup_askpass` ステージを持つ。pyinfraがsudo実行時に `/tmp` に作る一時askpassスクリプトが異常終了時に残存し、後続実行で `Exec format error` を起こすため、実行のたびに `/tmp/pyinfra-sudo-askpass-*` を検出・削除する（sudo権限は不要）。このヘルパーは各 `tasks/*/main.py` に同一コードがコピーされている（共通化はされていない）。
- `host.data.get('sudo_password')` はインベントリの `getpass` で収集した値を各ホストに配流したもの。`server.shell`/`host.run_shell_command` に `_sudo=True, _sudo_password=...` として渡す。
- シェルコマンドは概ね `_env={"LC_ALL": "C"}` を付与し、ロケール依存の出力ゆれを防止。
- CSV出力系タスク（`check_ntp`, `update_kernel`）は `output/<task>/` に結果を書き出し、`.gitignore` でコミット対象外。
- 冪等性を重視: `dpkg-query` 等で状態を事前確認し、変更不要ならスキップするタスクが多い。

## セキュリティ・機密情報の扱い

- `.gitignore` で除外: `inventories/inventory*.py`（sudoパスワード含む）、`output/*`。
- コミット対象はテンプレートのみ: `inventories/inventory.py.template`。
- シェルコマンドへ動的値を埋め込む場合は `shlex.quote()` でエスケープし、コマンドインジェクションを防止すること。

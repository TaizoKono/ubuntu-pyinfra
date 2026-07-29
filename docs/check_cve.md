# check_cve タスク

UbuntuサーバのCVE脆弱性を検出し、Ubuntu Pro APIを活用してレポート作成およびパッチ適用を行うタスクです。

## 実行コマンド

```bash
uv run pyinfra inventories/inventory.py deploys/check_cve.py [--data オプション] [--dry-run]
```

## 実行パターン

### パターンA: 実機スキャン（デフォルト）

サーバー上で直接 `pro cves` コマンドを実行して調査します。

```bash
uv run pyinfra inventories/inventory.py deploys/check_cve.py
```

### パターンB: 特定のCVE番号をピンポイントで調査

実機スキャンを行わず、指定した特定のCVE番号のみを直接調査対象とします（カンマ区切りで複数指定可能）。

```bash
uv run pyinfra inventories/inventory.py deploys/check_cve.py --data cves="CVE-2024-31578,CVE-2023-2640"
```

## オプション (--data)

| オプション | 値 | 内容 |
| :--- | :--- | :--- |
| `cves` | `"CVE-XXXX-YYYY,..."` | 特定のCVE番号のみをピンポイントでチェック対象にする |
| `only_critical` | `true` | 重要度が "Critical" のものだけに絞り込む（デフォルトは High以上） |
| `exclude_pro` | `true` | Ubuntu Pro登録やサービス有効化が必要な修正を除外する |
| `run_update` | `true` | 調査だけでなく、実際にパッチの適用（execute）まで行う |
| `chunk_size` | 整数（デフォルト: `20`） | `pro api` に一度に渡すCVEの件数。CVE件数が多くAPIエラーが頻発する場合は小さく（例: `10`）設定する |
| `false_positive` | `true` | `current_status` と `expected_status` が共に `not-affected` または `fixed` で一致する行のみCSVに出力する（誤検知の確認用） |

### 使用例：重要度Criticalのみを調査してアップデートまで実行

```bash
uv run pyinfra inventories/inventory.py deploys/check_cve.py --data only_critical=true --data run_update=true
```

## 出力成果物

実行完了後、`output/check_cve/` ディレクトリに以下のファイルが生成されます。

- **`summary_<host>_<date>.csv`**
  - **CVE ID**: 脆弱性番号（昇順ソート済）
  - **Current Status**: 現在の状態（still-affected など）。`run_update=true` の場合はパッチ適用後の再スキャン結果で上書きされる
  - **Expected Status**: 修正後の期待ステータス
  - **Packages**: 影響を受けるパッケージ名
  - **Action Needed**: 修正に必要な具体的なアクション（ESM有効化、アップグレード手順など）

## 注意事項

- **カーネル・Nvidia 系パッケージ**: `run_update=true` を指定しても、`linux`, `linux-*`, `nvidia-*` に関連する CVE は適用されません。これらの更新は `update_kernel` タスクで行ってください。該当 CVE は summary CSV には記録されます。

## 前提条件

- **Ubuntu Pro**: 実機スキャンや詳細プラン取得には、対象サーバーが Ubuntu Pro に紐付いている必要があります。

## 実行制御

- **順次実行**: `1.get (Fetch CVEs)` フェーズは、対象サーバーへの負荷集中を避けるため、ホスト1台ずつ順番に実行されます。後続の `2.scan_and_plan` や `3.finalize` は並列で高速に実行されます。

## 残存ファイルのクリーンアップ

pyinfraはsudo実行のたびに、パスワードを渡すための一時的なaskpassスクリプトを対象サーバの `/tmp` に作成し、通常は実行完了時に自動で削除します。ただし、SSH切断やタイムアウト等で実行が異常終了した場合、このファイルが削除されずに残ることがあります。

残存したaskpassファイルは後続の実行で `sudo: ... Exec format error` のようなエラーを引き起こすことがあるため、`0.cleanup_askpass` フェーズで実行のたびに `/tmp/pyinfra-sudo-askpass-*` を確認し、残っていれば削除しています（sudo権限は不要）。

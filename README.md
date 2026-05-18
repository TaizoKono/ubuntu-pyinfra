# Auto-Infra: CVE Management Pipeline

Ubuntuサーバーの脆弱性（CVE）を検出し、Ubuntu Pro APIを活用してレポート作成およびパッチ適用を行う自動化ツールです。

## 1. 基本的な使い方

実行を開始するとローカル端末でSudoパスワードの入力が求められます。

### パターンA: SentinelOne APIを使用（デフォルト）
SentinelOneの管理情報を元に、対象ホストの脆弱性を調査します。
```bash
uv run pyinfra inventories/inventory.py deploys/deploy_check_cve.py
```

### パターンB: 実機スキャンを強制
S1を経由せず、サーバー上で直接 `pro cves` コマンドを実行して調査します。
```bash
uv run pyinfra inventories/inventory.py deploys/deploy_check_cve.py --data no_s1=true
```

### パターンC: 特定のCVE番号をピンポイントで調査
S1や実機スキャンを行わず、指定した特定のCVE番号のみを直接調査対象とします（カンマ区切りで複数指定可能）。
```bash
uv run pyinfra inventories/inventory.py deploys/deploy_check_cve.py --data cves="CVE-2024-31578,CVE-2023-2640"
```


## 2. 主要なオプション (--data)

実行コマンドの末尾に `--data オプション名=値` を付与して制御します。

| オプション | 値 | 内容 |
| :--- | :--- | :--- |
| `cves` | `"CVE-XXXX-YYYY,..."` | 特定のCVE番号のみをピンポイントでチェック対象にする |
| `no_s1` | `true` | SentinelOne APIを使用せず、実機スキャンを実行する |
| `only_critical` | `true` | 重要度が "Critical" のものだけに絞り込む (デフォルトは High以上) |
| `exclude_pro` | `true` | Ubuntu Pro登録やサービス有効化が必要な修正を除外する |
| `run_update` | `true` | 調査だけでなく、実際にパッチの適用（execute）まで行う |

### 使用例：重要度Criticalのみを調査してアップデートまで実行
```bash
uv run pyinfra inventories/inventory.py deploys/deploy_check_cve.py --data only_critical=true --data run_update=true
```

## 3. 出力成果物

実行完了後、`output/check_cve/` ディレクトリに以下のファイルが生成されます。

- **`summary_<host>_<date>.csv`**:
  - **CVE ID**: 脆弱性番号（昇順ソート済）
  - **Current Status**: 現在の状態（still-affected など）
  - **Packages**: 影響を受けるパッケージ名
  - **Action Needed**: 修正に必要な具体的なアクション（ESM有効化、アップグレード手順など）

## 4. 前提条件

- **Ubuntu Pro**: 実機スキャンや詳細プラン取得には、対象サーバーが Ubuntu Pro に紐付いている必要があります。
- **S1 Token**: APIモードを利用する場合、`files/check_cve/token` に有効なApiTokenが配置されている必要があります。
- **inventory.py**: 対象ホストおよびSudoパスワードの収集設定が完了していること。

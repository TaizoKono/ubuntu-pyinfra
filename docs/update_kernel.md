# update_kernel タスク

複数のUbuntuサーバの最新カーネルを一括更新し、自動再起動・検証するタスクです。
GPU サーバに対しては Nvidia ドライバの更新も同時に行います。

## 実行コマンド

```bash
uv run pyinfra inventories/inventory.py deploys/update_kernel.py [--dry]
```

## GPU サーバの設定

`inventories/inventory.py` の各ホスト定義に `is_gpu` フラグを追加してください。

```python
target = [
    ("server1",     {"sudo_password": "...", "is_gpu": False}),  # 非GPUサーバ
    ("gpu-server1", {"sudo_password": "...", "is_gpu": True}),   # GPUサーバ
]
```

`is_gpu: True` のサーバでは、カーネル更新に加えて `ubuntu-drivers autoinstall` で
Nvidia ドライバが自動的に更新されます。

## 更新方式

### カーネル

**メタパッケージ経由での最新更新（GA / HWE 自動判定）**

`pre_check` ステージで `linux-image-generic-hwe-*` メタパッケージが導入済みかを確認し、
GA / HWE を自動判定して適切なメタパッケージを使用します。

| 種別 | 使用するメタパッケージ |
| :--- | :--- |
| GA | `linux-image-generic`, `linux-headers-generic` |
| HWE | `linux-image-generic-hwe-<ubuntu-version>`, `linux-headers-generic-hwe-<ubuntu-version>` |

- `apt` が依存関係をすべて自動解決
- `linux-image-generic` の依存先 `linux-image-<version>-generic` が
  `Recommends: linux-modules-extra-<version>-generic` を持つため、
  追加デバイスドライバも自動インストール
- initramfs の問題を回避

### Nvidia ドライバ（GPU サーバのみ）

```bash
ubuntu-drivers autoinstall
```

- Ubuntu が推奨するドライバを自動選択してインストール
- DKMS により新しいカーネル向けのモジュールが自動ビルドされる

## パラメータ

| パラメータ | 必須 | 説明 |
| :--- | :--- | :--- |
| `nvidia_driver` | 任意 | Nvidia ドライバのメジャーバージョン番号（例: `535`）。指定しない場合は `ubuntu-drivers autoinstall` で推奨版を自動選択。 |

GPU/非GPU の区別は `inventory.py` の `is_gpu` フラグで制御します。

## 使用例

### 事前確認（--dry で確認）

```bash
uv run pyinfra inventories/inventory.py deploys/update_kernel.py --dry
```

出力例：

```
--> Preparing operation files...
    [server1]     Current kernel: 5.4.0-216-generic (will update to latest available)
    [gpu-server1] Current kernel: 5.4.0-216-generic (will update to latest available)
    [gpu-server1] Current Nvidia driver: 535.183.01 (will update via ubuntu-drivers autoinstall)
```

### 実行

```bash
# Nvidia ドライバは推奨版を自動選択
uv run pyinfra inventories/inventory.py deploys/update_kernel.py

# R535 系の最新版に固定する場合
uv run pyinfra inventories/inventory.py deploys/update_kernel.py --data nvidia_driver=535
```

## 処理フロー

| ステージ | 内容 |
| :--- | :--- |
| `0.pre_check` | 現在のカーネル・インストール済みカーネル一覧を取得。GPU サーバは Nvidia ドライバ情報も取得 |
| `1.install` | メタパッケージで最新カーネルをインストール。`/var/run/reboot-required` および最新インストール済みカーネルと実行中カーネルの差分で再起動要否を判定 |
| `2.nvidia_install` | GPU サーバのみ: `ubuntu-drivers autoinstall` で Nvidia ドライバを更新 |
| `3.reboot` | カーネルまたはドライバの更新があった場合のみ再起動 |
| `4.post_check` | 起動中カーネルを確認。GPU サーバは `nvidia-smi` でドライバを確認。エラーログをチェック。結果を CSV に記録 |

## 出力成果物

実行完了後、`output/update_kernel/kernel_current.csv` が生成されます。

### CSV フォーマット

```csv
hostname,before,after,status,driver_before,driver_after,driver_status
server1,5.4.0-216-generic,5.4.0-231-generic,updated,,,
gpu-server1,5.4.0-216-generic,5.4.0-231-generic,updated,535.183.01,550.90.12,updated
```

| 列 | 説明 |
| :--- | :--- |
| `hostname` | ホスト名 |
| `before` | 更新前のカーネルバージョン |
| `after` | 更新後のカーネルバージョン |
| `status` | `updated`（更新あり）または `no_change`（変わらず） |
| `driver_before` | 更新前の Nvidia ドライババージョン（非GPU は空） |
| `driver_after` | 更新後の Nvidia ドライババージョン（非GPU は空） |
| `driver_status` | `updated`（更新あり）または `no_change`（変わらず）（非GPU は空） |

毎回の実行で上書きされるため、最新の結果が保持されます。

## 冪等性

既にリポジトリの最新カーネル・ドライバで実行中の場合、再インストールは発生せず再起動もスキップされます。再実行しても安全です。

## 注意事項

- **再起動**: 新しいカーネルまたはドライバがインストールされた場合、自動で再起動が行われます。本番環境では計画的な実行をお勧めします。
- **ディスク容量**: カーネルのインストールには約 1GB の空き容量が必要です。
- **is_gpu フラグ未設定**: `is_gpu` が未設定または `False` のサーバは Nvidia ドライバ更新をスキップします。

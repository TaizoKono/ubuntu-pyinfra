# check_ntp タスク

各Ubuntuサーバの時刻同期（NTP）状態を確認するタスクです。設定変更は行わず、確認のみ行います。

## 実行コマンド

```bash
uv run pyinfra inventories/inventory.py deploys/check_ntp.py [--dry-run]
```

## 確認内容

- `timedatectl` により NTP 同期状態（`NTPSynchronized`）とタイムゾーンを取得
- `chronyc`（chrony）または `timedatectl timesync-status`（systemd-timesyncd）により、
  利用可能な場合は現在の時刻オフセット（秒）も取得
- 取得したオフセットが許容値（±1秒未満）以内かどうかを判定
- サーバの現在時刻（ローカルタイム）を取得

sudo権限は不要です。

## 判定基準

オフセットの絶対値が **1秒未満** であれば `NTP Sync OK`、1秒以上（超過）であれば `NTP Sync NG` と判定します。

オフセットが取得できない環境（chrony・systemd-timesyncdのいずれも利用できない場合）では、`timedatectl` の `NTPSynchronized` フラグにフォールバックして判定します（`yes` なら `NTP Sync OK`、`no` なら `NTP Sync NG`）。

## 出力成果物

実行完了後、`output/check_ntp/ntp_status.csv` が生成されます。

### CSV フォーマット

```csv
hostname,status,synchronized,ntp_service,offset_sec,timezone,local_time
server1,NTP Sync OK,yes,systemd-timesyncd,-854us,Asia/Tokyo,2026-07-27 10:00:00 JST
server2,NTP Sync NG,no,systemd-timesyncd,,Asia/Tokyo,2026-07-27 10:00:03 JST
```

| 列 | 説明 |
| :--- | :--- |
| `hostname` | ホスト名 |
| `status` | 判定結果。`NTP Sync OK`（許容範囲内）または `NTP Sync NG`（許容範囲超過） |
| `synchronized` | `timedatectl` が報告する同期フラグ（`yes` / `no`） |
| `ntp_service` | 検出されたNTPサービス（`chrony` / `systemd-timesyncd` / `unknown`） |
| `offset_sec` | 検出できた場合の時刻オフセット（取得元のフォーマットのまま。例: `-854us`, `+1.024ms`）。取得できない場合は空 |
| `timezone` | サーバに設定されているタイムゾーン |
| `local_time` | 実行時点のサーバのローカル時刻 |

毎回の実行で上書きされるため、最新の結果が保持されます。

## 注意事項

- `status` が `NTP Sync NG` のホストはログに警告として出力されます。
- `offset_sec` は chrony または systemd-timesyncd のいずれも利用できない環境では取得できません（空欄になります）。この場合は `synchronized` フラグのみで判定されます。

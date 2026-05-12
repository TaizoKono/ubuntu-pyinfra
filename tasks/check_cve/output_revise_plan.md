# CVE出力ファイル設計プラン (output_revise_plan)

Ansibleから引き継いだ現在の多段階CSV出力を整理し、Pyinfraの `host.data` を活用した効率的なデータ管理へ移行するための棚卸しです。

## 1. 現状の出力ファイル一覧

| 生成順 | ファイル名 (例) | 主な役割 | 主要なカラム |
| :--- | :--- | :--- | :--- |
| 1 | `list_ollo7-new.csv` | 調査対象のCVE IDリスト | `CVE ID` |
| 2 | `csv-check_ollo7-new_20260511.csv` | 各CVEのUbuntu Pro API判定結果 | `CVE ID`, `priority`, `affected_package`, `check` (判定) |
| 3 | `fix-check_ollo7-new_20260511.csv` | `pro fix --dry-run` のパース結果 | `CVE ID`, `package`, `review` (修正可否), `fix_info` |
| 4 | `update-plan_ollo7-new_20260511.csv` | 自動適用可能なコマンド一覧 | `command`, `package`, `CVE ID` |
| 5 | `summary_ollo7-new_20260511.csv` | **【最終成果物】** 全情報を統合 | `CVE ID`, `Priority`, `Check Result`, `Package`, `Review`, `Fix Message` |

## 2. 現在のステップ間データ受け渡し (課題)

1.  **0.get (Fetch)**: リストを作成しディスクへ。
2.  **1.check (Scan)**: ディスクからリストを読み、スキャン結果を再度ディスクへ。
3.  **2.fix_info (Parse)**: スキャン結果を読み、`pro fix` の詳細を解析してディスクへ。
4.  **3/4.Finalize**: 過去のCSVを読み込み、フィルタリングして最終報告書と適用プランを作成。

**課題**:
- 重複データの蓄積（各ファイルに `CVE ID` や `Package` が何度も書き込まれる）。
- 記録として残すべきなのは「最終結果」と「実行したプラン」のみだが、中間ファイルが多すぎて管理が煩雑。

## 3. `host.data` を活用した新構造案

各フェーズでCSVを吐き出すのをやめ、Pythonのリストや辞書としてメモリに保持します。

| フェーズ | `host.data` に保持するデータ構造 |
| :--- | :--- |
| **0.get** | `cve_list = ['CVE-1', 'CVE-2', ...]` |
| **1.check** | `check_results = { 'CVE-1': { 'priority': 'high', 'pkgs': [...] }, ... }` |
| **2.fix_info** | `fix_details = [ { 'cve': 'CVE-1', 'pkg': 'pkg-a', 'review': 'PATCHABLE', 'cmd': '...' }, ... ]` |
| **最終出力** | **`summary_<host>.csv`** (全情報を統合) |
| **最終出力** | **`update_plan_<host>.csv`** (実際に叩くべきコマンド一覧) |

## 4. 次のステップ

1.  `tasks/check_cve/main.py` 内のCSV書き出し・読み込み処理を、`host.data` への代入・参照に置き換える。
2.  外部スクリプト (`parse_fix.py`, `make_plan.py`, `make_summary.py`) で行っていたパース/加工処理を `main.py` の内部関数として取り込む。
3.  成果物を「本当に必要な2つのCSV」に絞り込む。

この構成に変更することで、ディスクI/Oが減り、コードの可視性が大幅に向上します。



### 5. コマンド変更案
**0.get (Fetch)**: 
既存のままS1 APIか`pro cves`

**1.check (Scan), 2.fix_info (Parse)**: 
pro apiコマンドから
~~~sh
pro api u.pro.security.fix.cve.plan.v1 \
--data '{"cves":["CVE-YYYY-AAAA","CVE-YYYY-BBBB","CVE-YYYY-CCCC"]}'
~~~
出力例
~~~sh
$ pro api u.pro.security.fix.cve.plan.v1 --data '{"cves":["CVE-2024-31578"]}'
{"_schema_version": "v1", "data": {"attributes": {"cves_data": {"cves": [{"additional_data": {}, "affected_packages": ["ffmpeg"], "current_status": "still-affected", "description": "FFmpeg vulnerabilities", "error": null, "expected_status": "fixed", "plan": [{"data": {"reason": "required-pro-service", "required_service": "esm-apps", "source_packages": ["ffmpeg"]}, "operation": "attach", "order": 1}, {"data": {"service": "esm-apps", "source_packages": ["ffmpeg"]}, "operation": "enable", "order": 2}, {"data": {"binary_packages": ["ffmpeg", "libavcodec-dev", "libavcodec58", "libavdevice58", "libavfilter7", "libavformat-dev", "libavformat58", "libavutil-dev", "libavutil56", "libpostproc55", "libswresample-dev", "libswresample3", "libswscale-dev", "libswscale5"], "pocket": "esm-apps", "source_packages": ["ffmpeg"]}, "operation": "apt-upgrade", "order": 3}], "title": "CVE-2024-31578", "warnings": []}], "expected_status": "fixed"}}, "meta": {"environment_vars": []}, "type": "CVEFixPlan"}, "errors": [], "result": "success", "version": "37.1ubuntu0~22.04", "warnings": [{"code": "new-version-available", "meta": {}, "title": "A new version of the client is available: 37.2ubuntu~22.04. Please upgrade to the latest version to get the new features and bug fixes."}]}
~~~
~~~sh
$ pro api u.pro.security.fix.cve.plan.v1 --data '{"cves":["CVE-2024-31578"]}'
{"_schema_version": "v1", "data": {"attributes": {"cves_data": {"cves": [{"additional_data": {}, "affected_packages": ["ffmpeg"], "current_status": "still-affected", "description": "FFmpeg vulnerabilities", "error": null, "expected_status": "fixed", "plan": [{"data": {"reason": "required-pro-service", "required_service": "esm-apps", "source_packages": ["ffmpeg"]}, "operation": "attach", "order": 1}, {"data": {"service": "esm-apps", "source_packages": ["ffmpeg"]}, "operation": "enable", "order": 2}, {"data": {"binary_packages": ["ffmpeg", "libavcodec-dev", "libavcodec58", "libavdevice58", "libavfilter7", "libavformat-dev", "libavformat58", "libavutil-dev", "libavutil56", "libpostproc55", "libswresample-dev", "libswresample3", "libswscale-dev", "libswscale5"], "pocket": "esm-apps", "source_packages": ["ffmpeg"]}, "operation": "apt-upgrade", "order": 3}], "title": "CVE-2024-31578", "warnings": []}], "expected_status": "fixed"}}, "meta": {"environment_vars": []}, "type": "CVEFixPlan"}, "errors": [], "result": "success", "version": "37.1ubuntu0~22.04", "warnings": [{"code": "new-version-available", "meta": {}, "title": "A new version of the client is available: 37.2ubuntu~22.04. Please upgrade to the latest version to get the new features and bug fixes."}]}
~~~

**3/4.Finalize**:
サマリ→上記出力のまとめ
実行→pro apiコマンド
~~~sh
pro api u.pro.security.fix.cve.execute.v1 --data '{"cves":["CVE-YYYY-AAAA","CVE-YYYY-BBBB","CVE-YYYY-CCCC"]}'
~~~
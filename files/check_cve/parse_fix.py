import sys
import json
import re
import csv

# 標準入力からAnsibleのregister結果(JSON)を読み込む
data = json.load(sys.stdin)
writer = csv.writer(sys.stdout)
writer.writerow(['CVE ID', 'package', 'review', 'fix_info'])

def get_review(info):
    if info.startswith("A fix is available in Ubuntu standard updates. The update is already installed.") or \
       (info.startswith("A fix is available in Ubuntu standard updates.") and "{ apt" in info):
        return "PATCHABLE"
    elif info.startswith("A fix is available in Ubuntu standard updates. - Cannot install package") or info.startswith("A reboot is required to complete fix operation."):
        return "MANUALLY_PATCHABLE"
    elif info.startswith("A fix is available in Ubuntu Pro") or info.startswith("Sorry, no fix is available") or info.startswith("Ubuntu security engineers are investigating this issue."):
        return "NOT_PATCHABLE"
    return "OTHER"

for res in data.get('results', []):
    cve_id = res.get('item')
    stdout = res.get('stdout', '')
    
    # stdoutをパース
    packages = {}
    current_pkg = None
    current_info = []
    
    for line in stdout.split('\n'):
        m = re.match(r'^\(\d+/\d+\)\s+(.*?):', line)
        if m:
            if current_pkg:
                packages[current_pkg] = " ".join(current_info).strip()
            current_pkg = m.group(1)
            current_info = []
        elif current_pkg:
            if re.match(r'^(\d+ package|[✔✘])', line) or line.strip() == '':
                packages[current_pkg] = " ".join(current_info).strip()
                current_pkg = None
            else:
                current_info.append(line.strip())
    
    # 最後のパッケージ情報を保存
    if current_pkg:
        packages[current_pkg] = " ".join(current_info).strip()
        
    for pkg, info in packages.items():
        # 不要なANSIカラーコード等を除去
        info = re.sub(r'\x1b\[[0-9;]*m', '', info)
        info = info.replace('[37m', '').replace('[0m', '')
        
        review = get_review(info)
        writer.writerow([cve_id, pkg, review, info])

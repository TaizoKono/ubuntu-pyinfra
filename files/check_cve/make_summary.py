import sys
import csv

if len(sys.argv) < 4:
    print("Usage: make_summary.py <check_csv> <fix_csv> <output_csv>")
    sys.exit(1)

check_file = sys.argv[1]
fix_file = sys.argv[2]
output_file = sys.argv[3]

# fix_info を辞書に読み込む (キー: CVE ID と パッケージ)
fixes = {}
try:
    with open(fix_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # カラム名の揺れを吸収 (package or affected_package)
            pkg = row.get('package') or row.get('affected_package') or ""
            fixes[(row['CVE ID'], pkg)] = row
except FileNotFoundError:
    pass

# check_info を読み込みながら結合
try:
    with open(check_file, 'r', encoding='utf-8') as f_in:
        reader = csv.DictReader(f_in)
        # 実際のヘッダー名を確認
        fieldnames = reader.fieldnames
        # ヘッダー名に含まれるスペースをトリムしておく
        pkg_col = next((f for f in fieldnames if f.strip() == 'affected_package'), 'affected_package')
        cve_col = next((f for f in fieldnames if f.strip() == 'CVE ID'), 'CVE ID')
        priority_col = next((f for f in fieldnames if f.strip() == 'priority'), 'priority')
        check_col = next((f for f in fieldnames if f.strip() == 'check'), 'check')

        with open(output_file, 'w', encoding='utf-8', newline='') as f_out:
            writer = csv.writer(f_out)
            writer.writerow(['CVE ID', 'Priority', 'Check Result', 'Package', 'Review', 'Fix Message'])
            
            for row in reader:
                cve_id = row[cve_col].strip()
                pkg = row[pkg_col].strip()
                priority = row[priority_col].strip()
                check_res = row[check_col].strip()
                
                fix_row = fixes.get((cve_id, pkg), {})
                review = fix_row.get('review', '').strip()
                fix_msg = fix_row.get('fix_info', '').strip()
                
                writer.writerow([cve_id, priority, check_res, pkg, review, fix_msg])
except FileNotFoundError:
    print(f"Error: Check file {check_file} not found.")
    sys.exit(1)
except Exception as e:
    print(f"Error: {str(e)}")
    sys.exit(1)

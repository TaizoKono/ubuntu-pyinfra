import sys
import csv
import re
from collections import defaultdict

if len(sys.argv) < 3:
    print("Usage: make_plan.py <input_csv> <output_csv>")
    sys.exit(1)

input_file = sys.argv[1]
output_file = sys.argv[2]

plan = defaultdict(lambda: {'pkgs': set(), 'cves': set()})

try:
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['review'] == 'PATCHABLE':
                # Extract command between { }
                m = re.search(r'\{(.*?)\}', row['fix_info'])
                if m:
                    cmd = m.group(1).strip()
                    # Clean up multiple spaces, newlines, and backslashes
                    cmd = re.sub(r'\\\s*\n', ' ', cmd)
                    cmd = re.sub(r'\s+', ' ', cmd)
                    plan[cmd]['pkgs'].add(row['package'])
                    plan[cmd]['cves'].add(row['CVE ID'])
except FileNotFoundError:
    print(f"Error: Input file {input_file} not found.")
    sys.exit(1)

with open(output_file, 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['command', 'package', 'CVE ID'])
    for cmd, data in plan.items():
        writer.writerow([cmd, "; ".join(sorted(data['pkgs'])), "; ".join(sorted(data['cves']))])

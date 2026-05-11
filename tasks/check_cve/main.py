import os
import json
import re
import csv
import requests
import subprocess
from datetime import datetime
from pyinfra.operations import apt, python, server
from pyinfra import logger
from pyinfra.api.exceptions import OperationError

def _get_cves(state, host):
    hostname_res = host.run_shell_command("hostname")
    target_hostname = hostname_res[1].stdout.strip()
    
    token_path = "files/check_cve/token"
    s1_token = ""
    if os.path.exists(token_path):
        with open(token_path, "r") as f:
            s1_token = f.read().strip()
            
    target_severity = host.data.get('target_severity', 'critical').lower()
    if target_severity == 'high':
        s1_api_severity = "HIGH"
    elif target_severity == 'high_or_above':
        s1_api_severity = "CRITICAL,HIGH"
    else:
        s1_api_severity = "CRITICAL"

    s1_cve_list = []
    
    if s1_token:
        url = f"https://apse1-globalsoc.sentinelone.net/web/api/v2.1/application-management/risks?endpointName__contains={target_hostname}&severities={s1_api_severity}&limit=1000"
        headers = {"Authorization": f"ApiToken {s1_token}"}
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for item in data:
                    cve_id = item.get("cveId")
                    if cve_id and cve_id not in s1_cve_list:
                        s1_cve_list.append(cve_id)
        except Exception as e:
            logger.warning(f"Failed to fetch from S1: {e}")

    if not s1_cve_list:
        logger.info("No CVEs from S1, running pro cves locally.")
        host.run_shell_command("apt-get update && apt-get install -y ubuntu-pro-client", _sudo=True)
        res = host.run_shell_command("pro cves", _sudo=True)
        
        logger.info(f"pro cves status: {res[0]}")
        logger.info(f"pro cves stderr: {getattr(res[1], 'stderr', 'None')}")
        
        if res[1].stdout:
            # DEBUG: dump the raw stdout to a file to inspect it
            with open("output/check_cve/debug_pro_cves.txt", "w") as dbg:
                dbg.write(res[1].stdout)
                
            clean_stdout = re.sub(r'\x1b\[[0-9;]*m', '', res[1].stdout)
            matches = re.findall(r'(CVE-\d{4}-\d+)\s+\S+\s+(?:high|critical)', clean_stdout, re.IGNORECASE)
            s1_cve_list = list(set(matches))
            
            # DEBUG: dump the cleaned stdout as well
            with open("output/check_cve/debug_pro_cves_clean.txt", "w") as dbg:
                dbg.write(clean_stdout)

    os.makedirs("output/check_cve", exist_ok=True)
    list_path = f"output/check_cve/list_{host.name}.csv"
    with open(list_path, "w") as f:
        f.write("CVE ID\n")
        for cve in s1_cve_list:
            f.write(f"{cve}\n")
            
    host.data.cve_list_path = list_path
    host.data.cve_list = s1_cve_list


def _check_cves(state, host):
    host.run_shell_command("apt-get update", _sudo=True)
    cve_list = host.data.get('cve_list', [])
    csv_date = datetime.now().strftime('%Y%m%d')
    host.data.csv_date = csv_date
    
    parsed_cves = []
    api_results_dict = {}

    for cve in cve_list:
        res = host.run_shell_command(f"pro cve {cve}", _sudo=True)
        stdout = res[1].stdout if res[1].stdout else ""
        
        priority_match = re.search(r'(?i)priority:[\s]*([a-z]+)', re.sub(r'\x1b\[[0-9;]*m', '', stdout))
        priority = priority_match.group(1) if priority_match else 'unknown'
        has_packages = bool(re.search(r'(?m)^affected_packages:', stdout))
        
        parsed_cves.append({
            'id': cve,
            'priority': priority,
            'has_packages': has_packages
        })
        
    target_api_cves = [c['id'] for c in parsed_cves if c['has_packages']]
    for cve in target_api_cves:
        res = host.run_shell_command(f"pro api u.pro.security.fix.cve.plan.v1 --data '{{\"cves\":[\"{cve}\"]}}'", _sudo=True)
        if res[1].stdout and res[1].stdout.strip().startswith('{'):
            try:
                data = json.loads(res[1].stdout)
                cves_data = data.get('data', {}).get('attributes', {}).get('cves_data', {}).get('cves', [])
                if cves_data:
                    api_results_dict[cve] = cves_data[0]
            except Exception:
                pass

    check_csv_path = f"output/check_cve/csv-check_{host.name}_{csv_date}.csv"
    with open(check_csv_path, "w") as f:
        writer = csv.writer(f)
        writer.writerow(["CVE ID", "priority", "affected_package", "current_status", "expected_status", "plan", "check"])
        for cve in parsed_cves:
            cve_id = cve['id']
            if cve_id in api_results_dict:
                api = api_results_dict[cve_id]
                pkgs = api.get('affected_packages', [])
                status = api.get('current_status', 'N/A')
                expected = api.get('expected_status', 'N/A')
                plan_raw = api.get('plan', [])
                plan_bool = 'true' if len(plan_raw) > 0 else 'false'
                check_val = 'NEED_CHECK_FIX'
                
                if len(pkgs) == 0 or status == 'not-affected':
                    check_val = 'NOT_AFFECTED'
                elif plan_bool == 'false':
                    check_val = 'UNPATCHABLE'
                    
                if pkgs:
                    for pkg in pkgs:
                        writer.writerow([cve_id, cve['priority'], pkg, status, expected, plan_bool, check_val])
                else:
                    writer.writerow([cve_id, cve['priority'], 'none', status, expected, plan_bool, check_val])
            else:
                writer.writerow([cve_id, cve['priority'], 'none', 'N/A', 'N/A', 'false', 'NOT_AFFECTED'])
                
    host.data.check_csv_path = check_csv_path


def _fix_info(state, host):
    check_csv_path = host.data.get('check_csv_path')
    csv_date = host.data.get('csv_date', datetime.now().strftime('%Y%m%d'))
    
    target_cves = set()
    if os.path.exists(check_csv_path):
        with open(check_csv_path, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                if 'NEED_CHECK_FIX' in row:
                    target_cves.add(row[0].strip())
    
    target_cves = list(target_cves)
    pro_fix_results = []
    
    for cve in target_cves:
        res = host.run_shell_command(f"pro fix --dry-run {cve}", _sudo=True)
        pro_fix_results.append({
            'item': cve,
            'stdout': res[1].stdout if res[1].stdout else ""
        })
        
    fix_csv_path = f"output/check_cve/fix-check_{host.name}_{csv_date}.csv"
    input_json = json.dumps({"results": pro_fix_results})
    
    parse_script = "files/check_cve/parse_fix.py"
    if os.path.exists(parse_script):
        with open(fix_csv_path, "w") as out_f:
            p = subprocess.Popen(["python3", parse_script], stdin=subprocess.PIPE, stdout=out_f, stderr=subprocess.PIPE, text=True)
            p.communicate(input=input_json)
    else:
        logger.warning(f"Parse script not found: {parse_script}")
            
    host.data.fix_csv_path = fix_csv_path


def _update_and_summary(state, host):
    fix_csv_path = host.data.get('fix_csv_path')
    check_csv_path = host.data.get('check_csv_path')
    csv_date = host.data.get('csv_date', datetime.now().strftime('%Y%m%d'))
    
    plan_csv_path = f"output/check_cve/update-plan_{host.name}_{csv_date}.csv"
    summary_csv_path = f"output/check_cve/summary_{host.name}_{csv_date}.csv"
    
    # Run make_plan.py
    if os.path.exists("files/check_cve/make_plan.py"):
        subprocess.run(["python3", "files/check_cve/make_plan.py", fix_csv_path, plan_csv_path])
    else:
        logger.warning("make_plan.py not found.")
        
    # Execute update if run_update is set
    run_update_raw = host.data.get('run_update', os.getenv('RUN_UPDATE', False))
    run_update = str(run_update_raw).lower() in ['true', 'yes', '1', 'y']
    
    if run_update and os.path.exists(plan_csv_path):
        with open(plan_csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cmd = row.get('command')
                if cmd:
                    logger.info(f"Running update command: {cmd}")
                    host.run_shell_command(cmd, _sudo=True)

    # Run make_summary.py
    if os.path.exists("files/check_cve/make_summary.py"):
        subprocess.run(["python3", "files/check_cve/make_summary.py", check_csv_path, fix_csv_path, summary_csv_path])
        logger.info(f"Summary report generated at: {summary_csv_path}")
    else:
        logger.warning("make_summary.py not found.")


# Dummy operation to force Pyinfra to prompt for the sudo password if --use-sudo-password is set.
# Without a standard operation requiring _sudo=True, Pyinfra skips the password prompt for python.call operations.
server.shell(
    name="Init sudo credentials",
    commands=["echo 'Sudo initialized'"],
    _sudo=True
)

python.call(
    name="0.get (Fetch CVEs)",
    function=_get_cves
)

python.call(
    name="1.check (Check CVEs locally)",
    function=_check_cves
)

python.call(
    name="2.fix_info (Dry-run fix)",
    function=_fix_info
)

python.call(
    name="3.update & 4.summary",
    function=_update_and_summary
)

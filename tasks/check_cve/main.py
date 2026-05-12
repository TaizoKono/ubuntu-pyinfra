import os
import json
import re
import csv
import requests
from datetime import datetime
from pyinfra.operations import python, server
from pyinfra import logger

def _get_cves(state, host):
    # Determine source (S1 or local scan)
    no_s1_raw = host.data.get('no_s1', os.getenv('NO_S1', False))
    no_s1 = str(no_s1_raw).lower() in ['true', 'yes', '1', 'y']
    
    s1_cve_list = []
    only_critical_raw = host.data.get('only_critical', False)
    only_critical = str(only_critical_raw).lower() in ['true', 'yes', '1', 'y']

    if no_s1:
        logger.info("Mode: Local scan (--no-s1). Fetching CVEs from pro cves.")
        # Local scan requires sudo and English locale
        host.run_shell_command("apt-get update && apt-get install -y ubuntu-pro-client", _sudo=True, _sudo_password=host.data.get('sudo_password'), _env={"LC_ALL": "C"})
        res = host.run_shell_command("pro cves", _sudo=True, _sudo_password=host.data.get('sudo_password'), _env={"LC_ALL": "C"})
        
        if res[1].stdout:
            clean_stdout = re.sub(r'\x1b\[[0-9;]*m', '', res[1].stdout)
            if only_critical:
                regex = r'(CVE-\d{4}-\d+)\s+\S+\s+critical'
                logger.info("Severity filter: CRITICAL only")
            else:
                regex = r'(CVE-\d{4}-\d+)\s+\S+\s+(?:high|critical)'
                logger.info("Severity filter: HIGH or above (default)")
            
            matches = re.findall(regex, clean_stdout, re.IGNORECASE)
            s1_cve_list = list(set(matches))
    else:
        logger.info("Mode: SentinelOne API. Fetching CVEs from S1.")
        hostname_res = host.run_shell_command("hostname", _env={"LC_ALL": "C"})
        target_hostname = hostname_res[1].stdout.strip()
        
        token_path = "files/check_cve/token"
        s1_token = ""
        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                s1_token = f.read().strip()
                
        if only_critical:
            s1_api_severity = "CRITICAL"
            logger.info("Severity filter: CRITICAL only")
        else:
            s1_api_severity = "CRITICAL,HIGH"
            logger.info("Severity filter: HIGH or above (default)")

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
                else:
                    logger.warning(f"S1 API returned status {resp.status_code}")
            except Exception as e:
                logger.warning(f"Failed to fetch from S1: {e}")
        else:
            logger.warning("No S1 token found at files/check_cve/token")

    if not s1_cve_list:
        logger.info("No CVEs found. Stopping further processing for this host.")
        host.data.skip_cve_tasks = True
        return

    host.data.cve_list = sorted(s1_cve_list)
    host.data.skip_cve_tasks = False


def _scan_and_plan(state, host):
    if host.data.get('skip_cve_tasks'):
        return

    cve_list = host.data.get('cve_list', [])
    if not cve_list:
        return

    logger.info(f"Scanning and planning for {len(cve_list)} CVEs using pro api...")
    payload = json.dumps({"cves": cve_list})
    
    # Use pro api to get a structured fix plan in JSON
    res = host.run_shell_command(
        f"pro api u.pro.security.fix.cve.plan.v1 --data '{payload}'",
        _sudo=True,
        _sudo_password=host.data.get('sudo_password'),
        _env={"LC_ALL": "C"}
    )
    
    if res[0] and res[1].stdout:
        try:
            data = json.loads(res[1].stdout)
            # Store the raw CVE results for the finalize step
            host.data.cve_results = data.get('data', {}).get('attributes', {}).get('cves_data', {}).get('cves', [])
        except Exception as e:
            logger.error(f"Failed to parse pro api output: {e}")
            host.data.skip_cve_tasks = True
    else:
        logger.error(f"pro api command failed or returned empty output: {res[1].stderr}")
        host.data.skip_cve_tasks = True


def _finalize(state, host):
    if host.data.get('skip_cve_tasks'):
        return

    cve_results = host.data.get('cve_results', [])
    csv_date = datetime.now().strftime('%Y%m%d')
    os.makedirs("output/check_cve", exist_ok=True)
    summary_path = f"output/check_cve/summary_{host.name}_{csv_date}.csv"

    # Helper to humanize the plan operations
    def get_action_desc(plan):
        if not plan:
            return "No plan available"
        ops = []
        for p in plan:
            op = p.get('operation')
            if op == 'attach':
                ops.append("Attach Pro")
            elif op == 'enable':
                ops.append(f"Enable {p.get('data', {}).get('service', 'service')}")
            elif op == 'apt-upgrade':
                ops.append("Apt Upgrade")
            else:
                ops.append(op)
        return " -> ".join(ops)

    # 1. Generate Summary CSV (sorted by CVE ID)
    sorted_results = sorted(cve_results, key=lambda c: c.get('title', ''))
    with open(summary_path, "w", encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["CVE ID", "Current Status", "Expected Status", "Packages", "Action Needed"])
        
        for cve in sorted_results:
            writer.writerow([
                cve.get('title'),
                cve.get('current_status'),
                cve.get('expected_status'),
                ", ".join(cve.get('affected_packages', [])),
                get_action_desc(cve.get('plan', []))
            ])
    
    logger.info(f"Summary report generated at: {summary_path}")

    # 2. Prepare for Execution
    run_update_raw = host.data.get('run_update', os.getenv('RUN_UPDATE', False))
    run_update = str(run_update_raw).lower() in ['true', 'yes', '1', 'y']
    
    exclude_pro_raw = host.data.get('exclude_pro', False)
    exclude_pro = str(exclude_pro_raw).lower() in ['true', 'yes', '1', 'y']
    
    def needs_pro(plan):
        return any(p.get('operation') in ['attach', 'enable'] for p in plan)
    
    if run_update:
        # Only execute for those still affected and having a plan
        patchable_cves = []
        for cve in cve_results:
            if cve.get('current_status') == 'still-affected' and cve.get('plan'):
                if exclude_pro and needs_pro(cve.get('plan', [])):
                    logger.info(f"Skipping {cve.get('title')} as it requires Ubuntu Pro and exclude_pro is set.")
                    continue
                patchable_cves.append(cve.get('title'))
        
        if patchable_cves:
            logger.info(f"Found {len(patchable_cves)} patchable CVEs. Preparing execution...")
            payload = json.dumps({"cves": patchable_cves})
            
            # Use server.shell for better dry-run visibility
            server.shell(
                name="Execute CVE fixes via pro api",
                commands=[f"pro api u.pro.security.fix.cve.execute.v1 --data '{payload}'"],
                _sudo=True,
                _sudo_password=host.data.get('sudo_password'),
                _env={"LC_ALL": "C"}
            )
        else:
            logger.info("No patchable CVEs found to execute.")

# Execution Flow
python.call(
    name="0.get (Fetch CVEs)",
    function=_get_cves,
    _sudo=True
)

python.call(
    name="1.scan_and_plan (Pro API Plan)",
    function=_scan_and_plan,
    _sudo=True
)

python.call(
    name="2.finalize (Report & Execute)",
    function=_finalize,
    _sudo=True
)

import os
import json
import re
import csv
import shlex
from datetime import datetime
from pyinfra.operations import python, server
from pyinfra import logger

# カーネル・Nvidia 系パッケージは update_kernel タスクが専任で担うため、
# run_update 時に常に除外する（再起動なし適用を防ぐ）。
_KERNEL_NVIDIA_PKGS = frozenset({'linux', 'linux-firmware'})
_KERNEL_NVIDIA_PREFIXES = ('linux-', 'nvidia-')

_CVE_RE = re.compile(r'^CVE-\d{4}-\d{4,7}$')

def _chunked(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

def _is_kernel_or_nvidia(pkg):
    return pkg in _KERNEL_NVIDIA_PKGS or pkg.startswith(_KERNEL_NVIDIA_PREFIXES)

def _get_cves(state, host):
    # Check if specific CVEs are requested via CLI parameter
    cves_raw = host.data.get('cves')
    if cves_raw:
        if isinstance(cves_raw, list):
            target_cves = [str(c).strip().upper() for c in cves_raw if str(c).strip()]
        else:
            target_cves = [c.strip().upper() for c in str(cves_raw).split(',') if c.strip()]
        
        valid = [c for c in target_cves if _CVE_RE.match(c)]
        invalid = set(target_cves) - set(valid)
        for c in invalid:
            logger.warning(f"Skipping invalid CVE ID format: {c!r}")
        target_cves = valid

        if target_cves:
            logger.info(f"Target CVEs specified via CLI: {target_cves}")
            host.data.cve_list = sorted(list(set(target_cves)))
            host.data.skip_cve_tasks = False
            return

    only_critical_raw = host.data.get('only_critical', False)
    only_critical = str(only_critical_raw).lower() in ['true', 'yes', '1', 'y']

    logger.info("Fetching CVEs from pro cves.")
    host.run_shell_command("apt-get update && apt-get install -y ubuntu-pro-client", _sudo=True, _sudo_password=host.data.get('sudo_password'), _env={"LC_ALL": "C"})
    res = host.run_shell_command("pro cves", _sudo=True, _sudo_password=host.data.get('sudo_password'), _env={"LC_ALL": "C"})

    cve_list = []
    if res[1].stdout:
        clean_stdout = re.sub(r'\x1b\[[0-9;]*m', '', res[1].stdout)
        if only_critical:
            regex = r'(CVE-\d{4}-\d+)\s+\S+\s+critical'
            logger.info("Severity filter: CRITICAL only")
        else:
            regex = r'(CVE-\d{4}-\d+)\s+\S+\s+(?:high|critical)'
            logger.info("Severity filter: HIGH or above (default)")

        matches = re.findall(regex, clean_stdout, re.IGNORECASE)
        cve_list = list(set(matches))

    if not cve_list:
        logger.info("No CVEs found. Stopping further processing for this host.")
        host.data.skip_cve_tasks = True
        return

    host.data.cve_list = sorted(cve_list)
    host.data.skip_cve_tasks = False


def _scan_and_plan(state, host):
    if host.data.get('skip_cve_tasks'):
        return

    cve_list = host.data.get('cve_list', [])
    if not cve_list:
        return

    chunk_size_raw = host.data.get('chunk_size', 20)
    try:
        chunk_size = max(1, int(chunk_size_raw))
    except (ValueError, TypeError):
        chunk_size = 20

    chunks = list(_chunked(cve_list, chunk_size))
    logger.info(f"Scanning {len(cve_list)} CVEs in {len(chunks)} chunks (size={chunk_size}) using pro api...")

    all_cve_results = {}  # title -> cve_dict (重複排除用)
    failed_chunks = 0

    for i, chunk in enumerate(chunks, 1):
        logger.info(f"  Chunk {i}/{len(chunks)}: {len(chunk)} CVEs")
        payload = json.dumps({"cves": chunk})
        res = host.run_shell_command(
            f"pro api u.pro.security.fix.cve.plan.v1 --data {shlex.quote(payload)}",
            _sudo=True,
            _sudo_password=host.data.get('sudo_password'),
            _env={"LC_ALL": "C"}
        )
        if res[0] and res[1].stdout:
            try:
                data = json.loads(res[1].stdout)
                cves = data.get('data', {}).get('attributes', {}).get('cves_data', {}).get('cves', [])
                for cve in cves:
                    title = cve.get('title')
                    if title:
                        all_cve_results[title] = cve
            except Exception as e:
                logger.warning(f"Failed to parse pro api output for chunk {i}: {e}")
                failed_chunks += 1
        else:
            logger.warning(f"pro api failed for chunk {i}: {res[1].stderr}")
            failed_chunks += 1

    if not all_cve_results and failed_chunks == len(chunks):
        logger.error("All chunks failed. Stopping further processing.")
        host.data.skip_cve_tasks = True
        return

    if failed_chunks > 0:
        logger.warning(f"{failed_chunks}/{len(chunks)} chunks failed. Partial results available.")

    host.data.cve_results = list(all_cve_results.values())


def _write_summary_csv(cve_results, path):
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

    sorted_results = sorted(cve_results, key=lambda c: c.get('title', ''))
    with open(path, "w", encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["CVE ID", "Current Status", "Expected Status", "Packages", "Action Needed"])
        for cve in sorted_results:
            writer.writerow([
                cve.get('title'),
                cve.get('current_status'),
                cve.get('expected_status'),
                ", ".join(cve.get('affected_packages') or []),
                get_action_desc(cve.get('plan') or [])
            ])


def _finalize(state, host):
    if host.data.get('skip_cve_tasks'):
        return

    cve_results = host.data.get('cve_results', [])
    csv_date = datetime.now().strftime('%Y%m%d')
    os.makedirs("output/check_cve", exist_ok=True)
    summary_path = f"output/check_cve/summary_{host.name}_{csv_date}.csv"

    # 1. Generate Summary CSV (pre-execution state)
    false_positive_raw = host.data.get('false_positive', False)
    false_positive = str(false_positive_raw).lower() in ['true', 'yes', '1', 'y']
    if false_positive:
        _FP_STATUSES = {'not-affected', 'fixed'}
        cve_results_to_write = [
            c for c in cve_results
            if c.get('current_status') == c.get('expected_status')
            and c.get('current_status') in _FP_STATUSES
        ]
        logger.info(f"false_positive filter: {len(cve_results_to_write)}/{len(cve_results)} CVEs match.")
    else:
        cve_results_to_write = cve_results
    _write_summary_csv(cve_results_to_write, summary_path)
    logger.info(f"Summary report generated at: {summary_path}")

    # 2. Prepare for Execution
    run_update_raw = host.data.get('run_update', os.getenv('RUN_UPDATE', False))
    run_update = str(run_update_raw).lower() in ['true', 'yes', '1', 'y']
    
    exclude_pro_raw = host.data.get('exclude_pro', False)
    exclude_pro = str(exclude_pro_raw).lower() in ['true', 'yes', '1', 'y']
    
    def needs_pro(plan):
        return any(p.get('operation') in ['attach', 'enable'] for p in (plan or []))
    
    patchable_cves = []
    if run_update:
        # Only execute for those still affected and having a plan
        for cve in cve_results:
            if cve.get('current_status') == 'still-affected' and cve.get('plan'):
                if exclude_pro and needs_pro(cve.get('plan', [])):
                    logger.info(f"Skipping {cve.get('title')} as it requires Ubuntu Pro and exclude_pro is set.")
                    continue
                affected = cve.get('affected_packages') or []
                if any(_is_kernel_or_nvidia(p) for p in affected):
                    logger.info(
                        f"Skipping {cve.get('title')} (kernel/nvidia package: {affected})."
                        " Use update_kernel task instead."
                    )
                    continue
                patchable_cves.append(cve.get('title'))
        
        if patchable_cves:
            logger.info(f"Found {len(patchable_cves)} patchable CVEs. Preparing execution...")
            payload = json.dumps({"cves": patchable_cves})

            # Use server.shell for better dry-run visibility
            server.shell(
                name="Execute CVE fixes via pro api",
                commands=[f"pro api u.pro.security.fix.cve.execute.v1 --data {shlex.quote(payload)}"],
                _sudo=True,
                _sudo_password=host.data.get('sudo_password'),
                _env={"LC_ALL": "C"}
            )
        else:
            logger.info("No patchable CVEs found to execute.")

    host.data.did_execute = run_update and bool(patchable_cves)

def _post_check(state, host):
    if host.data.get('skip_cve_tasks'):
        return

    run_update_raw = host.data.get('run_update', os.getenv('RUN_UPDATE', False))
    run_update = str(run_update_raw).lower() in ['true', 'yes', '1', 'y']
    if not run_update or not host.data.get('did_execute'):
        return

    cve_list = host.data.get('cve_list', [])

    chunk_size_raw = host.data.get('chunk_size', 20)
    try:
        chunk_size = max(1, int(chunk_size_raw))
    except (ValueError, TypeError):
        chunk_size = 20

    chunks = list(_chunked(cve_list, chunk_size))
    logger.info(f"[{host.name}] Post-check re-scan: {len(cve_list)} CVEs in {len(chunks)} chunks...")

    all_post_results = {}
    failed_chunks = 0

    for i, chunk in enumerate(chunks, 1):
        payload = json.dumps({"cves": chunk})
        res = host.run_shell_command(
            f"pro api u.pro.security.fix.cve.plan.v1 --data {shlex.quote(payload)}",
            _sudo=True,
            _sudo_password=host.data.get('sudo_password'),
            _env={"LC_ALL": "C"}
        )
        if res[0] and res[1].stdout:
            try:
                data = json.loads(res[1].stdout)
                cves = data.get('data', {}).get('attributes', {}).get('cves_data', {}).get('cves', [])
                for cve in cves:
                    title = cve.get('title')
                    if title:
                        all_post_results[title] = cve
            except Exception as e:
                logger.warning(f"[{host.name}] Failed to parse post-check output for chunk {i}: {e}")
                failed_chunks += 1
        else:
            logger.warning(f"[{host.name}] Post-check pro api failed for chunk {i}: {res[1].stderr}")
            failed_chunks += 1

    if not all_post_results and failed_chunks == len(chunks):
        logger.error(f"[{host.name}] Post-check re-scan failed for all chunks.")
        return

    if failed_chunks > 0:
        logger.warning(f"[{host.name}] Post-check: {failed_chunks}/{len(chunks)} chunks failed.")

    post_results = list(all_post_results.values())

    csv_date = datetime.now().strftime('%Y%m%d')
    summary_path = f"output/check_cve/summary_{host.name}_{csv_date}.csv"
    false_positive_raw = host.data.get('false_positive', False)
    false_positive = str(false_positive_raw).lower() in ['true', 'yes', '1', 'y']
    if false_positive:
        _FP_STATUSES = {'not-affected', 'fixed'}
        post_results_to_write = [
            c for c in post_results
            if c.get('current_status') == c.get('expected_status')
            and c.get('current_status') in _FP_STATUSES
        ]
        logger.info(f"[{host.name}] false_positive filter: {len(post_results_to_write)}/{len(post_results)} CVEs match.")
    else:
        post_results_to_write = post_results
    _write_summary_csv(post_results_to_write, summary_path)
    logger.info(f"[{host.name}] Post-check report updated at: {summary_path}")

    fixed = [c.get('title') for c in post_results if c.get('current_status') == 'fixed']
    still = [c.get('title') for c in post_results if c.get('current_status') == 'still-affected']
    logger.info(f"[{host.name}] Post-check: {len(fixed)} fixed, {len(still)} still-affected")
    for cve in still:
        logger.warning(f"[{host.name}] Still affected after execute: {cve}")


# Execution Flow
python.call(
    name="0.get (Fetch CVEs)",
    function=_get_cves,
    _sudo=True,
    _parallel=1  # pro cves 実行時の負荷を抑えるため、1台ずつ順番に実行
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

python.call(
    name="3.post_check (Re-scan after execute)",
    function=_post_check,
    _sudo=True
)

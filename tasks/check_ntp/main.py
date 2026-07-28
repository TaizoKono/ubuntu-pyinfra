import os
import re
import csv
import threading
from pyinfra.operations import python
from pyinfra import host, logger

_ntp_results = {}
_results_lock = threading.Lock()

_OFFSET_THRESHOLD_SEC = 1.0  # NTP Sync OK と判定するズレの許容値（秒未満）
_TIMESYNCD_OFFSET_RE = re.compile(r'^([+-]?[\d.]+)\s*(us|ms|s)$')
_CHRONY_OFFSET_RE = re.compile(r'^([\d.]+)\s+seconds\s+(fast|slow)')
_UNIT_TO_SEC = {'us': 1e-6, 'ms': 1e-3, 's': 1.0}


def _parse_offset_seconds(offset_str, ntp_service):
    if not offset_str:
        return None
    if ntp_service == 'systemd-timesyncd':
        m = _TIMESYNCD_OFFSET_RE.match(offset_str)
        if not m:
            return None
        return float(m.group(1)) * _UNIT_TO_SEC[m.group(2)]
    if ntp_service == 'chrony':
        m = _CHRONY_OFFSET_RE.match(offset_str)
        if not m:
            return None
        value = float(m.group(1))
        return -value if m.group(2) == 'slow' else value
    return None


def _write_ntp_csv():
    os.makedirs("output/check_ntp", exist_ok=True)
    try:
        with open("output/check_ntp/ntp_status.csv", "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(
                ["hostname", "status", "synchronized", "ntp_service", "offset_sec", "timezone", "local_time"]
            )
            for h, d in sorted(_ntp_results.items()):
                writer.writerow([
                    h, d['status'], d['synchronized'], d['ntp_service'],
                    d['offset_sec'], d['timezone'], d['local_time'],
                ])
    except Exception as e:
        logger.error(f"Failed to write ntp_status.csv: {e}")


def _check_ntp(state, host):
    ok, res = host.run_shell_command(
        "timedatectl show -p NTPSynchronized -p TimezoneName --value",
        _env={"LC_ALL": "C"},
    )
    if not ok:
        raise Exception(f"[{host.name}] Failed to run timedatectl")
    lines = res.stdout.strip().splitlines()
    synchronized = lines[0].strip() if len(lines) > 0 else "unknown"
    timezone = lines[1].strip() if len(lines) > 1 else "unknown"

    ok2, res2 = host.run_shell_command("date '+%Y-%m-%d %H:%M:%S %Z'", _env={"LC_ALL": "C"})
    local_time = res2.stdout.strip() if ok2 else "unknown"

    # chrony優先。無ければ systemd-timesyncd の offset を確認する
    offset_sec = ""
    ntp_service = "unknown"
    ok3, res3 = host.run_shell_command("command -v chronyc", _env={"LC_ALL": "C"})
    if ok3 and res3.stdout.strip():
        ntp_service = "chrony"
        ok4, res4 = host.run_shell_command(
            "chronyc tracking 2>/dev/null | awk -F': ' '/System time/{print $2}'",
            _env={"LC_ALL": "C"},
        )
        if ok4 and res4.stdout.strip():
            offset_sec = res4.stdout.strip()
    else:
        ok5, res5 = host.run_shell_command(
            "timedatectl timesync-status 2>/dev/null | awk -F': ' '/Offset/{print $2}'",
            _env={"LC_ALL": "C"},
        )
        if ok5 and res5.stdout.strip():
            ntp_service = "systemd-timesyncd"
            offset_sec = res5.stdout.strip()

    offset_seconds = _parse_offset_seconds(offset_sec, ntp_service)
    if offset_seconds is not None:
        sync_ok = abs(offset_seconds) < _OFFSET_THRESHOLD_SEC
    else:
        # オフセットが取得できない環境では synchronized フラグにフォールバック
        sync_ok = synchronized == "yes"

    status = "NTP Sync OK" if sync_ok else "NTP Sync NG"
    if sync_ok:
        logger.info(f"[{host.name}] {status} (service={ntp_service}, offset={offset_sec or 'n/a'})")
    else:
        logger.warning(f"[{host.name}] {status} (service={ntp_service}, offset={offset_sec or 'unknown'})")

    with _results_lock:
        _ntp_results[host.name] = {
            'status': status,
            'synchronized': synchronized,
            'ntp_service': ntp_service,
            'offset_sec': offset_sec,
            'timezone': timezone,
            'local_time': local_time,
        }
        _write_ntp_csv()


python.call(
    name="0.check_ntp (Verify NTP time synchronization)",
    function=_check_ntp,
)

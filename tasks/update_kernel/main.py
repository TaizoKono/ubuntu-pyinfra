import os
import re
import csv
import threading
from pyinfra.operations import python, server
from pyinfra import host, logger


def _validate_nvidia_driver_param(value):
    """nvidia_driver パラメータが数字のみ（例: 535, 570）であることを検証する。"""
    if value is not None and not re.fullmatch(r'[0-9]{2,4}', str(value)):
        raise ValueError(
            f"Invalid nvidia_driver value: {value!r}. "
            "Specify a numeric major version only (e.g. --data nvidia_driver=535)."
        )

_kernel_results = {}
_results_lock = threading.Lock()


def _write_kernel_csv():
    os.makedirs("output/update_kernel", exist_ok=True)
    try:
        with open("output/update_kernel/kernel_current.csv", "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["hostname", "before", "after", "status", "driver_before", "driver_after", "driver_status"])
            for h, d in sorted(_kernel_results.items()):
                writer.writerow([
                    h,
                    d['before'], d['after'], d['status'],
                    d.get('driver_before', ''), d.get('driver_after', ''), d.get('driver_status', ''),
                ])
    except Exception as e:
        logger.error(f"Failed to write kernel_current.csv: {e}")


# Module-level: get current/planned kernel and driver for dry-run visibility
_ok, _res = host.run_shell_command("uname -r", _env={"LC_ALL": "C"})
_current = _res.stdout.strip() if _ok else "(unknown)"
logger.info(f"[{host.name}] Current kernel: {_current}")

_ok_p, _res_p = host.run_shell_command(
    "meta=$(dpkg-query -W -f='${Package}\\n' 'linux-image-generic-hwe-*' 2>/dev/null"
    " | sort -V | tail -1);"
    " [ -z \"$meta\" ] && meta=linux-image-generic;"
    " apt-cache depends \"$meta\" 2>/dev/null"
    " | awk '/Depends:/ && /linux-image-[0-9]/{print $2}'",
    _env={"LC_ALL": "C"},
)
_planned_pkg = _res_p.stdout.strip() if _ok_p else ""
_planned_kernel = _planned_pkg.replace("linux-image-", "") if _planned_pkg else "(unavailable)"
if _planned_kernel == _current:
    logger.info(f"[{host.name}] Planned kernel: {_planned_kernel} (already up to date)")
else:
    logger.info(f"[{host.name}] Planned kernel: {_planned_kernel}")

if host.data.get('is_gpu'):
    # $() サブシェルで stdout を捕捉することで、失敗時に nvidia-smi のエラー出力が
    # 混入するのを防ぐ（|| だけでは失敗したコマンドの stdout も出力される）
    _ok2, _res2 = host.run_shell_command(
        'ver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null)'
        ' && printf "%s" "$ver" || echo "(no driver)"',
        _env={"LC_ALL": "C"},
    )
    _drv = _res2.stdout.strip() if _ok2 else "(unknown)"
    logger.info(f"[{host.name}] Current Nvidia driver: {_drv}")

    # メジャーバージョン比較には dpkg を使う（NVML が壊れていても確実に取得できる）
    _ok_m, _res_m = host.run_shell_command(
        "dpkg-query -W -f='${Package}\\n' 'nvidia-driver-[0-9]*' 2>/dev/null"
        " | grep -oP '(?<=nvidia-driver-)\\d+' | sort -V | tail -1",
        _env={"LC_ALL": "C"},
    )
    _current_major = _res_m.stdout.strip() if (_ok_m and _res_m.stdout.strip()) else ""

    _nvidia_driver_param = host.data.get('nvidia_driver')
    if _nvidia_driver_param:
        _validate_nvidia_driver_param(_nvidia_driver_param)
        _ok3, _res3 = host.run_shell_command(
            f"apt-cache policy nvidia-driver-{_nvidia_driver_param} 2>/dev/null"
            " | awk '/Candidate:/{print $2}'",
            _env={"LC_ALL": "C"},
        )
        _planned_drv_ver = _res3.stdout.strip() if (_ok3 and _res3.stdout.strip()) else "(unavailable)"
        logger.info(f"[{host.name}] Planned Nvidia driver: nvidia-driver-{_nvidia_driver_param} ({_planned_drv_ver})")
        if _current_major and _current_major != str(_nvidia_driver_param):
            logger.warning(
                f"[{host.name}] WARNING: Nvidia driver major version will change:"
                f" {_current_major} -> {_nvidia_driver_param}"
            )
    else:
        _ok3, _res3 = host.run_shell_command(
            "ubuntu-drivers devices 2>/dev/null"
            " | awk '/recommended/{for(i=1;i<=NF;i++) if($i~/nvidia-driver-[0-9]/) print $i}'"
            " | head -1",
            _env={"LC_ALL": "C"},
        )
        _planned_drv = _res3.stdout.strip() if (_ok3 and _res3.stdout.strip()) else "(unavailable)"
        logger.info(f"[{host.name}] Planned Nvidia driver: {_planned_drv}")


def _cleanup_stale_askpass(state, host):
    # 過去の実行がタイムアウトやSSH切断等で異常終了すると、pyinfraが
    # sudo用に生成する一時askpassスクリプトが /tmp に残存することがある。
    # 残存ファイルが後続実行のsudo呼び出しと衝突し
    # 「Exec format error」を引き起こすことがあるため、実行の最初に掃除する。
    ok, res = host.run_shell_command(
        "find /tmp -maxdepth 1 -name 'pyinfra-sudo-askpass-*' -type f",
        _env={"LC_ALL": "C"},
    )
    stale_files = [line for line in (res.stdout or "").splitlines() if line.strip()]
    if not stale_files:
        return

    logger.warning(
        f"[{host.name}] Removing {len(stale_files)} stale sudo askpass file(s) left over from a previous run: {stale_files}"
    )
    host.run_shell_command(
        "find /tmp -maxdepth 1 -name 'pyinfra-sudo-askpass-*' -type f -delete",
        _env={"LC_ALL": "C"},
    )


def _pre_check(state, host):
    ok, res = host.run_shell_command("uname -r", _env={"LC_ALL": "C"})
    if not ok:
        raise Exception(f"[{host.name}] Failed to get current kernel version")
    current_kernel = res.stdout.strip()

    logger.info(f"[{host.name}] Current kernel: {current_kernel}")
    host.data.before_kernel = current_kernel

    ok, res = host.run_shell_command(
        "dpkg -l | grep 'linux-image-' | grep '^ii'",
        _env={"LC_ALL": "C"},
    )
    if ok and res.stdout.strip():
        logger.info(f"[{host.name}] Installed kernels:")
        for line in res.stdout.strip().splitlines():
            logger.info(f"[{host.name}]   {line}")

    # HWE メタパッケージが存在する場合はそちらを使う
    ok_hwe, res_hwe = host.run_shell_command(
        "dpkg-query -W -f='${Package}\\n' 'linux-image-generic-hwe-*' 2>/dev/null"
        " | sort -V | tail -1",
        _env={"LC_ALL": "C"},
    )
    hwe_meta = res_hwe.stdout.strip() if (ok_hwe and res_hwe.stdout.strip()) else ""
    if hwe_meta:
        meta_image = hwe_meta
        meta_headers = hwe_meta.replace("linux-image-", "linux-headers-")
        logger.info(f"[{host.name}] Kernel series: HWE ({meta_image})")
    else:
        meta_image = "linux-image-generic"
        meta_headers = "linux-headers-generic"
        logger.info(f"[{host.name}] Kernel series: GA ({meta_image})")
    host.data.kernel_meta_image = meta_image
    host.data.kernel_meta_headers = meta_headers

    if host.data.get('is_gpu'):
        ok, res = host.run_shell_command(
            'ver=$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null)'
            ' && printf "%s" "$ver" || true',
            _env={"LC_ALL": "C"},
        )
        if ok and res.stdout.strip():
            logger.info(f"[{host.name}] Current Nvidia GPU info:")
            for line in res.stdout.strip().splitlines():
                logger.info(f"[{host.name}]   {line}")
            host.data.before_driver = res.stdout.strip().split(',')[-1].strip()
        else:
            logger.info(f"[{host.name}] nvidia-smi unavailable (NVML error or no driver).")
            host.data.before_driver = "(no driver)"

        # メジャーバージョン比較用・再起動判定用: dpkg から取得（NVML 不要）
        ok_m, res_m = host.run_shell_command(
            "dpkg-query -W -f='${Package}\\n' 'nvidia-driver-[0-9]*' 2>/dev/null"
            " | grep -oP '(?<=nvidia-driver-)\\d+' | sort -V | tail -1",
            _env={"LC_ALL": "C"},
        )
        host.data.before_driver_major = res_m.stdout.strip() if (ok_m and res_m.stdout.strip()) else ""

        # インストール前の完全バージョン文字列を記録（インストール後と比較して再起動要否を判定）
        ok_dpkg, res_dpkg = host.run_shell_command(
            "dpkg-query -W -f='${Package} ${Version}\\n' 'nvidia-driver-[0-9]*' 2>/dev/null"
            " | grep -v '^$' | sort -V | tail -1",
            _env={"LC_ALL": "C"},
        )
        host.data.before_driver_dpkg = res_dpkg.stdout.strip() if ok_dpkg else ""


def _install(state, host):
    meta_image = host.data.get('kernel_meta_image', 'linux-image-generic')
    meta_headers = host.data.get('kernel_meta_headers', 'linux-headers-generic')
    server.shell(
        name=f"Install latest kernel via {meta_image}",
        commands=[
            "apt-get update || true",
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y {meta_image} {meta_headers}",
            "update-grub",
        ],
        _sudo=True,
        _sudo_password=host.data.get('sudo_password'),
        _env={"LC_ALL": "C"},
    )

    # /var/run/reboot-required フラグの確認
    ok, res = host.run_shell_command(
        "test -f /var/run/reboot-required && echo 'yes' || echo 'no'"
    )
    reboot_required_flag = ok and res.stdout.strip() == 'yes'

    # インストール済み最新カーネルと実行中カーネルの比較
    # (apt-get install が no-op だった場合 /var/run/reboot-required は作成されないため)
    # grep -v でプレフィックスマッチ: linux-image-generic と linux-image-generic-hwe-* の
    # 両メタパッケージを除外し、バージョン付きバイナリパッケージのみ残す
    ok2, res2 = host.run_shell_command(
        "dpkg -l 'linux-image-*-generic' | awk '/^ii/{print $2}'"
        " | grep -v '^linux-image-generic' | sort -V | tail -1 | sed 's/linux-image-//'",
        _env={"LC_ALL": "C"},
    )
    latest_installed = res2.stdout.strip() if ok2 else ""

    ok3, res3 = host.run_shell_command("uname -r", _env={"LC_ALL": "C"})
    running_kernel = res3.stdout.strip() if ok3 else ""

    needs_reboot = reboot_required_flag or (
        bool(latest_installed) and latest_installed != running_kernel
    )

    if needs_reboot:
        if not reboot_required_flag and latest_installed != running_kernel:
            logger.info(
                f"[{host.name}] Newer kernel {latest_installed} is installed "
                f"but not running ({running_kernel}). Reboot required."
            )
        host.data.skip_reboot = False
    else:
        logger.info(f"[{host.name}] Kernel is already up to date. No reboot required.")
        host.data.skip_reboot = True


def _nvidia_install(state, host):
    if not host.data.get('is_gpu'):
        return

    nvidia_driver_param = host.data.get('nvidia_driver')
    _validate_nvidia_driver_param(nvidia_driver_param)

    # メジャーバージョン変更の警告（dpkg ベースで比較。NVML 不要）
    before_driver_major = host.data.get('before_driver_major', '')
    if nvidia_driver_param and before_driver_major and before_driver_major != str(nvidia_driver_param):
        logger.warning(
            f"[{host.name}] WARNING: Nvidia driver major version will change:"
            f" {before_driver_major} -> {nvidia_driver_param}"
        )

    if nvidia_driver_param:
        commands = [
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-driver-{nvidia_driver_param}",
        ]
        op_name = f"Install Nvidia driver nvidia-driver-{nvidia_driver_param} via apt"
    else:
        commands = [
            "DEBIAN_FRONTEND=noninteractive apt-get install -y ubuntu-drivers-common",
            "ubuntu-drivers autoinstall",
        ]
        op_name = "Install/update Nvidia driver via ubuntu-drivers"

    # update-initramfs を明示実行して initramfs にドライバモジュールを確実に反映させる。
    # apt の postinst が呼ばれない場合でもバージョンミスマッチを防ぐ。
    commands = commands + ["update-initramfs -u -k all"]

    server.shell(
        name=op_name,
        commands=commands,
        _sudo=True,
        _sudo_password=host.data.get('sudo_password'),
        _env={"LC_ALL": "C"},
    )

    # インストール後の dpkg バージョンを取得してインストール前後を比較
    ok_after, res_after = host.run_shell_command(
        "dpkg-query -W -f='${Package} ${Version}\\n' 'nvidia-driver-[0-9]*' 2>/dev/null"
        " | grep -v '^$' | sort -V | tail -1",
        _env={"LC_ALL": "C"},
    )
    after_driver_dpkg = res_after.stdout.strip() if ok_after else ""
    before_driver_dpkg = host.data.get('before_driver_dpkg', '')

    ok_rb, res_rb = host.run_shell_command(
        "test -f /var/run/reboot-required && echo 'yes' || echo 'no'"
    )
    reboot_flag = ok_rb and res_rb.stdout.strip() == 'yes'

    # /var/run/reboot-required フラグ OR dpkg バージョン変化のどちらかで再起動。
    # nvidia ドライバは apt が reboot-required を設定しないケースがあるため
    # dpkg バージョン比較を主判定とする。
    driver_changed = bool(after_driver_dpkg) and after_driver_dpkg != before_driver_dpkg
    if reboot_flag or driver_changed:
        host.data.skip_reboot = False
        if driver_changed:
            logger.info(
                f"[{host.name}] Nvidia driver changed"
                f" ({before_driver_dpkg} -> {after_driver_dpkg}). Reboot required."
            )
    else:
        logger.info(f"[{host.name}] Nvidia driver is already up to date. No reboot required.")


def _reboot(state, host):
    if host.data.get('skip_reboot'):
        return

    import time

    logger.info(f"[{host.name}] Initiating reboot...")
    # Use host.run_shell_command instead of server.reboot() because server.reboot()
    # clears askpass files before running reboot, causing sudo auth to fail.
    try:
        host.run_shell_command(
            "reboot",
            _sudo=True,
            _sudo_password=host.data.get('sudo_password'),
            _env={"LC_ALL": "C"},
        )
    except Exception:
        pass  # Connection drop after reboot is expected

    # シャットダウンが完全に開始するのを待ってから disconnect する。
    # 短すぎると旧 SSH セッションへの誤接続が起きるため 30s 待つ。
    time.sleep(30)
    host.connector_data["sudo_askpass_path"] = None
    host.connector_data["su_askpass_path"] = None
    host.disconnect()
    logger.info(f"[{host.name}] Reboot initiated. post_check will wait for reconnection.")


def _post_check(state, host):
    import time

    if not host.data.get('skip_reboot'):
        reboot_timeout = 300
        interval = 10
        max_retries = reboot_timeout // interval

        logger.info(f"[{host.name}] Waiting for server to come back online...")
        reconnected = False
        for retry in range(max_retries + 1):
            host.connect(show_errors=False)
            if host.connected:
                elapsed = 30 + retry * interval
                logger.info(f"[{host.name}] Server back online (~{elapsed}s)")
                reconnected = True
                break
            time.sleep(interval)

        if not reconnected:
            raise Exception(
                f"[{host.name}] Server did not come back online within {30 + reboot_timeout}s after reboot. "
                "Please check the server console."
            )

    ok, res = host.run_shell_command("uname -r", _env={"LC_ALL": "C"})
    current = res.stdout.strip() if ok else "(unknown)"

    logger.info(f"[{host.name}] Kernel after update: {current}")
    before = host.data.get('before_kernel', '(unknown)')
    kernel_status = "updated" if before != current else "no_change"
    logger.info(f"[{host.name}] Kernel status: {kernel_status} ({before} -> {current})")

    driver_before = ""
    driver_after = ""
    driver_status = ""

    if host.data.get('is_gpu'):
        ok, res = host.run_shell_command(
            "nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null",
            _env={"LC_ALL": "C"},
        )
        if ok and res.stdout.strip():
            logger.info(f"[{host.name}] Nvidia GPU info after update:")
            for line in res.stdout.strip().splitlines():
                logger.info(f"[{host.name}]   {line}")
            driver_after = res.stdout.strip().split(',')[-1].strip()
        else:
            logger.warning(f"[{host.name}] nvidia-smi failed after update. Driver may not be loaded.")
            driver_after = "(unavailable)"

        driver_before = host.data.get('before_driver', '(unknown)')
        driver_status = "updated" if driver_before != driver_after else "no_change"
        logger.info(f"[{host.name}] Driver status: {driver_status} ({driver_before} -> {driver_after})")

    with _results_lock:
        _kernel_results[host.name] = {
            'before': before,
            'after': current,
            'status': kernel_status,
            'driver_before': driver_before,
            'driver_after': driver_after,
            'driver_status': driver_status,
        }
        _write_kernel_csv()

    ok, res = host.run_shell_command(
        "dpkg -l | grep 'linux-image-' | grep '^ii'", _env={"LC_ALL": "C"},
    )
    if ok and res.stdout.strip():
        logger.info(f"[{host.name}] Installed kernels after update:")
        for line in res.stdout.strip().splitlines():
            logger.info(f"[{host.name}]   {line}")

    ok, res = host.run_shell_command("test -f /var/run/reboot-required && echo 'yes' || echo 'no'")
    reboot_required = res.stdout.strip() == 'yes'
    logger.info(f"[{host.name}] Reboot required: {reboot_required}")

    ok, res = host.run_shell_command(
        "dmesg | grep -iE 'error|fail' | tail -20", _env={"LC_ALL": "C"},
    )
    if ok and res.stdout.strip():
        logger.warning(f"[{host.name}] Kernel error/fail logs:")
        for line in res.stdout.strip().splitlines():
            logger.warning(f"[{host.name}]   {line}")
    else:
        logger.info(f"[{host.name}] No kernel error/fail logs detected")


python.call(
    name="0.cleanup_askpass (Remove stale sudo askpass files)",
    function=_cleanup_stale_askpass,
)

python.call(
    name="1.pre_check (Check current kernel and Nvidia driver)",
    function=_pre_check,
)

python.call(
    name="2.install (Install latest kernel via generic metapackages)",
    function=_install,
    _sudo=True,
)

python.call(
    name="3.nvidia_install (Update Nvidia driver via ubuntu-drivers)",
    function=_nvidia_install,
    _sudo=True,
)

python.call(
    name="4.reboot (Reboot to apply kernel and driver)",
    function=_reboot,
)

python.call(
    name="5.post_check (Verify kernel and Nvidia driver)",
    function=_post_check,
)

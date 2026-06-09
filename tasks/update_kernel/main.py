import os
import csv
import re
import shlex
from pyinfra.operations import python, server
from pyinfra import host, logger


def _load_targets_csv(csv_path: str) -> dict:
    """Load hostname -> kernel_version mapping from CSV file."""
    targets = {}
    if not os.path.exists(csv_path):
        return targets
    try:
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or row[0].startswith('#'):
                    continue
                if len(row) >= 2:
                    targets[row[0].strip()] = row[1].strip()
    except Exception as e:
        logger.warning(f"Failed to load targets.csv: {e}")
    return targets


def _validate_kernel_version(kernel_version: str) -> str:
    """Validate kernel version format to prevent command injection."""
    if not kernel_version or not isinstance(kernel_version, str):
        raise ValueError(f"Invalid kernel version: {kernel_version!r}")
    # Allow alphanumeric, dot, hyphen, plus (standard kernel version pattern)
    if not re.fullmatch(r'[A-Za-z0-9._+-]+', kernel_version):
        raise ValueError(f"Invalid kernel version format: {kernel_version!r}")
    return kernel_version


def _resolve_target_kernel(hostname: str, cli_kernel: str | None = None) -> str | None:
    """Resolve target kernel version: CLI > targets.csv."""
    if cli_kernel:
        return _validate_kernel_version(cli_kernel)
    targets = _load_targets_csv("files/kernel/targets.csv")
    target = targets.get(hostname)
    if target:
        return _validate_kernel_version(target)
    return None


# Module-level: resolve targets and get current kernel for dry-run visibility
_cli_kernel = host.data.get('kernel')
_target_kernel = _resolve_target_kernel(host.name, _cli_kernel)

if _target_kernel:
    # Current kernel (SSH: works even in --dry-run since we're already connected)
    _ok, _res = host.run_shell_command("uname -r", _env={"LC_ALL": "C"})
    _current = _res.stdout.strip() if _ok else "(unknown)"

    if _current == _target_kernel:
        logger.info(f"[{host.name}] Current: {_current} == Target: {_target_kernel} → no update needed")
    else:
        logger.info(f"[{host.name}] Current: {_current} → Target: {_target_kernel} (update needed)")
else:
    logger.warning(f"[{host.name}] No target kernel specified (use --data kernel=... or files/kernel/targets.csv)")


def _pre_check(state, host):
    target_kernel = _resolve_target_kernel(host.name, host.data.get('kernel'))
    if not target_kernel:
        raise ValueError(
            f"[{host.name}] No target kernel specified. "
            "Use --data kernel=<version> or configure files/kernel/targets.csv"
        )

    # Current kernel
    ok, res = host.run_shell_command("uname -r", _env={"LC_ALL": "C"})
    if not ok:
        raise Exception(f"[{host.name}] Failed to get current kernel version")
    current_kernel = res.stdout.strip()

    logger.info(f"[{host.name}] Current kernel: {current_kernel}")

    # Installed kernels
    ok, res = host.run_shell_command(
        "dpkg -l | grep 'linux-image-' | grep '^ii'",
        _env={"LC_ALL": "C"},
    )
    if ok and res.stdout.strip():
        logger.info(f"[{host.name}] Installed kernels:")
        for line in res.stdout.strip().splitlines():
            logger.info(f"[{host.name}]   {line}")

    # Skip if already running target kernel
    if current_kernel == target_kernel:
        logger.info(f"[{host.name}] Already running target kernel {target_kernel}. Skipping update.")
        host.data.skip_kernel_update = True
        return

    host.data.target_kernel = target_kernel
    host.data.skip_kernel_update = False


def _install(state, host):
    if host.data.get('skip_kernel_update'):
        return

    target_kernel = host.data.get('target_kernel')
    if not target_kernel:
        raise Exception(f"[{host.name}] target_kernel not set; did _pre_check run?")

    # Build package names with shell escaping
    image_pkg = shlex.quote(f'linux-image-{target_kernel}')
    headers_pkg = shlex.quote(f'linux-headers-{target_kernel}')

    server.shell(
        name=f"Install kernel {target_kernel}",
        commands=[
            "apt-get update || true",
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y {image_pkg} {headers_pkg}",
            "update-grub",
        ],
        _sudo=True,
        _sudo_password=host.data.get('sudo_password'),
        _env={"LC_ALL": "C"},
    )


def _reboot(state, host):
    if host.data.get('skip_kernel_update'):
        return

    server.reboot(
        name="Reboot to apply new kernel",
        delay=3,
        timeout=300,
        interval=5,
        _sudo=True,
        _sudo_password=host.data.get('sudo_password'),
    )


def _post_check(state, host):
    if host.data.get('skip_kernel_update'):
        return

    target_kernel = host.data.get('target_kernel')

    # Current kernel after reboot
    ok, res = host.run_shell_command("uname -r", _env={"LC_ALL": "C"})
    current = res.stdout.strip() if ok else "(unknown)"

    logger.info(f"[{host.name}] Kernel after reboot: {current}")
    if current != target_kernel:
        logger.warning(f"[{host.name}] Expected {target_kernel}, but running {current}")

    # Installed kernels
    ok, res = host.run_shell_command(
        "dpkg -l | grep 'linux-image-' | grep '^ii'",
        _env={"LC_ALL": "C"},
    )
    if ok and res.stdout.strip():
        logger.info(f"[{host.name}] Installed kernels after update:")
        for line in res.stdout.strip().splitlines():
            logger.info(f"[{host.name}]   {line}")

    # Reboot required flag
    ok, res = host.run_shell_command("test -f /var/run/reboot-required && echo 'yes' || echo 'no'")
    reboot_required = res.stdout.strip() == 'yes'
    logger.info(f"[{host.name}] Reboot required: {reboot_required}")

    # Kernel error log
    ok, res = host.run_shell_command(
        "dmesg | grep -iE 'error|fail' | tail -20",
        _env={"LC_ALL": "C"},
    )
    if ok and res.stdout.strip():
        logger.warning(f"[{host.name}] Kernel error/fail logs:")
        for line in res.stdout.strip().splitlines():
            logger.warning(f"[{host.name}]   {line}")
    else:
        logger.info(f"[{host.name}] No kernel error/fail logs detected")


python.call(
    name="0.pre_check (Check current kernel and resolve target)",
    function=_pre_check,
)

python.call(
    name="1.install (Install target kernel)",
    function=_install,
    _sudo=True,
)

python.call(
    name="2.reboot (Reboot to apply kernel)",
    function=_reboot,
    _sudo=True,
)

python.call(
    name="3.post_check (Verify kernel and check errors)",
    function=_post_check,
)

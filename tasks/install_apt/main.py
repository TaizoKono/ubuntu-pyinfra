from pyinfra.operations import python, server
from pyinfra import host, logger

# Runs during "Preparing operation files" phase — before confirmation prompt and in --dry-run.
_pkg_param = host.data.get('pkg', '')
if _pkg_param:
    logger.info(f"[{host.name}] apt packages to install: {_pkg_param}")
else:
    logger.warning(f"[{host.name}] Required parameter 'pkg' not provided. Use --data pkg=<name>")


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


def _install(state, host):
    pkg_raw = host.data.get('pkg')
    if not pkg_raw:
        raise ValueError("Required parameter 'pkg' not provided. Use --data pkg=<package-name>")

    packages = [p.strip() for p in str(pkg_raw).split(',') if p.strip()]

    # Idempotency check: filter out already-installed packages
    to_install = []
    for pkg in packages:
        ok, res = host.run_shell_command(
            f"dpkg-query -W -f='${{Status}}' {pkg} 2>/dev/null",
            _env={"LC_ALL": "C"},
        )
        if ok and 'install ok installed' in res.stdout:
            logger.info(f"[{host.name}] {pkg} already installed. Skipping.")
        else:
            to_install.append(pkg)

    if not to_install:
        return

    server.shell(
        name=f"Install {', '.join(to_install)}",
        commands=[
            "apt-get update || true",
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y {' '.join(to_install)}",
        ],
        _sudo=True,
        _sudo_password=host.data.get('sudo_password'),
        _env={"LC_ALL": "C"},
    )


python.call(
    name="0.cleanup_askpass (Remove stale sudo askpass files)",
    function=_cleanup_stale_askpass,
)

python.call(
    name="1.install (apt install packages)",
    function=_install,
    _sudo=True,
)

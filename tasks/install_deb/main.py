import os
from pyinfra.operations import python, server, files
from pyinfra import host, logger

# Runs during "Preparing operation files" phase — before confirmation prompt and in --dry-run.
# Local filesystem scan only (no SSH), so it works regardless of execution mode.
_deb_param = host.data.get('deb', '')
if _deb_param:
    _lines = []
    for _d in sorted(os.listdir("files/downloads")):
        _dp = f"files/downloads/{_d}"
        if not os.path.isdir(_dp):
            continue
        _match = next(
            (_f for _f in sorted(os.listdir(_dp))
             if _f.endswith(".deb") and _deb_param.lower() in _f.lower()),
            None
        )
        if _match:
            _suffix = " (fallback)" if _d == "common" else ""
            _lines.append(f"  {_d}: {_match}{_suffix}")
        else:
            _lines.append(f"  {_d}: (no match)")
    if _lines:
        logger.info(f"[{host.name}] deb candidates for '{_deb_param}':")
        for _line in _lines:
            logger.info(f"[{host.name}] {_line}")
    else:
        logger.warning(f"[{host.name}] No version directories found under files/downloads/")


def _find_deb_file(deb_param: str, ubuntu_version: str) -> str | None:
    for search_dir in [f"files/downloads/{ubuntu_version}", "files/downloads/common"]:
        if not os.path.isdir(search_dir):
            continue
        for filename in os.listdir(search_dir):
            if filename.endswith(".deb") and deb_param.lower() in filename.lower():
                return os.path.join(search_dir, filename)
    return None


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


def _detect_and_resolve(state, host):
    deb_param = host.data.get('deb')
    if not deb_param:
        raise ValueError("Required parameter 'deb' not provided. Use --data deb=<package-name>")

    success, result = host.run_shell_command("lsb_release -rs", _env={"LC_ALL": "C"})
    if not success:
        raise Exception(f"Failed to detect Ubuntu version on {host.name}: {result.stderr}")

    ubuntu_version = result.stdout.strip()
    logger.info(f"[{host.name}] Detected Ubuntu {ubuntu_version}")

    local_file = _find_deb_file(deb_param, ubuntu_version)
    if local_file is None:
        raise FileNotFoundError(
            f"[{host.name}] No .deb file matching '{deb_param}' found in "
            f"files/downloads/{ubuntu_version}/ or files/downloads/common/"
        )

    host.data.ubuntu_version = ubuntu_version
    host.data.local_deb_path = local_file
    host.data.remote_deb_filename = os.path.basename(local_file)
    logger.info(f"[{host.name}] Resolved deb: {local_file}")


def _upload(state, host):
    local_path = host.data.get('local_deb_path')
    if not local_path:
        raise Exception(f"[{host.name}] No local_deb_path set; did detect stage run?")

    remote_tmp = host.data.get('remote_tmp', '/tmp')
    remote_path = f"{remote_tmp.rstrip('/')}/{host.data.remote_deb_filename}"
    host.data.remote_deb_path = remote_path

    files.put(
        name=f"Upload {host.data.remote_deb_filename}",
        src=local_path,
        dest=remote_path,
        _sudo=True,
        _sudo_password=host.data.get('sudo_password'),
        add_deploy_dir=True,
    )


def _install(state, host):
    remote_path = host.data.get('remote_deb_path')
    if not remote_path:
        raise Exception(f"[{host.name}] No remote_deb_path set; did upload stage run?")

    # Idempotency check: skip install if exact version is already installed
    ok, res = host.run_shell_command(
        f"dpkg-deb --field {remote_path} Package Version",
        _sudo=True,
        _sudo_password=host.data.get('sudo_password'),
        _env={"LC_ALL": "C"},
    )
    if ok and res.stdout.strip():
        fields = {}
        for line in res.stdout.strip().splitlines():
            if ': ' in line:
                k, v = line.split(': ', 1)
                fields[k.strip()] = v.strip()
        pkg_name = fields.get('Package', '')
        pkg_version = fields.get('Version', '')
        if pkg_name and pkg_version:
            ok2, res2 = host.run_shell_command(
                f"dpkg-query -W -f='${{Version}}' {pkg_name} 2>/dev/null",
                _env={"LC_ALL": "C"},
            )
            if ok2 and res2.stdout.strip() == pkg_version:
                logger.info(f"[{host.name}] {pkg_name} {pkg_version} already installed. Skipping.")
                return

    server.shell(
        name=f"Install {host.data.remote_deb_filename}",
        commands=[
            f"DEBIAN_FRONTEND=noninteractive dpkg --force-confdef --force-confold -i {remote_path} 2>/dev/null || true",
            "DEBIAN_FRONTEND=noninteractive apt-get install -f -y",
            f"DEBIAN_FRONTEND=noninteractive dpkg --force-confdef --force-confold -i {remote_path}",
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
    name="1.detect (Detect Ubuntu version and resolve deb)",
    function=_detect_and_resolve,
)

python.call(
    name="2.upload (Upload deb to remote)",
    function=_upload,
    _sudo=True,
)

python.call(
    name="3.install (Install deb package)",
    function=_install,
    _sudo=True,
)

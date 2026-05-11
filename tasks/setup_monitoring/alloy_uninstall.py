from pyinfra import host
from pyinfra.operations import apt, systemd

# Stop and disable Alloy service
systemd.service(
    name="Stop and disable Alloy service",
    service="alloy.service",
    running=False,
    enabled=False,
    sudo=True,
    ignore_errors=True,
)

# Uninstall Alloy package
apt.packages(
    name="Uninstall Alloy package",
    packages=["alloy"],
    present=False,
    sudo=True,
)

import getpass
from pyinfra.api import Config

# This runs once when inventory is loaded
sudo_password = getpass.getpass("Enter sudo password: ")

target = [
    ("@local", {"sudo_password": sudo_password}),
]

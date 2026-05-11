from pyinfra import local

# You can uncomment the uninstall task if needed
# local.include("tasks/setup_monitoring/alloy_uninstall.py")

local.include("tasks/setup_monitoring/alloy.py")

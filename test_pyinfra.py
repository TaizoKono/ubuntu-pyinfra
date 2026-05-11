from pyinfra import host
from pyinfra.operations import python

def test_fn(state, host):
    res = host.run_shell_command("echo hello", _sudo=True)
    print("RES:", res)

python.call(name="test", function=test_fn, _sudo=True)

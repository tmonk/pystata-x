import sys, platform
_IS_X86_64_QEMU = sys.platform in ("linux", "linux2") and platform.machine() != "aarch64"
print(f"sys.platform={sys.platform} machine={platform.machine()} _IS_X86_64_QEMU={_IS_X86_64_QEMU}")

# Simulate what pytest does
import pytest
@pytest.mark.skipif(_IS_X86_64_QEMU, reason="test skip")
def test_func():
    assert False, "should not run"

# Collect
import _pytest.config
import _pytest.main

# Simplest test: just call test_func's underlying function via pytest
if _IS_X86_64_QEMU:
    # Test should be skipped at collection time
    import _pytest.mark.structures
    marker = pytest.mark.skipif(_IS_X86_64_QEMU, reason="test skip")
    print(f"skipif marker: {marker}")
    print(f"condition: {_IS_X86_64_QEMU}")
    print("If condition is True, pytest will skip the test at collection time")
else:
    print("Condition is False, test will run")

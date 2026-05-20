import sys, platform
_IS_X86_64_QEMU = sys.platform in ("linux", "linux2") and platform.machine() != "aarch64"
print(f"_IS_X86_64_QEMU = {_IS_X86_64_QEMU}")

import pytest
@pytest.mark.skipif(_IS_X86_64_QEMU, reason="test")
def test_me():
    assert False

print("test_me has skipif:", pytest.mark.skipif in getattr(test_me, 'pytestmark', []))

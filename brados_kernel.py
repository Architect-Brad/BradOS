# brados_kernel.py — BradOS Kernel Shim
#
# Backward-compat re-export. The real kernel lives in brados_kernel_core.py.
# Breaking nothing since v1.

from brados_kernel_core import *           # noqa: F401, F403
from brados_kernel_core import BradOSKernel, hash_password, verify_password  # explicit re-export

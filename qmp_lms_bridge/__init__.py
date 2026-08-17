__version__ = "0.1.0"

from . import vendor_patches as _vendor_patches

_vendor_patches.apply()

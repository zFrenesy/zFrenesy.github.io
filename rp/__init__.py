"""we-solve research platform package.

Named ``rp`` because ``platform`` would shadow the standard library.
"""

from importlib.resources import files

__all__ = ["PACKAGE_ROOT", "__version__"]

__version__ = "0.1.0"

PACKAGE_ROOT = files(__name__)

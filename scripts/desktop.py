"""Dev shim: run the desktop app from a source checkout.

The PyInstaller build uses this same file as its entry script.
"""

import sys

from app.desktop import main

if __name__ == "__main__":
    sys.exit(main())

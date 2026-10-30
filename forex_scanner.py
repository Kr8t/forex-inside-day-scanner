"""Compatibility wrapper so `python forex_scanner.py ...` keeps working.

The implementation now lives in the `forex_scanner/` package; because this
script sits next to that package, `import forex_scanner` resolves to it.
"""

import sys

from forex_scanner.cli import main

if __name__ == "__main__":
    sys.exit(main())

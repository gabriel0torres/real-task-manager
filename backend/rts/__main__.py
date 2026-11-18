"""``python -m rts`` and the standalone executable entry point."""

import multiprocessing
import sys

from rts.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())

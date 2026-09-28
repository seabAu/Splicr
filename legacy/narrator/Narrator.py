#!/usr/bin/env python3
"""Double-clickable launcher.

Exists so the app can be started without knowing anything about Python
packages: double-click this file, or run `python Narrator.py`. It only adds
this folder to the import path and hands off to the package.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from narrator.__main__ import main

if __name__ == "__main__":
    main()

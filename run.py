"""Entry point for PyInstaller and `python run.py`."""
import multiprocessing

from comslog.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

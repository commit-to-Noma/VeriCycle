#!/usr/bin/env python
import os
import runpy

ROOT = os.path.abspath(os.path.dirname(__file__))
TARGET = os.path.join(ROOT, "scripts", "prepare_phase5_demo_events.py")

if __name__ == "__main__":
    runpy.run_path(TARGET, run_name="__main__")

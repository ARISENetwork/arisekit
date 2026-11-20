"""Run the pinned NOHARMKit CLI from the ARISEKit environment."""
from pathlib import Path
import runpy
import sys

toolkit = Path(__file__).resolve().parents[1] / "toolkits" / "noharmkit"
sys.path.insert(0, str(toolkit))
runpy.run_path(str(toolkit / "tools" / "noharm.py"), run_name="__main__")

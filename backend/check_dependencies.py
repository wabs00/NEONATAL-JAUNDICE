"""Quiet dependency probe for Windows PowerShell launchers."""
import subprocess
import sys

if __name__ == "__main__":
    probe = subprocess.run(
        [sys.executable, "-c", "import " + ", ".join(sys.argv[1:])],
        capture_output=True,
    )
    sys.exit(probe.returncode)

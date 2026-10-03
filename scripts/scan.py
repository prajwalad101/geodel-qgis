"""Run blocking code/security checks on source or an extracted plugin."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    subprocess.run([
        sys.executable, "-m", "flake8", "--isolated", "--max-line-length=120",
        "--extend-ignore=E402,W503", str(directory),
    ], check=True)
    subprocess.run([
        sys.executable, "-m", "bandit", "-r", str(directory), "-q",
    ], check=True)
    result = subprocess.run([
        sys.executable, "-m", "detect_secrets", "scan", "--all-files", str(directory),
    ], check=True, capture_output=True, text=True)
    findings = json.loads(result.stdout)["results"]
    if findings:
        # Report filenames and lines only, never secret values.
        locations = [
            f"{name}:{item['line_number']} ({item['type']})"
            for name, items in findings.items() for item in items
        ]
        raise SystemExit("Secret scan findings: " + ", ".join(locations))
    print(f"Flake8, Bandit and detect-secrets passed: {directory}")


if __name__ == "__main__":
    main()

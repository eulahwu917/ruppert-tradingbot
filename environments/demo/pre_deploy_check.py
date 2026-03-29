#!/usr/bin/env python
"""
Pre-deploy gate for Ruppert trading bot.
Runs Layers 1-3 tests only (no network/API required).
Exit 0 = safe to deploy, Exit 1 = BLOCKED.

Usage: python pre_deploy_check.py
"""
import subprocess
import sys


def main():
    print("=" * 60)
    print("RUPPERT PRE-DEPLOY GATE")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/',
         '--ignore=tests/test_integration.py', '-v', '--tb=short'],
        cwd=str(Path(__file__).parent),
    )

    if result.returncode != 0:
        print("\nDEPLOY BLOCKED: tests failed")
        sys.exit(1)

    print("\nALL CLEAR: pre-deploy checks passed")
    sys.exit(0)


if __name__ == '__main__':
    main()

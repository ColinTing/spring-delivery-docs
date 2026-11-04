#!/usr/bin/env python3
"""Keep the scripts that both skills use identical.

Each skill folder must work when installed on its own, so shared scripts are real
copies (git symlinks turn into plain text files on a default Windows checkout).
The source is skills/spring-delivery-docs/scripts/; this copies the shared files
into the other skills.

Usage:
    python tools/sync_shared.py          # update the copies
    python tools/sync_shared.py --check  # exit 1 if any copy differs (CI, pre-commit)
"""
import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "skills", "spring-delivery-docs", "scripts")
SHARED = {"spring-detailed-design": ["scan_spring.py", "md2docx.py"]}


def same(a, b):
    if not os.path.exists(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only report differences")
    args = ap.parse_args()
    stale = []
    for skill, files in SHARED.items():
        for name in files:
            src = os.path.join(SOURCE, name)
            dst = os.path.join(ROOT, "skills", skill, "scripts", name)
            rel = os.path.relpath(dst, ROOT)
            if same(src, dst):
                print(f"ok      {rel}")
            elif args.check:
                print(f"STALE   {rel}  (run: python tools/sync_shared.py)")
                stale.append(rel)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                print(f"updated {rel}")
    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()

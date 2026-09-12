#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from ppt_skill_v3.package_skill import package_skill


def main() -> int:
    parser = argparse.ArgumentParser(description="Package PPT Skill v3 with a strict whitelist.")
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    manifest = package_skill(args.skill_dir, args.output_dir)
    print(json.dumps({"status": "packaged", "manifest": manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

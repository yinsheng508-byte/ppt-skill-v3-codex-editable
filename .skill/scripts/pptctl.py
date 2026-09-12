#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
import os

RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
SKILL_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = SKILL_DIR.parent
PRIMARY_PYTHON = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "bin" / "python3"
if PRIMARY_PYTHON.exists() and os.environ.get("PPTCTL_NO_BUNDLED_PYTHON") != "1":
    current_python = Path(sys.executable).resolve()
    bundled_python = PRIMARY_PYTHON.resolve()
    if current_python != bundled_python:
        os.execv(str(bundled_python), [str(bundled_python), str(Path(__file__).resolve()), *sys.argv[1:]])
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from ppt_skill_v3.cli import main


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    os.chdir(WORKSPACE_DIR)
    raise SystemExit(main())

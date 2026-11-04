"""Streamlit multipage entry point for Stage 2 technical trading dashboard."""
from base64 import b64decode
from hashlib import sha256
from pathlib import Path
import runpy
import sys
import tempfile

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARTS_DIR = PROJECT_ROOT / "trading_module_bundle_parts"
EXPECTED_SHA256 = "db7294e5b087150c4eb500ebe0e4c7cb60012eb9a78ff9545ae69cdde97a74f9"

try:
    part_paths = sorted(PARTS_DIR.glob("part_*.b64"))
    if len(part_paths) != 24:
        raise FileNotFoundError(
            f"Trading package parts incomplete: found {len(part_paths)} of 24"
        )
    encoded = "".join(path.read_text(encoding="ascii").strip() for path in part_paths)
    archive = b64decode(encoded, validate=True)
    if sha256(archive).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Trading module package SHA-256 mismatch")
except Exception as exc:
    st.error(f"โหลด Trading Module ไม่สำเร็จ: {exc}")
    st.stop()

# Keep the verified archive in the OS temp directory. Python's zipimport
# loads the package directly from this ZIP; there is no network download.
bundle_path = Path(tempfile.gettempdir()) / f"fuzzy_trading_{EXPECTED_SHA256[:12]}.zip"
if (
    not bundle_path.is_file()
    or sha256(bundle_path.read_bytes()).hexdigest() != EXPECTED_SHA256
):
    bundle_path.write_bytes(archive)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(bundle_path) not in sys.path:
    sys.path.insert(0, str(bundle_path))

runpy.run_module("trading.dashboard_page", run_name="__main__")

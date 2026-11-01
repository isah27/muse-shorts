import os, sys, tempfile
from pathlib import Path
# Tests run fully offline on the mock provider unless a test is marked `live`.
os.environ.setdefault("MUSE_PROVIDER", "mock")
os.environ["EVIDENCE_PROVIDER"] = "mock"
os.environ["EVIDENCE_CACHE"] = tempfile.mkdtemp()
os.environ["OUTPUT_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import sys
import tempfile
from pathlib import Path

# isolate the database/media for tests before the app is imported
os.environ["LMM_DATA_DIR"] = tempfile.mkdtemp(prefix="lmm-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

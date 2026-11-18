import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# keep test artefacts out of the real data folders
_tmp = tempfile.mkdtemp(prefix="barndo-test-")
os.environ.setdefault("BARNDO_DATA_DIR", str(Path(_tmp) / "data"))
os.environ.setdefault("BARNDO_OUTPUT_DIR", str(Path(_tmp) / "output"))
os.environ.setdefault("BARNDO_ADMIN_TOKEN", "test-token")
for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
    os.environ.pop(k, None)

"""Paths and environment settings."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULEBOOK_PATH = Path(os.environ.get("BARNDO_RULEBOOK", ROOT / "rules" / "barndo_rules.xlsx"))
MODULES_DIR = Path(os.environ.get("BARNDO_MODULES_DIR", ROOT / "modules"))
DATA_DIR = Path(os.environ.get("BARNDO_DATA_DIR", ROOT / "data"))
OUTPUT_DIR = Path(os.environ.get("BARNDO_OUTPUT_DIR", ROOT / "output"))
WEB_DIR = ROOT / "web"

COMPANY_NAME = os.environ.get("BARNDO_COMPANY_NAME", "ES Barndominiums")
AI_MODEL = os.environ.get("BARNDO_AI_MODEL", "claude-opus-5-5")
ADMIN_TOKEN = os.environ.get("BARNDO_ADMIN_TOKEN", "")
LEAD_WEBHOOK_URL = os.environ.get("BARNDO_LEAD_WEBHOOK_URL", "")
ODA_CONVERTER = os.environ.get("ODA_FILE_CONVERTER", "")  # path to ODAFileConverter for DWG export

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st

from ui_automation.config import settings
from ui_automation.database import Database
from ui_automation.repository import Repository
from ui_automation.ui import render
from ui_automation.utils import configure_logging

settings.prepare()
database = Database(settings.database_path)
repository = Repository(database)
logger = configure_logging(settings.reports_dir)

st.set_page_config(page_title="UI Automation Workbench", page_icon="◉", layout="wide")
render(repository, settings, logger)

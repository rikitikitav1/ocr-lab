import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres@localhost:5433/postgres")
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
SHELF_DIR = Path(os.getenv("SHELF_DIR", "/shelf"))
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", Path(__file__).resolve().parents[1] / "config"))
APP_DIR = Path(__file__).resolve().parent
CPU_LANE_THREADS = int(os.getenv("CPU_LANE_THREADS", "4"))
CONVERTERS = {
    "docling": os.getenv("CONVERTER_DOCLING_BASE_URL", "http://localhost:5001"),
    "mineru": os.getenv("CONVERTER_MINERU_BASE_URL", "http://localhost:5002"),
}
# the engines every piece is read by, named once
ENGINES = tuple(CONVERTERS)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# where people and agents reach the stand from outside, for the download links its answers carry
STAND_URL = os.getenv("STAND_URL", "http://localhost:8100")
MODEL_CLOUD_BASE_URL = os.getenv("MODEL_CLOUD_BASE_URL", "")
MODEL_CLOUD_API_KEY = os.getenv("MODEL_CLOUD_API_KEY", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

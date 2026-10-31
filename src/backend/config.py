import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PROFILE = os.getenv("DATA_PROFILE", "prod")
if DATA_PROFILE == 'eval':
    JSON_PATH = os.path.join(BASE_DIR, "data","eval", "raw", "wiki_crawler_dataset.json")
    VDB_PATH = os.path.join(BASE_DIR, "data", "eval", "vector")
else:
    JSON_PATH = os.path.join(BASE_DIR, "data", "raw", "wiki_crawler_dataset.jsonl")
    VDB_PATH = os.path.join(BASE_DIR, "data", "vector")

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "wiki_ai_english"
DEFAULT_TOP_K = 5
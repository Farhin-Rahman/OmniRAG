"""Test configuration - mocks heavy ML dependencies."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add backend directory to Python path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Set test environment
os.environ["APP_ENV"] = "test"

# Set required environment variables for tests
test_env_vars = {
    "APP_NAME": "omnirag-test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_DB": "test",
    "POSTGRES_URL": "sqlite:///:memory:",  # Use SQLite by default for tests
    "JWT_SECRET_KEY": "test-jwt-secret",
    "NEO_USER": "test",
    "NEO_PASSWORD": "test",
    "NEO_DB": "test",
    "NEO_URI": "bolt://localhost:7687",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672/",
    "QDRANT_HOST": "localhost",
    "QDRANT_PORT": "6333",
    "QDRANT_URI": "http://localhost:6333",
    "BLOB_STORAGE_DIR": "data/blob_storage",
    "DOCUMENTS_DIR": "data/documents",
}

# Set environment variables only if not already set
for key, value in test_env_vars.items():
    if key not in os.environ:
        os.environ[key] = value

# Mock ML client to avoid importing httpx and ML dependencies
mock_ml_client = MagicMock()
mock_ml_client.base_url = "http://mock-ml-service:8000"
mock_ml_client.generate_embeddings = MagicMock(return_value=[[0.1] * 1024])
mock_ml_client.generate_embeddings_async = MagicMock(return_value=[[0.1] * 1024])
mock_ml_client.rerank_candidates = MagicMock(return_value=[])
mock_ml_client.rerank_candidates_async = MagicMock(return_value=[])

sys.modules["services.ml_client"] = MagicMock(
    MLServiceClient=MagicMock, ml_client=mock_ml_client
)

# Mock heavy libraries so app modules import without them installed. These
# are all in the OCR / document-parsing path, which no test exercises (the
# tests cover moderation, the LLM client, language utils, and the webhook
# surface). The CI test env installs only requirements-ci.txt.
sys.modules["paddleocr"] = MagicMock()
sys.modules["paddlepaddle"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchvision"] = MagicMock()
sys.modules["transformers"] = MagicMock()
sys.modules["sentence_transformers"] = MagicMock()
sys.modules["docling"] = MagicMock()
sys.modules["docling_core"] = MagicMock()
sys.modules["docling_parse"] = MagicMock()
sys.modules["layoutparser"] = MagicMock()
sys.modules["pytesseract"] = MagicMock()
sys.modules["fitz"] = MagicMock()
_pil = MagicMock()
sys.modules["PIL"] = _pil
sys.modules["PIL.Image"] = _pil.Image
sys.modules["cv2"] = MagicMock()

# Mock task queue dependencies (not tested in CI)
sys.modules["celery"] = MagicMock()
sys.modules["pika"] = MagicMock()
sys.modules["redis"] = MagicMock()

# Mock Firebase Admin: routes/webhooks.py imports it at module level for
# Bearer-token verification, but no test exercises that path (the webhook
# tests cover the WEBHOOK_SECRET header check). Not in requirements-ci.txt
# — same tradeoff as the OCR/ML libs above, mocked rather than installed
# since nothing here actually needs real Firebase verification.
sys.modules["firebase_admin"] = MagicMock()
sys.modules["firebase_admin.auth"] = MagicMock()
sys.modules["firebase_admin.credentials"] = MagicMock()

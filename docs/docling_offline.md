# Docling Offline Setup Guide (Docker + Celery)

Use this setup to run Docling fully offline inside Docker.  
This prevents model download failures, missing-model errors, and worker hangs.

------------------------------------------------------------
# 1. Configure Celery Worker (single process)

In the worker service of docker-compose.yml:

command:
  [
    "celery", "-A", "worker.celery_app", "worker",
    "--loglevel=info",
    "--pool=solo",
    "--concurrency=1"
  ]

Add shared memory:
shm_size: "2gb"

------------------------------------------------------------
# 2. Add shared model cache volume

volumes:
  - model_cache:/home/appuser/.cache

This ensures all Docling & HF models are stored persistently.

Also add the volume under the global `volumes:` section:

volumes:
  model_cache:

------------------------------------------------------------
# 3. Add required environment variables

These MUST be in the worker container:

DOCLING_CACHE_DIR=/home/appuser/.cache/docling
DOCLING_ARTIFACTS_PATH=/home/appuser/.cache/docling/models/docling-project--docling-models
HF_HOME=/home/appuser/.cache/huggingface
TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface

These ensure Docling + Transformers look in the correct offline directories.

------------------------------------------------------------
# 4. Download Docling models (once)

Run inside worker container:

docker exec -u appuser omnirag-worker python - << 'EOF'
from docling.utils.model_downloader import download_models
download_models()
EOF

This downloads:
- TableFormer (accurate + fast)
- RapidOCR
- Layout models
- Figure classifier
- Docling internal models

------------------------------------------------------------
# 5. Verify that all models are present

docker exec omnirag-worker ls -R /home/appuser/.cache/docling/models

Expected folders:

docling-project--docling-models
RapidOcr
docling-project--CodeFormulaV2
docling-project--DocumentFigureClassifier
docling-project--docling-layout-heron
tableformer/accurate/*.safetensors
tableformer/fast/*.safetensors

If these exist, Docling can run fully offline.

------------------------------------------------------------
# 6. After verification, restart worker

docker compose restart worker

Worker should now:
- load Docling converter instantly
- NEVER download models
- avoid TableModel04_rs errors
- avoid blocking/hanging
- run stable inside Celery solo mode

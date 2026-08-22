import sys

# Add backend to path
sys.path.append("/app/backend")

from services.database import SessionLocal
from models.document import Document

db = SessionLocal()
doc = db.query(Document).first()

if doc:
    print(f"DOC_ID={doc.doc_id}")
    print(f"TENANT_ID={doc.tenant_id}")
else:
    print("NO_DOCUMENTS")

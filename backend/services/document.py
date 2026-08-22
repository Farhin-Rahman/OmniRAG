import hashlib
import logging

from sqlalchemy.orm import Session

from models import Document

logger = logging.getLogger(__name__)


def get_document_by_hash(db: Session, file_hash: str) -> Document | None:
    """
    Retrieves a document from the database by its SHA256 hash.

    Args:
        db (Session): The database session.
        file_hash (str): The SHA256 hash of the document file.

    Returns:
        Document | None: The Document object if found, otherwise None.
    """
    return db.query(Document).filter(Document.sha256 == file_hash).first()


def get_sha256_hash(file_content: bytes) -> str:
    """
    Calculates the SHA256 hash of a file's content.

    Args:
        file_content (bytes): The content of the file.

    Returns:
        str: The hexadecimal representation of the SHA256 hash.
    """
    sha256_hash = hashlib.sha256()
    sha256_hash.update(file_content)
    return sha256_hash.hexdigest()

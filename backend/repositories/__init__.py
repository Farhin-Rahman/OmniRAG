"""Repository layer for database operations.

Repositories encapsulate data access logic and provide a clean API
for CRUD operations on domain models.
"""

from repositories.document_repository import DocumentRepository

__all__ = [
    "DocumentRepository",
]

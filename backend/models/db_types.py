"""Database-agnostic type definitions for SQLAlchemy models."""

import json
import uuid as uuid_lib

from sqlalchemy import JSON, String, Text, TypeDecorator
from sqlalchemy.dialects import postgresql


class GUID(TypeDecorator):
    """Platform-independent GUID type.

    Uses PostgreSQL's UUID type when available, otherwise uses CHAR(36).
    """

    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID())
        else:
            return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == "postgresql":
            return str(value)
        else:
            if isinstance(value, uuid_lib.UUID):
                return str(value)
            return value

    def process_result_value(self, value, dialect):  # noqa: ARG002
        if value is None:
            return value
        if not isinstance(value, uuid_lib.UUID):
            return uuid_lib.UUID(value)
        return value


# Alias for compatibility
UUID = GUID


class JSONType(TypeDecorator):
    """Platform-independent JSON type.

    Uses PostgreSQL's JSONB type when available, otherwise uses generic JSON.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        else:
            return dialect.type_descriptor(JSON())


# Alias for compatibility
JSONB = JSONType


class ArrayType(TypeDecorator):
    """Platform-independent Array type.

    Uses PostgreSQL's ARRAY type when available, otherwise stores as JSON.
    """

    impl = Text
    cache_ok = True

    def __init__(self, item_type, *args, **kwargs):
        self.item_type = item_type
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.ARRAY(self.item_type))
        else:
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name != "postgresql":
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name != "postgresql" and isinstance(value, str):
            return json.loads(value)
        return value


# Alias for compatibility
def ARRAY(item_type):
    """Factory function for ArrayType."""
    return ArrayType(item_type)

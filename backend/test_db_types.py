#!/usr/bin/env python3
"""Test db_types work correctly"""

import os

os.environ["POSTGRES_URL"] = "sqlite:///:memory:"

from models.db_types import JSONB
from sqlalchemy import create_engine, Column, Integer
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class TestModel(Base):
    __tablename__ = "test"
    id = Column(Integer, primary_key=True)
    data = Column(JSONB, nullable=True)


engine = create_engine("sqlite:///:memory:")
print(f"JSONB type: {JSONB}")
print(f"JSONB class: {JSONB.__class__}")
print("Creating tables...")
Base.metadata.create_all(engine)
print("Success!")

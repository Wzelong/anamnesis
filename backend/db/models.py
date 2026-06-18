"""SQLAlchemy ORM models.

Empty for now: the stateless path persists no DB rows. The per-user config
table (app_user) lands once the PO token's identity claim is confirmed.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

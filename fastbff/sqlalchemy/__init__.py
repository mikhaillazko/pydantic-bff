"""SQLAlchemy extension for fastbff.

Optional extra — install with ``pip install fastbff[sqlalchemy]``. Provides
:class:`SqlalchemyConverter`, a per-request helper that executes a
SQLAlchemy ``Select`` and projects rows into the shape fastbff's auto-wrap
expects, so handlers don't hand-build ``[{...} for row in ...]`` lists.
"""

from .converter import SqlalchemyConverter

__all__ = ['SqlalchemyConverter']

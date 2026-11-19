"""Add, edit and remove cards in the collection CSV: search TCGdex, save a card with its condition, keep its TCGplayer id.

store.py   the CSV, one row per owned stack (the PriceCharting export format)
service.py the operations (search / add / update / remove); no HTTP, no files of its own, so an API can wrap it later
"""
from .service import CollectionService, ServiceError  # noqa: F401
from .store import COLUMNS, CsvCollection, row_keys  # noqa: F401

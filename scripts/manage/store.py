"""The collection CSV: a list of rows in the PriceCharting export format (the columns build.py reads).

Every change rewrites the whole file through a temp file, after copying the old one to <name>.prev.csv (gitignored with
the other CSVs), so a bad edit is one `mv` away from undone.
"""
from __future__ import annotations

import csv
import io
import os
import shutil
import threading
from typing import Callable, Dict, List

COLUMNS = ["id", "product-name", "console-name", "price-in-pennies", "include-string", "condition-string", "condition-id", "sku",
           "notes", "cost-basis-in-pennies", "quantity", "date-entered", "date-purchased", "grading-company", "grading-cert-id", "folder"]

Row = Dict[str, str]


def row_keys(rows: List[Row]) -> List[str]:
    """A stable key per row (PriceCharting id, grade, condition, date, folder, and a counter for identical rows).
    build.py uses these as entry keys, and the editor addresses rows by them."""
    seen: Dict[str, int] = {}
    keys = []
    for r in rows:
        cond = (r.get("condition-string") or "").strip()
        grader = (r.get("grading-company") or "").strip()
        grade = f"{grader} {cond}".strip() if grader else "Raw"
        base = "|".join([r["id"], grade, cond, r.get("date-entered", ""), (r.get("folder") or "").strip()])
        seen[base] = seen.get(base, 0) + 1
        keys.append(f"{base}|{seen[base]}")
    return keys


class CsvCollection:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()

    def _read(self):
        if not os.path.exists(self.path):
            return list(COLUMNS), [], "\n"
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            text = f.read()
        reader = csv.DictReader(io.StringIO(text, newline=""))
        return list(reader.fieldnames or COLUMNS), list(reader), "\r\n" if "\r\n" in text else "\n"

    def rows(self) -> List[Row]:
        return self._read()[1]

    def _commit(self, fieldnames, rows, newline) -> None:
        if os.path.exists(self.path):
            shutil.copyfile(self.path, os.path.splitext(self.path)[0] + ".prev.csv")
        tmp = self.path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator=newline)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, self.path)

    def append(self, row: Row) -> None:
        with self._lock:
            fields, rows, nl = self._read()
            rows.append({c: row.get(c, "") for c in fields})
            self._commit(fields, rows, nl)

    def edit(self, key: str, change: Callable[[Row], None]) -> Row:
        """Apply `change` to the row with this key and save. KeyError if there is no such row."""
        with self._lock:
            fields, rows, nl = self._read()
            keys = row_keys(rows)
            if key not in keys:
                raise KeyError(key)
            row = rows[keys.index(key)]
            change(row)
            self._commit(fields, rows, nl)
            return row

    def delete(self, key: str) -> None:
        with self._lock:
            fields, rows, nl = self._read()
            keys = row_keys(rows)
            if key not in keys:
                raise KeyError(key)
            del rows[keys.index(key)]
            self._commit(fields, rows, nl)

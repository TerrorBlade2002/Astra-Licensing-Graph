"""Controlled spreadsheet and source imports.

Spreadsheet cells are treated strictly as data: formulas are never evaluated and
macro-enabled workbooks are rejected. Every run is a dry-runnable, row-level
auditable operation that preserves the original source file and row fingerprints.
"""

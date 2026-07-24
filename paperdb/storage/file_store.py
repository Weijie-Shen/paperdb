"""File storage layer — manage the paper_database/files/ directory tree."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional


# Directory names under files/
DIR_RAW_PDF = "raw_pdf"
DIR_RAW_HTML = "raw_html"
DIR_RAW_DOCX = "raw_docx"
DIR_PARSED_TEXT = "parsed/text"
DIR_PARSED_TABLES = "parsed/tables"
DIR_PARSED_META = "parsed/metadata"
DIR_NOTES = "notes"
DIR_SUMMARIES = "summaries"
DIR_INBOX = "_inbox"

ALL_DIRS = [
    DIR_RAW_PDF,
    DIR_RAW_HTML,
    DIR_RAW_DOCX,
    DIR_PARSED_TEXT,
    DIR_PARSED_TABLES,
    DIR_PARSED_META,
    DIR_NOTES,
    DIR_SUMMARIES,
    DIR_INBOX,
]


class FileStore:
    """Manages the file storage tree under ``paper_database/files/``.

    All file paths are relative to the store root. Files are named by paper
    ID (e.g. ``raw_pdf/p_2026_07_08_a1b2c3.pdf``).
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create the full directory tree. Idempotent."""
        for d in ALL_DIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path builders
    # ------------------------------------------------------------------

    def raw_path(self, paper_id: str, fmt: str = "pdf") -> Path:
        """Path to store a raw downloaded/imported file.

        Args:
            paper_id: e.g. ``p_2026_07_08_a1b2c3``
            fmt: one of ``pdf``, ``html``, ``docx``, ``txt``
        """
        dir_map = {"pdf": DIR_RAW_PDF, "html": DIR_RAW_HTML, "docx": DIR_RAW_DOCX, "txt": DIR_RAW_PDF}
        subdir = dir_map.get(fmt, DIR_RAW_PDF)
        return self.root / subdir / f"{paper_id}.{fmt}"

    def parsed_text_path(self, paper_id: str) -> Path:
        return self.root / DIR_PARSED_TEXT / f"{paper_id}.txt"

    def parsed_tables_path(self, paper_id: str) -> Path:
        return self.root / DIR_PARSED_TABLES / f"{paper_id}.json"

    def summary_path(self, paper_id: str) -> Path:
        return self.root / DIR_SUMMARIES / f"{paper_id}.md"

    def note_path(self, paper_id: str) -> Path:
        return self.root / DIR_NOTES / f"{paper_id}.md"

    def inbox_path(self, filename: str) -> Path:
        return self.root / DIR_INBOX / filename

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def add_file(
        self,
        paper_id: str,
        source_path: str | Path,
        fmt: str = "pdf",
        move: bool = False,
    ) -> str:
        """Copy (or move) a file into the store.

        Args:
            paper_id: Paper ID for naming.
            source_path: Path to the source file.
            fmt: File format (determines target subdirectory).
            move: If True, move instead of copy.

        Returns:
            The relative path from the store root (e.g. ``raw_pdf/p_xxx.pdf``).
        """
        dest = self.raw_path(paper_id, fmt)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if move:
            shutil.move(str(source_path), str(dest))
        else:
            shutil.copy2(str(source_path), str(dest))

        # Return relative path from store root
        return str(dest.relative_to(self.root))

    def get_path(self, relative_path: str) -> Path:
        """Resolve a store-relative path to an absolute path."""
        return self.root / relative_path

    def exists(self, relative_path: str) -> bool:
        """Check if a file exists at the given store-relative path."""
        return (self.root / relative_path).is_file()

    def remove_file(self, relative_path: str) -> None:
        """Remove a file from the store."""
        p = self.root / relative_path
        if p.exists():
            p.unlink()

    def list_inbox(self) -> list[Path]:
        """List files in the watched _inbox directory."""
        inbox = self.root / DIR_INBOX
        if not inbox.exists():
            return []
        return sorted(p for p in inbox.iterdir() if p.is_file())

    def write_parsed_text(self, paper_id: str, text: str) -> str:
        """Write extracted plain text. Returns relative path."""
        dest = self.parsed_text_path(paper_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return str(dest.relative_to(self.root))

    def write_summary(self, paper_id: str, summary: str) -> str:
        """Write AI-generated summary in markdown. Returns relative path."""
        dest = self.summary_path(paper_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(summary, encoding="utf-8")
        return str(dest.relative_to(self.root))

    def read_text(self, relative_path: str) -> Optional[str]:
        """Read a text file from the store."""
        p = self.root / relative_path
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

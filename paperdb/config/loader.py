"""Configuration loader — reads YAML config files from paper_database/config/."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

from paperdb.config.institutions import InstitutionMatch, match_institutions


# ---------------------------------------------------------------------------
# Default config values (used when no config files exist yet)
# ---------------------------------------------------------------------------

DEFAULT_SOURCES: dict[str, Any] = {
    "connectors": {
        "arxiv": {
            "enabled": True,
            "categories": ["q-fin.ST", "q-fin.PM", "q-fin.RM", "stat.ML", "cs.LG"],
        },
        "choice": {
            "enabled": True,
            "requires_auth": True,
            "auth_type": "terminal",
        },
        "semantic_scholar": {
            "enabled": True,
        },
    },
    "search_defaults": {
        "max_results": 50,
        "time_range_years": None,
    },
}

DEFAULT_WATCHLIST: dict[str, Any] = {
    "institutions": [
        {"name": "华泰证券", "priority": 1, "aliases": ["华泰证券股份有限公司", "Huatai Securities", "HTSC"], "research_teams": ["金融工程组", "策略组"]},
        {"name": "国泰君安", "priority": 1, "aliases": ["国泰君安证券", "Guotai Junan Securities"], "research_teams": ["金融工程组"]},
        {"name": "中金公司", "priority": 1, "aliases": ["中国国际金融股份有限公司", "China International Capital Corporation", "CICC"]},
        {"name": "中信证券", "priority": 2, "aliases": ["中信证券股份有限公司", "CITIC Securities"]},
        {"name": "海通证券", "priority": 2},
        {"name": "广发证券", "priority": 2, "aliases": ["广发证券股份有限公司", "GF Securities"]},
        {"name": "招商证券", "priority": 2, "aliases": ["招商证券股份有限公司", "China Merchants Securities"]},
        {"name": "申万宏源", "priority": 2},
        {"name": "兴业证券", "priority": 3},
        {"name": "东方证券", "priority": 3},
        {"name": "天风证券", "priority": 3},
        {"name": "方正证券", "priority": 3},
    ],
    "authors": [],
}

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

class Config:
    """Loads and provides access to YAML configuration files.

    Config files live under ``<db_root>/config/``. Missing files fall back
    to sensible defaults.
    """

    def __init__(self, db_root: str | Path):
        self.db_root = Path(db_root).resolve()
        self.config_dir = self.db_root / "config"

    # ------------------------------------------------------------------
    # Low-level YAML loading
    # ------------------------------------------------------------------

    def _load_yaml(self, filename: str, default: dict) -> dict:
        """Load a YAML file, returning *default* if the file is missing."""
        path = self.config_dir / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or default
        return default

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def sources(self) -> dict:
        """Connector configuration (sources.yaml)."""
        return self._load_yaml("sources.yaml", DEFAULT_SOURCES)

    @property
    def watchlist(self) -> dict:
        """Priority institutions and authors (watchlist.yaml)."""
        return self._load_yaml("watchlist.yaml", DEFAULT_WATCHLIST)

    @property
    def taxonomy(self) -> dict:
        """Label taxonomy (taxonomy.yaml)."""
        default_tax = {"labels": {}}
        return self._load_yaml("taxonomy.yaml", default_tax)

    @property
    def embedding(self) -> dict:
        """Embedding backend config (embedding.yaml)."""
        default_embed = {
            "backend": "local",
            "local": {
                "model": "BAAI/bge-large-zh-v1.5",
                "device": "auto",
            },
            "openai": {
                "model": "text-embedding-3-small",
            },
        }
        return self._load_yaml("embedding.yaml", default_embed)

    # ------------------------------------------------------------------
    # Watchlist helpers
    # ------------------------------------------------------------------

    def resolve_institutions(self, values: list[tuple[str, str]]) -> list[InstitutionMatch]:
        """Resolve raw affiliations to canonical, alias-aware watchlist identities."""
        return match_institutions(self.watchlist.get("institutions", []), values)

    def resolve_metadata_institutions(self, metadata) -> list[InstitutionMatch]:
        """Resolve paper and per-author affiliations; never inspect author names."""
        values: list[tuple[str, str]] = []
        if getattr(metadata, "institution", None):
            values.append((metadata.institution, "paper_institution"))
        extra = getattr(metadata, "extra", {}) or {}
        for author in extra.get("author_affiliations", []):
            for affiliation in author.get("affiliations", []):
                values.append((affiliation, "author_affiliation"))
        return self.resolve_institutions(values)

    def get_priority(self, institution: str) -> int:
        """Return a descending sort score (highest configured priority ranks first)."""
        matches = self.resolve_institutions([(institution, "paper_institution")])
        return matches[0].priority_score if matches else 0

    def canonicalize_institution_filter(self, value: str) -> str:
        """Map a configured alias (for example CICC) to its canonical name."""
        matches = self.resolve_institutions([(value, "query_filter")])
        return matches[0].canonical_name if matches else value

    def get_watchlist_institutions(self) -> list[str]:
        """Return list of institution names on the watchlist, sorted by priority."""
        wl = self.watchlist
        items = sorted(wl.get("institutions", []), key=lambda x: x["priority"])
        return [inst["name"] for inst in items]

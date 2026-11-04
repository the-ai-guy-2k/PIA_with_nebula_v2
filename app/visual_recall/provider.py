"""Replaceable image lookup. The default provider does not call the network."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.purchase_analytics.identity import analytics_key

PROVIDER_NAME = "local-catalog"


@dataclass(frozen=True)
class ProviderMatch:
    match_type: str
    image_file: str | None
    source_reference: str | None
    provider_name: str


class CatalogImageProvider:
    """Local illustrations. Exact is used only for a full catalog name.

    A generic food word never becomes an exact product image. Two different
    food words in one name are treated as ambiguous and return no image.
    """

    def __init__(self, catalog_dir: Path) -> None:
        self.catalog_dir = catalog_dir
        self._exact: list[dict[str, str]] = []
        self._representative: list[dict[str, object]] = []
        self._load()

    def lookup(self, item_name: str) -> ProviderMatch:
        key = analytics_key(item_name)
        for entry in self._exact:
            if key == entry["name"] and self.resolve(entry["file"]) is not None:
                return ProviderMatch("exact", entry["file"], entry["source"], PROVIDER_NAME)
        hits = []
        tokens = set(key.split())
        for entry in self._representative:
            entry_tokens = entry["tokens"]
            if tokens & entry_tokens and self.resolve(str(entry["file"])) is not None:
                hits.append(entry)
        if len(hits) > 1:
            return ProviderMatch("ambiguous", None, None, PROVIDER_NAME)
        if len(hits) == 1:
            chosen = hits[0]
            return ProviderMatch(
                "representative",
                str(chosen["file"]),
                str(chosen["source"]),
                PROVIDER_NAME,
            )
        return ProviderMatch("none", None, None, PROVIDER_NAME)

    def resolve(self, reference: str | None) -> Path | None:
        if not reference or "\\" in reference or reference.startswith("/"):
            return None
        parts = Path(reference).parts
        if not parts or ".." in parts:
            return None
        root = self.catalog_dir.resolve()
        candidate = (root / reference).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return None
        if candidate.suffix.lower() != ".svg":
            return None
        text = candidate.read_text(encoding="utf-8")
        if "<script" in text.lower():
            return None
        return candidate

    def _load(self) -> None:
        manifest = self.catalog_dir / "catalog.json"
        if not manifest.is_file():
            raise FileNotFoundError(manifest)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("catalog")
        exact = payload.get("exact", [])
        representative = payload.get("representative", [])
        if not isinstance(exact, list) or not isinstance(representative, list):
            raise ValueError("catalog")
        self._exact = [_exact_entry(entry) for entry in exact]
        self._representative = [_representative_entry(entry) for entry in representative]


def _exact_entry(entry: object) -> dict[str, str]:
    if not isinstance(entry, dict):
        raise ValueError("catalog")
    name = entry.get("name")
    file_name = entry.get("file")
    source = entry.get("source")
    if not all(isinstance(value, str) and value.strip() for value in (name, file_name, source)):
        raise ValueError("catalog")
    return {"name": analytics_key(str(name)), "file": str(file_name), "source": str(source)}


def _representative_entry(entry: object) -> dict[str, object]:
    if not isinstance(entry, dict):
        raise ValueError("catalog")
    tokens = entry.get("tokens")
    file_name = entry.get("file")
    source = entry.get("source")
    if not isinstance(tokens, list) or not tokens or not all(isinstance(token, str) and token for token in tokens):
        raise ValueError("catalog")
    if not isinstance(file_name, str) or not isinstance(source, str) or not file_name or not source:
        raise ValueError("catalog")
    return {"tokens": {analytics_key(token) for token in tokens}, "file": file_name, "source": source}

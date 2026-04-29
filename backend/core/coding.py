"""FAISS-backed vector search for medical terminology codes.

Lazy-loads indexes and embedding model on first use.  Heavy imports
(faiss, sentence_transformers) are deferred to method bodies so that
``from core.coding import ...`` works without those packages installed
and MCP cold start stays fast.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "indexes"
DEFAULT_MODEL_NAME = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"

SYSTEM_META_COLS: dict[str, dict] = {
    "snomed": {"code_col": "conceptId", "display_col": "display"},
    "rxnorm": {"code_col": "rxcui", "display_col": "term_string"},
    "loinc": {"code_col": "conceptId", "display_col": "long_common_name"},
    "icd10": {"code_col": "code", "display_col": "description"},
}


@dataclass(frozen=True)
class SearchResult:
    code: str
    display: str
    score: float
    rank: int


class EmbeddingModel:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                logger.info("Loading embedding model: %s", self._model_name)
                self._model = SentenceTransformer(self._model_name)

        vecs = self._model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        vecs = vecs.astype(np.float32)
        import faiss
        faiss.normalize_L2(vecs)
        return vecs


class IndexStore:
    def __init__(self, index_dir: Path = DEFAULT_INDEX_DIR):
        self._index_dir = index_dir
        self._loaded: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def _ensure_loaded(self, system: str) -> None:
        if system in self._loaded:
            return
        with self._lock:
            if system in self._loaded:
                return

            import faiss
            import pyarrow.parquet as pq

            index_path = self._index_dir / f"{system}.faiss"
            meta_path = self._index_dir / f"{system}_metadata.parquet"

            if not index_path.exists():
                raise FileNotFoundError(f"Index not found: {index_path}")
            if not meta_path.exists():
                raise FileNotFoundError(f"Metadata not found: {meta_path}")

            index = faiss.read_index(str(index_path))

            if hasattr(index, "nprobe"):
                index.nprobe = min(128, getattr(index, "nlist", 128))

            meta_table = pq.read_table(meta_path)
            cols = SYSTEM_META_COLS.get(system, {})
            code_col = cols.get("code_col", "code")
            display_col = cols.get("display_col", "display")

            codes = meta_table.column(code_col).to_pylist()
            displays = meta_table.column(display_col).to_pylist()

            logger.info("Loaded %s index: %d vectors", system, index.ntotal)
            self._loaded[system] = (index, codes, displays)

    def search(
        self,
        query_embedding: np.ndarray,
        system: str,
        top_k: int = 10,
    ) -> list[SearchResult]:
        self._ensure_loaded(system)
        index, codes, displays = self._loaded[system]

        q = query_embedding.astype(np.float32)
        if q.ndim == 1:
            q = q.reshape(1, -1)

        distances, indices = index.search(q, top_k)

        results = []
        for rank, (idx, score) in enumerate(zip(indices[0], distances[0])):
            if idx == -1:
                continue
            results.append(SearchResult(
                code=str(codes[idx]),
                display=str(displays[idx]),
                score=float(score),
                rank=rank + 1,
            ))
        return results


_default_store: IndexStore | None = None
_default_model: EmbeddingModel | None = None
_init_lock = threading.Lock()


def _get_defaults() -> tuple[IndexStore, EmbeddingModel]:
    global _default_store, _default_model
    if _default_store is None:
        with _init_lock:
            if _default_store is None:
                _default_store = IndexStore()
                _default_model = EmbeddingModel()
    return _default_store, _default_model


def search_code(
    term: str,
    system: str,
    top_k: int = 10,
) -> list[SearchResult]:
    """Search a medical code system by term text.

    >>> results = search_code("essential hypertension", "snomed")
    >>> results[0].code
    '59621000'
    """
    store, model = _get_defaults()
    embedding = model.encode([term])
    return store.search(embedding, system, top_k)

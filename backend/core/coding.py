"""FAISS-backed vector search for medical terminology codes.

Indexes and the embedding model lazy-load on first use, but the backend
startup path can call ``warmup`` to pay that cost before the first coding
request arrives. Heavy imports (faiss, sentence_transformers) stay deferred
to method bodies so ``from core.coding import ...`` remains cheap.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_HF_HOME = Path(__file__).resolve().parent.parent / ".cache" / "huggingface"
_REPO_INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "indexes"
DEFAULT_INDEX_DIR = Path(os.environ.get("ANAMNESIS_INDEX_DIR", str(_REPO_INDEX_DIR)))
DEFAULT_MODEL_NAME = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
os.environ.setdefault("HF_HOME", str(DEFAULT_HF_HOME))

SYSTEM_META_COLS: dict[str, dict] = {
    "snomed": {"code_col": "conceptId", "display_col": "display"},
    "rxnorm": {"code_col": "rxcui", "display_col": "term_string"},
    "loinc": {"code_col": "conceptId", "display_col": "long_common_name"},
    "icd10": {"code_col": "code", "display_col": "description"},
}


def _hf_home() -> Path:
    return Path(os.environ.get("HF_HOME", str(DEFAULT_HF_HOME)))


def _model_cache_exists(model_name: str) -> bool:
    model_path = Path(model_name)
    if model_path.exists():
        return True

    cache_name = f"models--{model_name.replace('/', '--')}"
    snapshots_dir = _hf_home() / "hub" / cache_name / "snapshots"
    return snapshots_dir.exists() and any(snapshots_dir.iterdir())


@dataclass(frozen=True)
class SearchResult:
    code: str
    display: str
    score: float
    rank: int


@dataclass(frozen=True)
class WarmupResult:
    model_name: str
    loaded_indexes: dict[str, int]
    missing_indexes: tuple[str, ...]
    elapsed_seconds: float


class EmbeddingModel:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                start = time.perf_counter()
                local_files_only = _model_cache_exists(self._model_name)
                if local_files_only:
                    os.environ.setdefault("HF_HUB_OFFLINE", "1")
                logger.info(
                    "Loading embedding model%s: %s",
                    " from local cache" if local_files_only else "",
                    self._model_name,
                )
                self._model = SentenceTransformer(
                    self._model_name,
                    local_files_only=local_files_only,
                )
                logger.info(
                    "Embedding model loaded in %.2fs",
                    time.perf_counter() - start,
                )

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
        if system not in SYSTEM_META_COLS:
            raise ValueError(f"Unsupported code system: {system}")
        if system in self._loaded:
            return
        with self._lock:
            if system in self._loaded:
                return

            import faiss

            index_path = self._index_dir / f"{system}.faiss"
            meta_npz_path = self._index_dir / f"{system}_metadata.npz"
            meta_path = self._index_dir / f"{system}_metadata.parquet"

            if not index_path.exists():
                raise FileNotFoundError(f"Index not found: {index_path}")
            if not meta_npz_path.exists() and not meta_path.exists():
                raise FileNotFoundError(f"Metadata not found: {meta_npz_path} or {meta_path}")

            index = faiss.read_index(str(index_path))

            if hasattr(index, "nprobe"):
                index.nprobe = min(128, getattr(index, "nlist", 128))

            if meta_path.exists():
                import pyarrow.parquet as pq

                meta_table = pq.read_table(meta_path)
                cols = SYSTEM_META_COLS.get(system, {})
                code_col = cols.get("code_col", "code")
                display_col = cols.get("display_col", "display")

                codes = meta_table.column(code_col).to_pylist()
                displays = meta_table.column(display_col).to_pylist()
            else:
                meta = np.load(meta_npz_path, allow_pickle=False)
                codes = meta["codes"].tolist()
                displays = meta["displays"].tolist()

            logger.info("Loaded %s index: %d vectors", system, index.ntotal)
            self._loaded[system] = (index, codes, displays)

    def preload(
        self,
        systems: Iterable[str] | None = None,
        *,
        strict: bool = True,
    ) -> tuple[dict[str, int], tuple[str, ...]]:
        loaded: dict[str, int] = {}
        missing: list[str] = []
        systems_to_load = SYSTEM_META_COLS if systems is None else systems
        for system in systems_to_load:
            try:
                self._ensure_loaded(system)
            except FileNotFoundError:
                if strict:
                    raise
                missing.append(system)
                continue
            index = self._loaded[system][0]
            loaded[system] = int(index.ntotal)
        return loaded, tuple(missing)

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
    store, model = _get_defaults()
    embedding = model.encode([term])
    return store.search(embedding, system, top_k)


def warmup() -> WarmupResult:
    start = time.perf_counter()
    store, model = _get_defaults()
    model.encode(["warmup"])
    loaded_indexes, missing_indexes = store.preload(strict=False)
    elapsed = time.perf_counter() - start
    logger.info(
        "Coding warmup complete: loaded=%s missing=%s elapsed=%.2fs",
        ", ".join(f"{system}:{count}" for system, count in loaded_indexes.items()) or "none",
        ", ".join(missing_indexes) or "none",
        elapsed,
    )
    return WarmupResult(
        model_name=model.model_name,
        loaded_indexes=loaded_indexes,
        missing_indexes=missing_indexes,
        elapsed_seconds=elapsed,
    )

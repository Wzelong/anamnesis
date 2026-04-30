"""Build FAISS indexes from pre-computed embedding parquet files.

One-time build artifact. Indexes are baked into the Docker image at
data/indexes/ and loaded at runtime by core.coding.IndexStore.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np
import pyarrow.parquet as pq
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_EMBEDDINGS_DIR = PROJECT_ROOT / "embeddings"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "indexes"

SYSTEMS: dict[str, dict] = {
    "snomed": {
        "parquet": "snomed_with_embeddings.parquet",
        "code_col": "conceptId",
        "display_col": "all_terms",
        "display_is_list": True,
        "extra_cols": [],
    },
    "rxnorm": {
        "parquet": "rxnorm_embeddings.parquet",
        "code_col": "rxcui",
        "display_col": "term_string",
        "display_is_list": False,
        "extra_cols": ["source", "term_type"],
    },
    "loinc": {
        "parquet": "loinc_with_embeddings.parquet",
        "code_col": "conceptId",
        "display_col": "long_common_name",
        "display_is_list": False,
        "extra_cols": ["component", "shortname", "class"],
    },
    "icd10": {
        "parquet": "icd10_embeddings.parquet",
        "code_col": "code",
        "display_col": "description",
        "display_is_list": False,
        "extra_cols": ["category"],
    },
}

EMBEDDING_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
IVFPQ_THRESHOLD = 20_000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_one(
    system: str,
    cfg: dict,
    embeddings_dir: Path,
    output_dir: Path,
    force: bool,
) -> dict | None:
    index_path = output_dir / f"{system}.faiss"
    meta_path = output_dir / f"{system}_metadata.parquet"
    meta_npz_path = output_dir / f"{system}_metadata.npz"

    if index_path.exists() and meta_path.exists() and meta_npz_path.exists() and not force:
        print(f"\n[{system}] Already built — skipping (use --force to rebuild)")
        return None

    parquet_path = embeddings_dir / cfg["parquet"]
    if not parquet_path.exists():
        print(f"\n[{system}] WARNING: {parquet_path} not found — skipping")
        return None

    print(f"\n{'=' * 50}")
    print(f"  Building {system}")
    print(f"{'=' * 50}")
    t0 = time.time()

    columns = [cfg["code_col"], cfg["display_col"], "embedding"] + cfg["extra_cols"]
    print(f"  Reading {cfg['parquet']}...")
    table = pq.read_table(parquet_path, columns=columns)
    n_rows = table.num_rows
    print(f"  {n_rows:,} rows loaded")

    print(f"  Extracting embeddings...")
    emb_col = table.column("embedding")
    embeddings = np.array(
        [row.as_py() for row in tqdm(emb_col, desc=f"  {system} vectors", unit="vec")],
        dtype=np.float32,
    )
    dim = embeddings.shape[1]
    print(f"  Shape: {embeddings.shape}, dtype: {embeddings.dtype}")

    print(f"  Normalizing to unit length...")
    faiss.normalize_L2(embeddings)

    if n_rows >= IVFPQ_THRESHOLD:
        nlist = math.ceil(math.sqrt(n_rows))
        pq_m = 48
        print(f"  Building IndexIVFPQ (nlist={nlist}, M={pq_m}, nbits=8)...")
        quantizer = faiss.IndexFlatIP(dim)
        index = faiss.IndexIVFPQ(quantizer, dim, nlist, pq_m, 8)
        print(f"  Training on {n_rows:,} vectors...")
        index.train(embeddings)
        print(f"  Adding vectors...")
        index.add(embeddings)
        index_type = f"IndexIVFPQ(nlist={nlist})"
    else:
        print(f"  Building IndexFlatIP (exact search)...")
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)
        index_type = "IndexFlatIP"

    print(f"  Index contains {index.ntotal:,} vectors")

    del embeddings
    gc.collect()

    tmp_index = output_dir / f"{system}.faiss.tmp"
    faiss.write_index(index, str(tmp_index))
    os.replace(tmp_index, index_path)
    print(f"  Wrote {index_path.name} ({index_path.stat().st_size / 1024 / 1024:.1f} MB)")
    del index
    gc.collect()

    meta_cols = [cfg["code_col"], cfg["display_col"]] + cfg["extra_cols"]
    meta_table = table.select(meta_cols)

    import pyarrow as pa
    if cfg["display_is_list"]:
        display_arr = meta_table.column(cfg["display_col"])
        first_terms = pa.array(
            [row[0].as_py() if len(row) > 0 else "" for row in display_arr],
            type=pa.string(),
        )
        meta_table = meta_table.append_column("display", first_terms)

    tmp_meta = output_dir / f"{system}_metadata.parquet.tmp"
    pq.write_table(meta_table, tmp_meta)
    os.replace(tmp_meta, meta_path)
    print(f"  Wrote {meta_path.name} ({meta_path.stat().st_size / 1024 / 1024:.1f} MB)")

    code_col = cfg["code_col"]
    display_col = "display" if cfg["display_is_list"] else cfg["display_col"]
    codes = np.asarray(meta_table.column(code_col).to_pylist(), dtype=str)
    displays = np.asarray(meta_table.column(display_col).to_pylist(), dtype=str)
    tmp_meta_npz = output_dir / f"{system}_metadata.npz.tmp"
    np.savez_compressed(tmp_meta_npz, codes=codes, displays=displays)
    os.replace(tmp_meta_npz.with_suffix(""), meta_npz_path)
    print(f"  Wrote {meta_npz_path.name} ({meta_npz_path.stat().st_size / 1024 / 1024:.1f} MB)")

    del table, meta_table
    gc.collect()

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s")

    return {
        "rows": n_rows,
        "dim": dim,
        "index_type": index_type,
        "build_seconds": round(elapsed, 1),
        "parquet_sha256": sha256_file(parquet_path),
        "index_sha256": sha256_file(index_path),
        "index_size_mb": round(index_path.stat().st_size / 1024 / 1024, 1),
        "metadata_npz_size_mb": round(meta_npz_path.stat().st_size / 1024 / 1024, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build FAISS indexes from embedding parquets")
    parser.add_argument("--embeddings-dir", type=Path, default=DEFAULT_EMBEDDINGS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--force", action="store_true", help="Rebuild even if indexes exist")
    parser.add_argument("--system", type=str, help="Build only this system (snomed, rxnorm, loinc, icd10)")
    args = parser.parse_args()

    if not args.embeddings_dir.exists():
        print(f"Embeddings directory not found: {args.embeddings_dir}")
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    systems_to_build = {args.system: SYSTEMS[args.system]} if args.system else SYSTEMS

    manifest_path = args.output_dir / "build_manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    manifest.setdefault("systems", {})
    manifest["embedding_model"] = EMBEDDING_MODEL

    total_t0 = time.time()
    for name, cfg in systems_to_build.items():
        result = build_one(name, cfg, args.embeddings_dir, args.output_dir, args.force)
        if result:
            manifest["systems"][name] = result

    manifest["build_date"] = datetime.now(timezone.utc).isoformat()
    manifest["embedding_dim"] = 768
    manifest_path.write_text(json.dumps(manifest, indent=2))

    total = time.time() - total_t0
    print(f"\nTotal build time: {total:.1f}s")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

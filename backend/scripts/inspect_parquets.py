"""Inspect embedding parquet files: schema, dimensions, sample rows."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow.parquet as pq


DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "embeddings"

EXPECTED_FILES = [
    "snomed_with_embeddings.parquet",
    "rxnorm_embeddings.parquet",
    "loinc_with_embeddings.parquet",
    "icd10_embeddings.parquet",
]


def inspect_file(path: Path) -> dict | None:
    if not path.exists():
        print(f"\n  {path.name}: NOT FOUND")
        return None

    size_mb = path.stat().st_size / (1024 * 1024)
    meta = pq.read_metadata(path)
    schema = pq.read_schema(path)

    print(f"\n{'=' * 60}")
    print(f"  {path.name}  ({size_mb:.1f} MB, {meta.num_rows:,} rows)")
    print(f"{'=' * 60}")

    print(f"\n  Columns ({len(schema)}):")
    embedding_col = None
    for i in range(len(schema)):
        field = schema.field(i)
        print(f"    {field.name}: {field.type}")
        type_str = str(field.type).lower()
        if "list" in type_str or "float" in type_str or "embedding" in field.name.lower() or "vector" in field.name.lower():
            if "list" in type_str or field.name.lower() in ("embedding", "embeddings", "vector", "vec"):
                embedding_col = field.name

    table = pq.read_table(path, columns=None).slice(0, 3)
    cols = table.column_names

    if not embedding_col:
        for c in cols:
            sample = table.column(c)[0].as_py()
            if isinstance(sample, list) and len(sample) > 10 and isinstance(sample[0], (int, float)):
                embedding_col = c
                break

    if embedding_col:
        sample_vec = table.column(embedding_col)[0].as_py()
        dim = len(sample_vec)
        dtype = type(sample_vec[0]).__name__
        print(f"\n  Embedding column: '{embedding_col}'")
        print(f"  Dimension: {dim}")
        print(f"  Element dtype: {dtype}")
        print(f"  First 5 values: {sample_vec[:5]}")
    else:
        dim = None
        print("\n  WARNING: Could not identify embedding column!")

    non_emb = [c for c in cols if c != embedding_col]
    print(f"\n  Non-embedding columns: {non_emb}")
    print(f"\n  Sample rows (non-embedding fields):")
    for i in range(min(2, table.num_rows)):
        row = {c: table.column(c)[i].as_py() for c in non_emb}
        print(f"    [{i}] {row}")

    pandas_meta = schema.pandas_metadata
    if pandas_meta:
        creator = pandas_meta.get("creator", {})
        if creator:
            print(f"\n  Pandas metadata creator: {creator}")

    arrow_meta = schema.metadata or {}
    for k, v in arrow_meta.items():
        key = k.decode() if isinstance(k, bytes) else k
        if key != b"pandas" and key != "pandas":
            val = v.decode() if isinstance(v, bytes) else v
            print(f"\n  Arrow metadata[{key}]: {val[:200]}")

    return {
        "file": path.name,
        "rows": meta.num_rows,
        "size_mb": round(size_mb, 1),
        "embedding_col": embedding_col,
        "dim": dim,
        "non_emb_cols": non_emb,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect embedding parquets")
    parser.add_argument("--embeddings-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()

    d = args.embeddings_dir
    if not d.exists():
        print(f"Directory not found: {d}")
        return 1

    print(f"Scanning: {d}")

    all_parquets = sorted(d.glob("*.parquet"))
    print(f"Found {len(all_parquets)} parquet files: {[p.name for p in all_parquets]}")

    results = []
    for p in all_parquets:
        r = inspect_file(p)
        if r:
            results.append(r)

    if results:
        print(f"\n{'=' * 60}")
        print("  SUMMARY")
        print(f"{'=' * 60}")
        print(f"  {'System':<12} {'Rows':>10} {'Size':>8} {'Dim':>5} {'Emb Col':<15} {'Other Cols'}")
        print(f"  {'-'*12} {'-'*10} {'-'*8} {'-'*5} {'-'*15} {'-'*30}")
        for r in results:
            system = r["file"].split("_")[0]
            dim_s = str(r["dim"]) if r["dim"] else "???"
            print(f"  {system:<12} {r['rows']:>10,} {r['size_mb']:>7.1f}M {dim_s:>5} {r['embedding_col'] or '???':<15} {r['non_emb_cols']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

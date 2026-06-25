# mCODE Genomics Domain

mCODE reuses the **HL7 Genomics Reporting IG** profiles as bases — GenomicVariant constrains the GR `variant` profile, GenomicRegionStudied the GR `region-studied`, GenomicsReport the GR `genomics-report`. The structure is a `DiagnosticReport` whose `result` references variant/region Observations.

These profiles model data as **component slices, each keyed by a fixed LOINC `component.code`**, with the actual data in `component.value[x]`. So the pattern is always: emit a component with the fixed code, then fill its value. You don't search terminology for component codes — they're pinned.

## GenomicsReport (DiagnosticReport → genomics-report)

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: diagnostic-report-status |
| category | 1..* | ✓ | includes a coding **fixed to `GE`** (genetics, diagnostic-service-sections) |
| code | 1..1 | ✓ | preferred: report-codes (LOINC) |
| subject, effective[x], issued, performer, specimen | | ✓ | |
| result | 0..* | ✓ | → GenomicVariant / GenomicRegionStudied Observations |

## GenomicVariant (Observation → GR `variant`)

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: observation-status |
| category | 1..1 | | **fixed** observation-category `laboratory` |
| code | 1..1 | ✓ | **fixed LOINC 69548-6** "Genetic variant assessment" |
| value[x] | 0..1 | | (present/absent — LOINC answer list LL1971-2) |
| method | 0..1 | ✓ | extensible (LOINC LL4048-6) |
| specimen | 0..1 | ✓ | |

Key component slices (fixed `component.code` → `value[x]`):
| component.code (LOINC) | meaning | value binding |
|---|---|---|
| 48018-6 | Gene studied | extensible HGNC-VS (gene symbol) |
| 48001-2 | Genomic region/cytoband | |
| 62374-4 | Reference genome build | LL1040-6 (e.g. GRCh38) |
| 48004-6 / 81290-9 | DNA change (g./c. HGVS) | required HGVS-VS |
| 48005-3 | Amino acid change (p. HGVS) | required HGVS-VS |
| 48002-0 | Genomic source class | LL378-1 (somatic/germline) |
| 53034-5 | Allelic state | LL381-5 |
| 48019-4 | DNA change type | extensible dna-change-type-vs |
| 81252-9 | Variant code (ClinVar etc.) | |
| 53037-8 | Clinical significance | (pathogenic / likely / VUS …) |

For a typical somatic point mutation report, the minimum useful set is: fixed `code`, then components for gene studied (48018-6), c.HGVS (48004-6), p.HGVS (48005-3), and genomic source class (48002-0 = somatic).

## GenomicRegionStudied (Observation → GR `region-studied`)

Describes the genes/regions covered by a targeted panel.

| Element | Card | MS | Binding |
|---|---|---|---|
| code | 1..1 | ✓ | **fixed LOINC 53041-0** "DNA region of interest panel" |
| category | 1..1 | | fixed `laboratory` |

Component slices (fixed LOINC code): `48018-6` gene-studied (HGNC) · `36908-2` gene mutations tested (required HGVS-VS) · `81293-3` genomic ref-sequence · `51959-5` ranges-examined · `92822-6` genomic coord system (LL5323-2).

"""Stage-3 post-pass: collapse multifocal cancer into one Condition, laterality-aware."""
from __future__ import annotations

from core.extraction_merge import _collapse_multifocal_conditions
from core.schemas import MergedCandidate, SourceRef


def _cond(name, body_site=None, negated=False, doc="d1", sents=(1,)):
    item = {"name": name, "negated": negated}
    if body_site is not None:
        item["body_site"] = body_site
    return MergedCandidate(resource_type="Condition", item=item,
                           source_refs=[SourceRef(document_id=doc, source_sentences=list(sents))])


def test_multifocal_same_organ_collapses_with_unioned_body_site():
    out = _collapse_multifocal_conditions([
        _cond("ductal carcinoma in situ", ["right breast"], sents=(1,)),
        _cond("ductal carcinoma in situ", ["breast", "6:00 site"], sents=(2,)),
        _cond("ductal carcinoma in situ", ["breast", "9:00 site"], sents=(3,)),
    ])
    assert len(out) == 1
    assert out[0].item["body_site"] == ["right breast", "breast", "6:00 site", "9:00 site"]
    assert len(out[0].source_refs) == 3  # all foci's citations preserved


def test_bilateral_stays_separate():
    out = _collapse_multifocal_conditions([
        _cond("carcinoma", ["left breast"]),
        _cond("carcinoma", ["right breast"]),
    ])
    assert len(out) == 2


def test_distinct_names_not_merged():
    out = _collapse_multifocal_conditions([
        _cond("ductal carcinoma in situ", ["breast"]),
        _cond("lobular carcinoma in situ", ["breast"]),
    ])
    assert len(out) == 2


def test_negated_left_untouched():
    out = _collapse_multifocal_conditions([
        _cond("CHF", negated=True),
        _cond("CHF", negated=False),
    ])
    assert len(out) == 2  # negated assertion not merged into the affirmed one


def test_no_laterality_merges_into_sided_focus():
    out = _collapse_multifocal_conditions([
        _cond("seminoma", ["right testis"]),
        _cond("seminoma", ["testis"]),
    ])
    assert len(out) == 1


def test_non_condition_passthrough():
    obs = MergedCandidate(resource_type="Observation", item={"name": "x"}, source_refs=[])
    out = _collapse_multifocal_conditions([obs])
    assert out == [obs]

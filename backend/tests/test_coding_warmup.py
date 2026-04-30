import numpy as np

import core.coding as coding


class FakeModel:
    model_name = "fake-model"

    def __init__(self):
        self.encoded: list[list[str]] = []

    def encode(self, texts: list[str]) -> np.ndarray:
        self.encoded.append(texts)
        return np.ones((len(texts), 1), dtype=np.float32)


class FakeStore:
    def __init__(self):
        self.systems: list[str] = []

    def preload(self, systems=None, *, strict=True):
        self.systems = list(systems or coding.SYSTEM_META_COLS)
        return {system: i + 1 for i, system in enumerate(self.systems)}, ()


def test_warmup_loads_embedding_model_and_indexes(monkeypatch):
    model = FakeModel()
    store = FakeStore()
    monkeypatch.setattr(coding, "_get_defaults", lambda: (store, model))
    monkeypatch.setattr(
        coding,
        "SYSTEM_META_COLS",
        {"snomed": {}, "rxnorm": {}, "loinc": {}, "icd10": {}},
    )

    result = coding.warmup()

    assert model.encoded == [["warmup"]]
    assert store.systems == ["snomed", "rxnorm", "loinc", "icd10"]
    assert result.model_name == "fake-model"
    assert result.loaded_indexes == {"snomed": 1, "rxnorm": 2, "loinc": 3, "icd10": 4}
    assert result.missing_indexes == ()

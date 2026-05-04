import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from fhir.local_bundle import load_demo_data, load_bundle, BUNDLE_PATH
from fhir.models import Document, PatientContext


@pytest.fixture(scope="session")
def demo_bundle_raw() -> dict:
    return load_bundle()


@pytest.fixture(scope="session")
def demo_data() -> tuple[PatientContext, list[Document]]:
    return load_demo_data()


@pytest.fixture(scope="session")
def patient_context(demo_data) -> PatientContext:
    return demo_data[0]


@pytest.fixture(scope="session")
def demo_documents(demo_data) -> list[Document]:
    return demo_data[1]

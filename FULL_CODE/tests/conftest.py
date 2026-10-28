from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


@pytest.fixture(scope="session")
def data_dir():
    if not (DATA / "feedback.csv").exists():
        pytest.skip("pack data not present in data/ (it is not committed; see README)")
    return DATA

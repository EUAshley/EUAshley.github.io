import pytest

from engine import db


@pytest.fixture
def session():
    db.init_engine("sqlite:///:memory:")
    db.create_all()
    s = db.new_session()
    yield s
    s.close()

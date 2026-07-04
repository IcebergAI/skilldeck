from src.discount import apply_discount


def test_basic_discount():
    assert apply_discount(100.0, 10) == 90.0

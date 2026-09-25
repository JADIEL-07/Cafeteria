import pytest

from app.utils.money import basis_points, format_money, format_qty, line_cost, parse_money, parse_quantity


def test_format_money():
    assert format_money(0) == "$0.00"
    assert format_money(1695) == "$16.95"
    assert format_money(384520) == "$3,845.20"
    assert format_money(-250) == "-$2.50"
    assert format_money(250, signed=True) == "+$2.50"
    assert format_money(0, signed=True) == "$0.00"


@pytest.mark.parametrize(
    "text, cents",
    [("12.50", 1250), ("12,50", 1250), ("$1,250.00", 125000), ("0.005", 1), ("7", 700), (" 3.10 ", 310)],
)
def test_parse_money_ok(text, cents):
    assert parse_money(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "-5", "nan", "inf", "1e999999", "99999999999999999999", "1000000.01"])
def test_parse_money_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_money(text)


def test_parse_money_zero_rules():
    assert parse_money("0") == 0
    with pytest.raises(ValueError):
        parse_money("0", allow_zero=False)


def test_parse_quantity():
    assert parse_quantity("2,5") == 2.5
    for huge in ("1e999999", "5000000", "nan"):
        with pytest.raises(ValueError):
            parse_quantity(huge)
    with pytest.raises(ValueError):
        parse_quantity("0")
    assert parse_quantity("0", allow_zero=True) == 0
    with pytest.raises(ValueError):
        parse_quantity("-1")


def test_basis_points_rounds_half_up():
    assert basis_points(1180, 750) == 89  # 88.5 -> 89
    assert basis_points(1269, 240) == 30  # 30.456 -> 30
    assert basis_points(0, 750) == 0


def test_line_cost_and_format_qty():
    assert line_cost(0.75, 3400) == 2550
    assert line_cost(22.0, 2850) == 62700
    assert format_qty(5.0) == "5"
    assert format_qty(4.5) == "4.5"
    assert format_qty(0.2500001) == "0.25"

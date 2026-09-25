"""Registra los fixtures de cada modelo (ver tests/fixtures/)."""
pytest_plugins = [
    "tests.fixtures.application",
    "tests.fixtures.users",
    "tests.fixtures.catalog",
    "tests.fixtures.inventory",
    "tests.fixtures.coupons",
    "tests.fixtures.carts",
    "tests.fixtures.orders",
    "tests.fixtures.ledger",
    "tests.fixtures.favorites",
]

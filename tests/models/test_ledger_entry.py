"""Modelo LedgerEntry: libro de movimientos, resumen (invertido / recuperado / ganancia) y gráficos."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import DomainError, LedgerEntry
from tests.fixtures.ledger import DAY


class TestPresentation:
    def test_tx_id_is_zero_padded(self, sale_entry):
        assert sale_entry.tx_id == f"TX-{sale_entry.id:05d}"

    @pytest.mark.parametrize(
        "concept, label",
        [("venta", "Venta"), ("reembolso", "Reembolso"), ("compra_inventario", "Compra de inventario"), ("ajuste", "Ajuste manual"), ("otro", "otro")],
    )
    def test_concept_label(self, concept, label):
        assert LedgerEntry(concept=concept).concept_label == label

    @pytest.mark.parametrize("method, label", [("efectivo", "Efectivo en barra"), ("tarjeta", "Tarjeta / Apple Pay"), (None, "—"), ("cheque", "—")])
    def test_method_label(self, method, label):
        assert LedgerEntry(method=method).method_label == label

    def test_net_effect_of_an_income_is_amount_minus_fee(self, sale_entry):
        assert sale_entry.net_cents == 976

    def test_net_effect_of_an_expense_is_negative(self, refund_entry, purchase_entry):
        assert (refund_entry.net_cents, purchase_entry.net_cents) == (-1000, -5000)

    def test_status_badges(self, ledger_factory, refund_entry, purchase_entry, adjustment_in_entry):
        assert ledger_factory("ingreso", "venta", 100, method="tarjeta").status == ("Confirmado", "ok")
        assert ledger_factory("ingreso", "venta", 100, method="efectivo").status == ("Efectivo confirmado", "ok")
        assert refund_entry.status == ("Reembolsado", "bad")
        assert purchase_entry.status == ("Compra registrada", "warn")
        assert adjustment_in_entry.status == ("Ajuste manual", "neutral")

    def test_repr(self, sale_entry):
        assert repr(sale_entry) == f"<LedgerEntry TX-{sale_entry.id:05d} venta 1000>"


class TestRecordFromOrders:
    def test_paying_an_order_records_the_sale(self, card_order):
        entry = db.session.scalar(select(LedgerEntry).where(LedgerEntry.order_id == card_order.id))
        assert (entry.kind, entry.concept, entry.amount_cents, entry.fee_cents, entry.method) == ("ingreso", "venta", 1484, 36, "tarjeta")
        assert entry.party == "Elena Rostova"
        assert entry.description == f"Pedido {card_order.code}"
        assert entry.order == card_order

    def test_cancelling_a_paid_order_records_the_refund(self, cancelled_paid_order, barista_user):
        refund = db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "reembolso"))
        assert (refund.kind, refund.amount_cents, refund.fee_cents, refund.method) == ("egreso", 1484, 0, "tarjeta")
        assert refund.description == f"Reembolso del pedido {cancelled_paid_order.code}"
        assert refund.created_by == barista_user

    def test_pending_cash_orders_leave_no_entry(self, cash_order):
        assert db.session.scalar(select(LedgerEntry.id)) is None

    def test_purchases_record_an_expense(self, purchase_movement, coffee_item, admin_user):
        entry = db.session.scalar(select(LedgerEntry).where(LedgerEntry.movement_id == purchase_movement.id))
        assert (entry.kind, entry.concept, entry.amount_cents, entry.party, entry.method) == ("egreso", "compra_inventario", 14500, "Proveedor X", None)
        assert entry.description == "Compra: Café en Grano Etiopía (5 kg)"
        assert entry.created_by == admin_user


class TestRecordAdjustment:
    def test_valid_adjustment(self, admin_user):
        entry = LedgerEntry.record_adjustment("egreso", 2550, "  Faltante de caja  ", method="efectivo", user=admin_user)
        assert (entry.kind, entry.concept, entry.amount_cents, entry.method) == ("egreso", "ajuste", 2550, "efectivo")
        assert (entry.description, entry.party, entry.created_by) == ("Faltante de caja", "Administrador Moka", admin_user)
        assert entry.id is not None                      # se confirmó en la base

    def test_without_user_and_with_custom_time(self, app):
        when = datetime(2026, 1, 2, 3, 4)
        entry = LedgerEntry.record_adjustment("ingreso", 500, "Propina", at=when)
        assert (entry.party, entry.created_by_id, entry.created_at) == (None, None, when)

    def test_unknown_method_becomes_none(self, app):
        assert LedgerEntry.record_adjustment("ingreso", 100, "Otro medio", method="cheque").method is None

    def test_long_descriptions_are_truncated(self, app):
        assert len(LedgerEntry.record_adjustment("ingreso", 100, "x" * 500).description) == 240

    @pytest.mark.parametrize(
        "kind, amount, description, message",
        [("regalo", 100, "Motivo", "Tipo"), ("ingreso", 0, "Motivo", "mayor que cero"), ("egreso", -5, "Motivo", "mayor que cero"), ("ingreso", 100, "", "motivo"), ("ingreso", 100, "ab", "motivo"), ("ingreso", 100, "   ", "motivo")],
    )
    def test_validation(self, app, kind, amount, description, message):
        with pytest.raises(DomainError, match=message):
            LedgerEntry.record_adjustment(kind, amount, description)
        assert db.session.scalar(select(LedgerEntry.id)) is None


class TestSummary:
    def test_empty_ledger(self, app):
        summary = LedgerEntry.summary()
        for key in ("gross_sales", "fees", "refunds", "invested", "adjustments", "recovered", "profit", "sales_count", "purchases_count", "tarjeta_net", "efectivo_net"):
            assert summary[key] == 0, key
        assert summary["recovery_pct"] is None and summary["margin_pct"] is None

    def test_a_full_day(self, ledger_dataset):
        summary = LedgerEntry.summary(ledger_dataset.start, ledger_dataset.end)
        for key, value in ledger_dataset.expected.items():
            assert summary[key] == value, key

    def test_formulas_hold(self, ledger_dataset):
        s = LedgerEntry.summary(ledger_dataset.start, ledger_dataset.end)
        assert s["recovered"] == s["gross_sales"] - s["fees"] - s["refunds"]
        assert s["profit"] == s["recovered"] - s["invested"] + s["adjustments"]
        assert s["tarjeta_net"] + s["efectivo_net"] == s["recovered"] + s["adjustments"]

    def test_without_bounds_counts_everything(self, ledger_dataset):
        s = LedgerEntry.summary()
        assert s["gross_sales"] == 5000 + 9999 + 7777

    def test_start_is_inclusive_and_end_is_exclusive(self, ledger_factory):
        ledger_factory(amount_cents=100, created_at=DAY)                          # justo al inicio: cuenta
        ledger_factory(amount_cents=200, created_at=DAY + timedelta(days=1))      # justo al final: no cuenta
        assert LedgerEntry.summary(DAY, DAY + timedelta(days=1))["gross_sales"] == 100

    def test_only_a_lower_or_an_upper_bound(self, ledger_dataset):
        assert LedgerEntry.summary(start=DAY + timedelta(days=1))["gross_sales"] == 7777
        assert LedgerEntry.summary(end=DAY)["gross_sales"] == 9999

    def test_percentages_are_none_when_they_make_no_sense(self, ledger_factory):
        ledger_factory("egreso", "compra_inventario", 1000, method=None)
        s = LedgerEntry.summary()
        assert s["recovery_pct"] == 0.0            # se invirtió pero nada se recuperó
        assert s["margin_pct"] is None             # sin ingresos no hay margen

    def test_sales_only_have_no_recovery_percentage(self, ledger_factory):
        ledger_factory("ingreso", "venta", 1000, method="tarjeta")
        s = LedgerEntry.summary()
        assert s["recovery_pct"] is None and s["margin_pct"] == 100.0

    def test_unknown_methods_do_not_break_the_totals(self, ledger_factory):
        ledger_factory("ingreso", "venta", 1000, method="cheque")
        s = LedgerEntry.summary()
        assert s["gross_sales"] == 1000 and s["tarjeta_net"] == 0 and s["efectivo_net"] == 0


class TestCashDrawer:
    def test_opening_float_plus_net_cash(self, ledger_dataset):
        drawer = LedgerEntry.cash_drawer(ledger_dataset.start, ledger_dataset.end)
        assert drawer == {"opening": 20000, "collected": 1800, "expected": 21800}

    def test_empty_day(self, app):
        assert LedgerEntry.cash_drawer(DAY, DAY + timedelta(days=1)) == {"opening": 20000, "collected": 0, "expected": 20000}

    def test_opening_float_comes_from_the_configuration(self, app):
        app.config["CASH_FLOAT_CENTS"] = 5000
        assert LedgerEntry.cash_drawer(DAY, DAY + timedelta(days=1))["expected"] == 5000


class TestHourlySales:
    def test_slot_labels(self, app):
        assert [s["label"] for s in LedgerEntry.hourly_sales()] == ["06-08", "08-10", "10-12", "12-14", "14-16", "16-18", "18-20", "20-22"]

    def test_empty_ledger_has_zero_heights(self, app):
        assert all(s["tarjeta"] == s["efectivo"] == s["tarjeta_pct"] == s["efectivo_pct"] == 0 for s in LedgerEntry.hourly_sales())

    def test_full_day(self, ledger_dataset):
        slots = {s["label"]: s for s in LedgerEntry.hourly_sales(ledger_dataset.start, ledger_dataset.end)}
        assert (slots["06-08"]["tarjeta"], slots["06-08"]["tarjeta_pct"]) == (1000, 50)
        assert (slots["08-10"]["tarjeta"], slots["08-10"]["tarjeta_pct"]) == (2000, 100)
        assert (slots["08-10"]["efectivo"], slots["08-10"]["efectivo_pct"]) == (1500, 75)
        assert (slots["20-22"]["efectivo"], slots["20-22"]["efectivo_pct"]) == (500, 25)
        assert slots["10-12"]["tarjeta"] == slots["10-12"]["efectivo"] == 0

    @pytest.mark.parametrize("hour, label", [(0, "06-08"), (5, "06-08"), (6, "06-08"), (7, "06-08"), (8, "08-10"), (21, "20-22"), (22, "20-22"), (23, "20-22")])
    def test_out_of_range_hours_go_to_the_edge_slots(self, ledger_factory, hour, label):
        ledger_factory(amount_cents=700, method="efectivo", created_at=DAY + timedelta(hours=hour, minutes=30))
        slots = {s["label"]: s for s in LedgerEntry.hourly_sales()}
        assert slots[label]["efectivo"] == 700

    def test_only_sales_with_a_known_method_are_counted(self, ledger_factory):
        ledger_factory("egreso", "reembolso", 900, method="efectivo")
        ledger_factory("ingreso", "ajuste", 900, method="efectivo")
        ledger_factory("ingreso", "venta", 900, method=None)
        ledger_factory("ingreso", "venta", 900, method="cheque")
        assert all(s["efectivo"] == s["tarjeta"] == 0 for s in LedgerEntry.hourly_sales())


class TestListing:
    @pytest.fixture()
    def entries(self, ledger_dataset):
        return ledger_dataset

    def test_newest_first(self, entries):
        stamps = [e.created_at for e in db.session.scalars(LedgerEntry.entries_query())]
        assert stamps == sorted(stamps, reverse=True)

    def test_period_filter(self, entries):
        assert len(db.session.scalars(LedgerEntry.entries_query(entries.start, entries.end)).all()) == 10

    @pytest.mark.parametrize("method, count", [("efectivo", 4), ("tarjeta", 4)])
    def test_method_filter(self, entries, method, count):
        rows = db.session.scalars(LedgerEntry.entries_query(entries.start, entries.end, method=method)).all()
        assert len(rows) == count and all(e.method == method for e in rows)

    @pytest.mark.parametrize("concept, count", [("venta", 4), ("reembolso", 2), ("compra_inventario", 2), ("ajuste", 2)])
    def test_concept_filter(self, entries, concept, count):
        rows = db.session.scalars(LedgerEntry.entries_query(entries.start, entries.end, concept=concept)).all()
        assert len(rows) == count and all(e.concept == concept for e in rows)

    def test_unknown_filters_are_ignored(self, entries):
        assert len(db.session.scalars(LedgerEntry.entries_query(entries.start, entries.end, method="cheque", concept="raro")).all()) == 10

    def test_pagination(self, entries):
        page = LedgerEntry.transactions(entries.start, entries.end, per_page=4, page=1)
        assert (page.total, page.pages, len(page.items)) == (10, 3, 4)
        assert len(LedgerEntry.transactions(entries.start, entries.end, per_page=4, page=3).items) == 2
        assert LedgerEntry.transactions(entries.start, entries.end, per_page=4, page=9).items == []     # sin error

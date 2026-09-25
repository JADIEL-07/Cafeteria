"""Modelo Order: creación desde el carrito, ciclo de vida, cancelaciones y consultas de la pizarra."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Cart, DomainError, InsufficientStock, InventoryItem, InventoryMovement, LedgerEntry, Order, OrderStateError
from app.models.order import BOARD_FILTERS, STAGES

T0 = datetime(2026, 3, 10, 9, 0)


def reload(order):
    db.session.expire_all()
    return db.session.get(Order, order.id)


def stock(item):
    db.session.expire_all()
    return db.session.get(InventoryItem, item.id).stock


def order_count():
    return db.session.scalar(select(func.count(Order.id)))


class TestCreateFromCart:
    def test_card_order_is_paid_immediately(self, card_order, client_user, kitchen):
        assert card_order.code == f"MK-{8000 + card_order.id}"
        assert (card_order.status, card_order.payment_status, card_order.payment_method) == ("nuevo", "pagado", "tarjeta")
        assert (card_order.subtotal_cents, card_order.discount_cents, card_order.tax_cents, card_order.total_cents) == (1380, 0, 104, 1484)
        assert (card_order.fee_cents, card_order.beans_earned) == (36, 14)         # 2.4 % de $14.84; 1 grano por $1
        assert card_order.transaction_ref == f"CH-{card_order.id:05d}"
        assert card_order.user == client_user and client_user.beans == 14
        assert card_order.paid_at is not None and card_order.accepted_at is None
        assert (card_order.fulfillment, card_order.table_number) == ("barra", None)

    def test_cash_order_waits_for_payment(self, cash_order, client_user):
        assert (cash_order.status, cash_order.payment_status, cash_order.payment_method) == ("nuevo", "pendiente", "efectivo")
        assert (cash_order.fee_cents, cash_order.beans_earned, cash_order.paid_at, cash_order.transaction_ref) == (0, 0, None, None)
        assert client_user.beans == 0
        assert db.session.scalar(select(LedgerEntry.id)) is None

    def test_pickup_pin_is_four_digits(self, order_factory):
        pins = {order_factory("efectivo", drinks=0, pastries=1).pickup_pin for _ in range(8)}
        assert all(len(pin) == 4 and 1000 <= int(pin) <= 9999 for pin in pins)

    def test_items_are_a_snapshot_of_the_cart(self, card_order, kitchen):
        drink_item, pastry_item = card_order.items
        assert (drink_item.name, drink_item.qty, drink_item.unit_price_cents, drink_item.line_total_cents) == ("Caramel Macchiato Insignia", 1, 590, 590)
        assert drink_item.options_text == "Mediano • Caliente • Leche de Avena Barista • Normal (100%)"
        assert (pastry_item.name, pastry_item.qty, pastry_item.unit_price_cents, pastry_item.line_total_cents) == ("Croissant de Almendras", 2, 395, 790)
        assert pastry_item.product == kitchen.pastry
        assert card_order.item_count == 3

    def test_snapshot_survives_catalog_changes(self, card_order, kitchen):
        kitchen.drink.name, kitchen.drink.price_cents = "Nombre nuevo", 9999
        db.session.commit()
        item = reload(card_order).items[0]
        assert (item.name, item.unit_price_cents) == ("Caramel Macchiato Insignia", 590)

    def test_coupon_lowers_the_total_and_counts_a_use(self, order_factory, fixed_coupon):
        order = order_factory("tarjeta", coupon=True)
        assert (order.discount_cents, order.tax_cents, order.total_cents, order.coupon_code) == (200, 89, 1269, "CAFELOVER")
        assert (order.fee_cents, order.beans_earned) == (30, 12)
        assert fixed_coupon.uses_count == 1

    def test_custom_timestamp_is_used_for_the_events(self, order_factory):
        card = order_factory("tarjeta", at=T0)
        assert (card.created_at, card.paid_at) == (T0, T0)
        cash = order_factory("efectivo", at=T0)
        assert (cash.created_at, cash.paid_at) == (T0, None)

    def test_updated_at_moves_when_the_order_changes(self, order_factory):
        order = order_factory("efectivo", at=T0)
        order.confirm_payment(at=T0)
        assert reload(order).updated_at > T0

    def test_table_service(self, order_factory):
        order = order_factory("efectivo", fulfillment="mesa", table="  4  ")
        assert (order.fulfillment, order.table_number) == ("mesa", "4")

    def test_table_number_is_truncated(self, order_factory):
        assert order_factory("efectivo", fulfillment="mesa", table="1234567890123").table_number == "1234567890"

    def test_unknown_fulfillment_falls_back_to_counter_pickup(self, order_factory):
        assert order_factory("efectivo", fulfillment="dron").fulfillment == "barra"

    @pytest.mark.parametrize("notes, expected", [("  Sin azúcar  ", "Sin azúcar"), ("x" * 300, "x" * 200), ("   ", None), (None, None)])
    def test_notes(self, order_factory, notes, expected):
        assert order_factory("efectivo", notes=notes).notes == expected

    def test_requires_a_user(self, cart_summary):
        with pytest.raises(DomainError, match="Inicia sesión"):
            Order.create_from_cart(None, cart_summary, "tarjeta")

    def test_requires_items(self, client_user):
        with pytest.raises(DomainError, match="vacío"):
            Order.create_from_cart(client_user, Cart(store={}).summary(), "tarjeta")

    @pytest.mark.parametrize("method", ["bitcoin", "", None])
    def test_requires_a_known_payment_method(self, client_user, cart_summary, method):
        with pytest.raises(DomainError, match="método de pago"):
            Order.create_from_cart(client_user, cart_summary, method)

    def test_table_service_requires_a_table(self, client_user, cart_summary):
        with pytest.raises(DomainError, match="número de mesa"):
            Order.create_from_cart(client_user, cart_summary, "tarjeta", "mesa", "  ")

    def test_failed_creation_leaves_nothing_behind(self, client_user, cart_summary):
        with pytest.raises(DomainError):
            Order.create_from_cart(client_user, cart_summary, "bitcoin")
        assert order_count() == 0
        assert db.session.scalar(select(LedgerEntry.id)) is None

    def test_repr(self, card_order):
        assert repr(card_order) == f"<Order {card_order.code}>"


class TestStages:
    @pytest.mark.parametrize(
        "fixture, stage",
        [
            ("cash_order", "pending_payment"),
            ("card_order", "paid"),
            ("accepted_order", "in_bar"),
            ("ready_order", "ready"),
            ("delivered_order", "delivered"),
            ("cancelled_paid_order", "cancelled"),
            ("cancelled_unpaid_order", "cancelled"),
        ],
    )
    def test_stage(self, request, fixture, stage):
        order = request.getfixturevalue(fixture)
        assert order.stage == stage
        assert order.stage_info is STAGES[stage]

    def test_every_stage_has_the_data_the_views_need(self):
        assert set(STAGES) == {"pending_payment", "paid", "in_bar", "ready", "delivered", "cancelled"}
        for info in STAGES.values():
            assert set(info) == {"label", "short", "icon", "badge", "tile"}

    @pytest.mark.parametrize(
        "fixture, is_open, can_accept, can_cancel, can_confirm",
        [
            ("cash_order", True, False, True, True),
            ("card_order", True, True, True, False),
            ("accepted_order", True, False, False, False),
            ("ready_order", True, False, False, False),
            ("delivered_order", False, False, False, False),
            ("cancelled_paid_order", False, False, False, False),
            ("cancelled_unpaid_order", False, False, False, False),
        ],
    )
    def test_action_flags(self, request, fixture, is_open, can_accept, can_cancel, can_confirm):
        order = request.getfixturevalue(fixture)
        assert (order.is_open, order.can_accept, order.can_cancel, order.can_confirm_payment) == (is_open, can_accept, can_cancel, can_confirm)

    def test_labels(self, card_order, cash_order, order_factory):
        assert card_order.payment_method_label == "Tarjeta / Apple Pay"
        assert cash_order.payment_method_label == "Efectivo en barra"
        assert card_order.fulfillment_label == "Retiro en barra"
        assert order_factory("efectivo", fulfillment="mesa", table="4").fulfillment_label == "Servir en mesa · Mesa 4"

    def test_customer_name(self, card_order):
        assert card_order.customer_name == "Elena Rostova"
        assert Order().customer_name == "Cliente"

    def test_board_filters_cover_the_documented_views(self):
        assert list(BOARD_FILTERS) == ["activas", "pendiente", "pagado", "en_barra", "listo", "cerrados"]


class TestEvents:
    def test_new_card_order(self, card_order):
        assert [label for label, _, _ in card_order.events] == ["Pedido recibido", f"Pago confirmado con tarjeta · CH-{card_order.id:05d}"]

    def test_pending_cash_order(self, cash_order):
        assert [label for label, _, _ in cash_order.events] == ["Pedido recibido"]

    def test_full_lifecycle_in_chronological_order(self, order_factory, barista_user):
        order = order_factory("efectivo", at=T0)
        order.confirm_payment(by=barista_user, at=T0 + timedelta(minutes=1))
        order.accept(barista_user, at=T0 + timedelta(minutes=2))
        order.mark_ready(at=T0 + timedelta(minutes=8))
        order.mark_delivered(at=T0 + timedelta(minutes=10))
        events = order.events
        assert [label for label, _, _ in events] == [
            "Pedido recibido",
            f"Pago confirmado en barra · EF-{order.id:05d}",
            "Aceptado e iniciada la elaboración por Mateo Gómez",
            "Listo para retiro",
            "Entregado al cliente",
        ]
        assert [at for _, at, _ in events] == [T0 + timedelta(minutes=m) for m in (0, 1, 2, 8, 10)]
        assert all(icon for _, _, icon in events)

    def test_cancellations(self, cancelled_paid_order, cancelled_unpaid_order):
        assert cancelled_paid_order.events[-1][0] == "Cancelado · reembolso emitido"
        assert cancelled_unpaid_order.events[-1][0] == "Cancelado"


class TestConfirmPayment:
    def test_cash_payment(self, cash_order, barista_user, client_user):
        cash_order.confirm_payment(by=barista_user, at=T0)
        order = reload(cash_order)
        assert (order.payment_status, order.paid_at, order.fee_cents, order.beans_earned) == ("pagado", T0, 0, 14)
        assert order.transaction_ref == f"EF-{order.id:05d}"
        assert client_user.beans == 14
        sale = db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "venta"))
        assert (sale.method, sale.fee_cents, sale.amount_cents, sale.created_by, sale.created_at) == ("efectivo", 0, 1484, barista_user, T0)

    def test_confirming_twice_does_not_duplicate_anything(self, cash_order, client_user):
        cash_order.confirm_payment()
        with pytest.raises(OrderStateError, match="pendiente de pago"):
            cash_order.confirm_payment()
        assert db.session.scalar(select(func.count(LedgerEntry.id))) == 1
        assert client_user.beans == 14

    def test_already_paid_card_orders_cannot_be_confirmed(self, card_order):
        with pytest.raises(OrderStateError):
            card_order.confirm_payment()

    def test_cancelled_orders_cannot_be_confirmed(self, cancelled_unpaid_order):
        with pytest.raises(OrderStateError):
            cancelled_unpaid_order.confirm_payment()


class TestIngredientNeeds:
    def test_recipe_plus_chosen_options(self, card_order, kitchen):
        assert card_order.ingredient_needs() == {kitchen.coffee.id: 0.018, kitchen.cup.id: 1, kitchen.milk.id: 0.25, kitchen.butter.id: 0.1}

    def test_scales_with_quantity(self, order_factory, kitchen):
        needs = order_factory("tarjeta", drinks=2, pastries=0).ingredient_needs()
        assert needs == {kitchen.coffee.id: 0.036, kitchen.cup.id: 2, kitchen.milk.id: 0.5}

    def test_extras_add_their_own_consumption(self, client_user, kitchen):
        cart = Cart(store={})
        cart.add(kitchen.drink, extras=[kitchen.modifiers.extra["shot"].id])
        order = Order.create_from_cart(client_user, cart.summary(), "tarjeta")
        assert order.ingredient_needs()[kitchen.coffee.id] == 0.036

    def test_options_without_inventory_link_consume_nothing_extra(self, client_user, kitchen):
        cart = Cart(store={})
        cart.add(kitchen.drink, selections={"milk": kitchen.modifiers.milk["almond"].id})
        order = Order.create_from_cart(client_user, cart.summary(), "tarjeta")
        assert kitchen.milk.id not in order.ingredient_needs()

    def test_products_without_recipe_need_nothing(self, client_user, product_factory):
        cart = Cart(store={})
        cart.add(product_factory(name="Sin receta"))
        assert Order.create_from_cart(client_user, cart.summary(), "tarjeta").ingredient_needs() == {}

    def test_deleted_options_are_ignored(self, card_order, kitchen):
        db.session.delete(kitchen.modifiers.milk["oat"])
        db.session.commit()
        assert kitchen.milk.id not in reload(card_order).ingredient_needs()


class TestAccept:
    def test_starts_preparation_and_consumes_the_stock(self, card_order, kitchen, barista_user):
        card_order.accept(barista_user, at=T0)
        order = reload(card_order)
        assert (order.status, order.accepted_by, order.accepted_at) == ("en_barra", barista_user, T0)
        assert stock(kitchen.coffee) == pytest.approx(9.982)
        assert stock(kitchen.cup) == 499
        assert stock(kitchen.milk) == pytest.approx(23.75)
        assert stock(kitchen.butter) == pytest.approx(19.9)

    def test_consumption_is_logged_against_the_order(self, card_order, barista_user):
        card_order.accept(barista_user, at=T0)
        moves = db.session.scalars(select(InventoryMovement)).all()
        assert len(moves) == 4
        assert all(m.kind == "consumo" and m.reference == card_order.code and m.user_id == barista_user.id and m.created_at == T0 for m in moves)
        assert all(m.qty < 0 for m in moves)

    def test_accepting_without_a_user_is_allowed(self, card_order):
        card_order.accept(None)
        assert reload(card_order).accepted_by_id is None

    def test_unpaid_orders_are_blocked(self, cash_order, kitchen, barista_user):
        with pytest.raises(OrderStateError, match="Bloqueado"):
            cash_order.accept(barista_user)
        assert reload(cash_order).status == "nuevo"
        assert stock(kitchen.coffee) == 10
        assert db.session.scalar(select(InventoryMovement.id)) is None

    def test_cannot_accept_twice(self, accepted_order, kitchen, barista_user):
        before = stock(kitchen.coffee)
        with pytest.raises(OrderStateError, match="ya fue procesado"):
            accepted_order.accept(barista_user)
        assert stock(kitchen.coffee) == before

    def test_cancelled_orders_cannot_be_accepted(self, cancelled_paid_order, barista_user):
        with pytest.raises(OrderStateError, match="ya fue procesado"):
            cancelled_paid_order.accept(barista_user)

    def test_missing_stock_blocks_the_order_and_changes_nothing(self, card_order, kitchen, barista_user):
        kitchen.cup.stock = 0
        db.session.commit()
        with pytest.raises(InsufficientStock) as info:
            card_order.accept(barista_user)
        assert [s[0] for s in info.value.shortages] == ["Vasos Compostables 12oz"]
        assert reload(card_order).status == "nuevo"
        assert stock(kitchen.coffee) == 10 and stock(kitchen.milk) == 24     # nada se descontó
        assert db.session.scalar(select(InventoryMovement.id)) is None


class TestTransitions:
    def test_mark_ready_then_delivered(self, accepted_order):
        accepted_order.mark_ready(at=T0)
        assert (reload(accepted_order).status, reload(accepted_order).ready_at) == ("listo", T0)
        accepted_order.mark_delivered(at=T0 + timedelta(minutes=2))
        order = reload(accepted_order)
        assert (order.status, order.delivered_at) == ("entregado", T0 + timedelta(minutes=2))

    def test_cannot_deliver_before_it_is_ready(self, accepted_order):
        with pytest.raises(OrderStateError, match="listo"):
            accepted_order.mark_delivered()
        assert reload(accepted_order).status == "en_barra"

    def test_ready_needs_an_order_in_the_bar(self, order_factory):
        fresh = order_factory("tarjeta")
        with pytest.raises(OrderStateError, match="en barra"):
            fresh.mark_ready()
        with pytest.raises(OrderStateError, match="listo"):
            fresh.mark_delivered()

    def test_closed_orders_do_not_move(self, delivered_order):
        with pytest.raises(OrderStateError):
            delivered_order.mark_ready()
        with pytest.raises(OrderStateError):
            delivered_order.mark_delivered()

    def test_claim_is_an_atomic_compare_and_set(self, card_order):
        assert card_order._claim("nuevo", "pendiente", status="en_barra") is False      # pago distinto
        assert card_order._claim("listo", status="entregado") is False                 # estado distinto
        assert reload(card_order).status == "nuevo"
        assert card_order._claim("nuevo", "pagado", status="en_barra") is True
        assert card_order._claim("nuevo", "pagado", status="en_barra") is False        # ya cambió
        assert reload(card_order).status == "en_barra"


class TestCancel:
    def test_unpaid_order_has_no_money_movement(self, cash_order):
        cash_order.cancel(reason="  No se presentó  ", at=T0)
        order = reload(cash_order)
        assert (order.status, order.payment_status, order.cancel_reason, order.cancelled_at) == ("cancelado", "pendiente", "No se presentó", T0)
        assert db.session.scalar(select(LedgerEntry.id)) is None

    def test_paid_order_is_refunded_and_beans_are_reverted(self, card_order, client_user, barista_user):
        assert client_user.beans == 14
        card_order.cancel(by=barista_user, reason="Cliente canceló")
        order = reload(card_order)
        assert (order.status, order.payment_status) == ("cancelado", "reembolsado")
        assert client_user.beans == 0
        refund = db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "reembolso"))
        assert (refund.amount_cents, refund.created_by) == (1484, barista_user)
        assert LedgerEntry.summary()["refunds"] == 1484

    def test_reverting_beans_never_goes_below_zero(self, card_order, client_user):
        client_user.beans = 5
        db.session.commit()
        card_order.cancel()
        assert client_user.beans == 0

    @pytest.mark.parametrize("reason, expected", [("x" * 500, "x" * 200), ("   ", None), (None, None)])
    def test_reason_is_cleaned(self, cash_order, reason, expected):
        cash_order.cancel(reason=reason)
        assert reload(cash_order).cancel_reason == expected

    def test_cannot_cancel_once_preparation_started(self, accepted_order):
        with pytest.raises(OrderStateError, match="en preparación"):
            accepted_order.cancel()
        assert reload(accepted_order).status == "en_barra"

    def test_cannot_cancel_twice_without_a_second_refund(self, cancelled_paid_order):
        with pytest.raises(OrderStateError):
            cancelled_paid_order.cancel()
        assert db.session.scalar(select(func.count(LedgerEntry.id)).where(LedgerEntry.concept == "reembolso")) == 1

    def test_cannot_cancel_after_delivery(self, delivered_order):
        with pytest.raises(OrderStateError):
            delivered_order.cancel()
        assert reload(delivered_order).status == "entregado"


class TestArrivalAndNotes:
    @pytest.mark.parametrize("fixture", ["cash_order", "card_order", "accepted_order", "ready_order"])
    def test_customer_can_announce_arrival_while_the_order_is_open(self, request, fixture):
        order = request.getfixturevalue(fixture)
        assert order.arrived_at is None
        order.mark_arrived()
        assert reload(order).arrived_at is not None

    @pytest.mark.parametrize("fixture", ["delivered_order", "cancelled_paid_order"])
    def test_closed_orders_reject_the_arrival(self, request, fixture):
        with pytest.raises(OrderStateError, match="ya no está activo"):
            request.getfixturevalue(fixture).mark_arrived()

    def test_notes_can_change_before_acceptance(self, cash_order):
        cash_order.update_notes("  Poco hielo  ")
        assert reload(cash_order).notes == "Poco hielo"
        cash_order.update_notes("y" * 300)
        assert len(reload(cash_order).notes) == 200
        cash_order.update_notes("   ")
        assert reload(cash_order).notes is None

    def test_notes_are_locked_after_acceptance(self, accepted_order):
        with pytest.raises(OrderStateError, match="antes de que el barista"):
            accepted_order.update_notes("tarde")


@pytest.fixture()
def board_orders(order_factory, barista_user, silver_user):
    """Siete pedidos en todas las etapas, creados con horas fijas (09:00 - 09:09)."""
    def at(minutes):
        return T0 + timedelta(minutes=minutes)

    pending = order_factory("efectivo", at=at(0))
    paid = order_factory("tarjeta", at=at(1))
    in_bar = order_factory("tarjeta", at=at(2))
    in_bar.accept(barista_user, at=at(3))
    ready = order_factory("tarjeta", at=at(4))
    ready.accept(barista_user, at=at(5))
    ready.mark_ready(at=at(11))                       # 6 min de preparación
    delivered = order_factory("tarjeta", at=at(6))
    delivered.accept(barista_user, at=at(7))
    delivered.mark_ready(at=at(17))                   # 10 min de preparación
    delivered.mark_delivered(at=at(18))
    cancelled = order_factory("efectivo", at=at(8))
    cancelled.cancel(at=at(9))
    other = order_factory("tarjeta", at=at(9), user=silver_user)
    return {"pending": pending, "paid": paid, "in_bar": in_bar, "ready": ready, "delivered": delivered, "cancelled": cancelled, "other": other}


class TestBoard:
    def board(self, key="activas", **kwargs):
        return Order.board(key, **kwargs).items

    def test_active_orders_are_a_fifo_queue(self, board_orders):
        o = board_orders
        assert self.board() == [o["pending"], o["paid"], o["in_bar"], o["ready"], o["other"]]

    @pytest.mark.parametrize(
        "key, expected",
        [("pendiente", ["pending"]), ("pagado", ["paid", "other"]), ("en_barra", ["in_bar"]), ("listo", ["ready"])],
    )
    def test_each_filter(self, board_orders, key, expected):
        assert self.board(key) == [board_orders[name] for name in expected]

    def test_closed_orders_show_newest_first(self, board_orders):
        assert self.board("cerrados") == [board_orders["cancelled"], board_orders["delivered"]]

    def test_everything_newest_first(self, board_orders):
        codes = [o.created_at for o in self.board("todas")]
        assert codes == sorted(codes, reverse=True) and len(codes) == 7

    def test_unknown_filter_behaves_like_active(self, board_orders):
        assert self.board("raro") == self.board("activas")

    def test_search_by_code_is_case_insensitive(self, board_orders):
        assert self.board("todas", query=board_orders["paid"].code.lower()) == [board_orders["paid"]]

    def test_search_by_customer_name(self, board_orders):
        assert self.board("todas", query="sofía") == [board_orders["other"]]
        assert len(self.board("todas", query="elena")) == 6

    @pytest.mark.parametrize("query", ["%", "_", "\\", "zzz"])
    def test_search_wildcards_are_literals(self, board_orders, query):
        assert self.board("todas", query=query) == []

    def test_pagination(self, board_orders):
        page = Order.board("todas", per_page=3, page=2)
        assert (page.total, page.pages, len(page.items)) == (7, 3, 3)
        assert Order.board("todas", per_page=3, page=99).items == []

    def test_counts_per_filter(self, board_orders):
        assert Order.filter_counts() == {"activas": 5, "pendiente": 1, "pagado": 2, "en_barra": 1, "listo": 1, "cerrados": 2}

    def test_counts_when_empty(self, app):
        assert Order.filter_counts() == {key: 0 for key in BOARD_FILTERS}

    def test_pending_payments(self, board_orders):
        assert Order.pending_payments() == (1, board_orders["pending"].total_cents)

    def test_no_pending_payments(self, card_order):
        assert Order.pending_payments() == (0, 0)


class TestQueries:
    def test_get_by_code(self, card_order):
        assert Order.get_by_code(card_order.code) == card_order
        assert Order.get_by_code(f"  {card_order.code.lower()} ") == card_order
        assert Order.get_by_code("MK-0") is None
        assert Order.get_by_code(None) is None

    def test_for_user_newest_first_with_limit(self, client_user, silver_user, order_factory):
        first = order_factory("tarjeta", at=T0)
        second = order_factory("efectivo", at=T0 + timedelta(hours=1))
        order_factory("tarjeta", user=silver_user, at=T0 + timedelta(hours=2))
        assert Order.for_user(client_user) == [second, first]
        assert Order.for_user(client_user, limit=1) == [second]
        assert len(Order.for_user(silver_user)) == 1

    def test_average_preparation_time(self, board_orders):
        assert Order.avg_prep_minutes(T0) == 8.0                                   # (6 + 10) / 2
        assert Order.avg_prep_minutes(T0 + timedelta(minutes=12)) == 10.0          # sólo el entregado
        assert Order.avg_prep_minutes(T0 + timedelta(days=1)) is None

    def test_average_preparation_time_without_data(self, app):
        assert Order.avg_prep_minutes(T0) is None

    def test_signature_changes_when_an_order_changes(self, app, order_factory):
        assert Order.signature() == "0:"
        order = order_factory("efectivo", at=T0)
        order.updated_at = T0
        db.session.commit()
        first = Order.signature()
        assert first == f"1:{T0.isoformat()}"
        order.confirm_payment()                       # toca updated_at con la hora real
        assert Order.signature() != first
        order_factory("efectivo", at=T0)
        assert Order.signature().startswith("2:")

    def test_estimated_wait_grows_with_the_queue(self, order_factory, barista_user):
        assert Order.estimated_wait() == (5, 9)
        order_factory("efectivo")                            # sin cobrar: no cuenta
        assert Order.estimated_wait() == (5, 9)
        order_factory("tarjeta")                             # pagado y en cola
        assert Order.estimated_wait() == (7, 11)
        order_factory("tarjeta").accept(barista_user)        # en barra
        assert Order.estimated_wait() == (9, 13)

    def test_estimated_wait_is_capped(self, order_factory):
        for _ in range(13):
            order_factory("tarjeta", drinks=0, pastries=1)
        assert Order.estimated_wait() == (30, 34)

"""Datos iniciales.

* ``seed_catalog``  : categorías, opciones de personalización, insumos (stock 0),
                      productos con receta, cupón y cuentas del equipo.
* ``seed_demo``     : compra inicial de inventario, clientes y pedidos históricos
                      para que el panel y la cartera se vean con vida.
"""
import random
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import select

from .extensions import db
from .models import (
    Cart,
    Category,
    Coupon,
    InventoryItem,
    Modifier,
    Order,
    Product,
    ProductIngredient,
    User,
)
from .models.inventory import CAT_BAKERY, CAT_COFFEE, CAT_MILK, CAT_PACKAGING, MOV_ADJUSTMENT
from .models.user import ROLE_ADMIN, ROLE_BARISTA

# Las fotos viven en app/views/static/img/products/<clave>.jpg (copias locales de tus diseños)
IMAGE_DIR = "img/products"

CATEGORIES = [
    ("cafe", "Café de Especialidad", "coffee", 1),
    ("frios", "Cold Brews & Refrescantes", "ac_unit", 2),
    ("panaderia", "Panadería & Viennoiserie", "bakery_dining", 3),
    ("brunch", "Brunch & Tostas", "brunch_dining", 4),
    ("tes", "Tés & Matcha", "emoji_food_beverage", 5),
    ("granos", "Granos en Bolsa", "inventory_2", 6),
]

# sku, nombre, categoría, unidad, mínimo, costo (centavos), proveedor, compra inicial (demo)
INVENTORY = [
    ("MOK-CF-01", "Café en Grano Etiopía Yirgacheffe", CAT_COFFEE, "kg", 2, 2850, "Importadora Cafés del Valle", 5),
    ("MOK-CF-02", "Café Cold Brew Colombia (molienda gruesa)", CAT_COFFEE, "kg", 1, 2400, "Importadora Cafés del Valle", 2),
    ("MOK-CF-03", "Matcha Ceremonial Uji", CAT_COFFEE, "kg", 0.1, 9500, "Té Kioto Import", 0.3),
    ("MOK-LK-01", "Leche de Avena Barista Edition", CAT_MILK, "briks", 10, 210, "Distribuidora Oatly", 24),
    ("MOK-LK-02", "Leche de Almendras Artesanal", CAT_MILK, "L", 4, 185, "Obrador Moka", 8),
    ("MOK-LK-03", "Leche Entera Fresca", CAT_MILK, "L", 8, 120, "Lácteos La Granja", 16),
    ("MOK-LK-04", "Leche Sin Lactosa", CAT_MILK, "L", 4, 150, "Lácteos La Granja", 8),
    ("MOK-LK-05", "Crema para Batir", CAT_MILK, "L", 1, 450, "Lácteos La Granja", 3),
    ("MOK-OB-01", "Mantequilla AOP Francesa", CAT_BAKERY, "kg", 2, 1420, "Importadora Bretaña", 4),
    ("MOK-OB-02", "Harina de Fuerza", CAT_BAKERY, "kg", 6, 110, "Molino del Valle", 15),
    ("MOK-OB-03", "Chocolate Valrhona Guanaja 70%", CAT_BAKERY, "kg", 0.5, 2640, "Importadora Bretaña", 2),
    ("MOK-OB-04", "Almendra Fileteada", CAT_BAKERY, "kg", 0.5, 1250, "Frutos Secos del Sur", 1),
    ("MOK-OB-05", "Aguacate Hass", CAT_BAKERY, "uds", 8, 90, "Mercado Central", 24),
    ("MOK-OB-06", "Caramelo Salado Casero", CAT_BAKERY, "L", 1, 600, "Obrador Moka", 2),
    ("MOK-OB-07", "Hogaza de Masa Madre", CAT_BAKERY, "uds", 4, 240, "Obrador Moka", 10),
    ("MOK-PKG-01", "Vasos Compostables 12oz", CAT_PACKAGING, "uds", 150, 9, "EcoEnvases", 500),
    ("MOK-PKG-02", "Bolsas Kraft 250g", CAT_PACKAGING, "uds", 10, 35, "EcoEnvases", 30),
]

# (grupo, nombre, descripción, insignia, icono, delta en centavos, por defecto, orden, sku insumo, cantidad de insumo)
MODIFIERS = [
    ("size", "Chico", "12 oz / 355 ml", None, "local_cafe", 0, False, 1, None, 0),
    ("size", "Mediano", "16 oz / 475 ml", "Recomendado", "local_cafe", 50, True, 2, None, 0),
    ("size", "Grande", "20 oz / 590 ml", None, "local_cafe", 100, False, 3, None, 0),
    ("temperature", "Caliente", "Microespuma sedosa a 65°C", None, "water_drop", 0, True, 1, None, 0),
    ("temperature", "Iced / Con Hielo", "Cubo cristalino de lenta dilución", None, "ac_unit", 0, False, 2, None, 0),
    ("milk", "Entera Fresca de Granja", "Cremosa, de proximidad", None, "grocery", 0, False, 1, "MOK-LK-03", 0.25),
    ("milk", "Leche de Avena Barista", "Microespuma sedosa vegetal", "Recomendada", "grass", 60, True, 2, "MOK-LK-01", 0.25),
    ("milk", "Almendras Tostadas", "Toque ligero y aromático", None, "nutrition", 60, False, 3, "MOK-LK-02", 0.25),
    ("milk", "Sin Lactosa", "Fácil digestión con cuerpo completo", None, "health_and_safety", 40, False, 4, "MOK-LK-04", 0.25),
    ("sweetness", "Normal (100%)", "Receta de la casa", None, None, 0, True, 1, None, 0),
    ("sweetness", "Ligero (50%)", "Suave", None, None, 0, False, 2, None, 0),
    ("sweetness", "Sutil (25%)", "Apenas dulce", None, None, 0, False, 3, None, 0),
    ("sweetness", "Sin Sirope", "Puro café", None, None, 0, False, 4, None, 0),
    ("extra", "Shot Extra de Espresso", "Mayor intensidad y cafeína pura", None, None, 90, False, 1, "MOK-CF-01", 0.018),
    ("extra", "Nube de Crema Batida", "Batida a mano cada mañana", None, None, 50, False, 2, "MOK-LK-05", 0.03),
    ("extra", "Canela de Ceilán", "Espolvoreada al momento", None, None, 0, False, 3, None, 0),
]

DRINK = "size,temperature,milk,sweetness,extra"

# slug: campos + receta {sku: cantidad por unidad}
PRODUCTS = [
    dict(
        slug="caramel-macchiato-insignia", cat="cafe", name="Caramel Macchiato Insignia", price=480, badge="Bebida Insignia",
        subtitle="Receta de la Casa • Infusión Vainilla Bourbon", featured=True, groups=DRINK, tags="",
        description="Espresso doble de origen Etiopía Yirgacheffe, leche vaporizada sedosa infusionada lentamente con vainilla natural de Madagascar y coronado con nuestro hilado artesanal de caramelo con sal marina rosada.",
        meta=("Doble Shot Ristretto", "bolt"), origin="Etiopía Yirgacheffe", notes="Jazmín Silvestre,Vainilla de Madagascar,Sal Marina,Mantequilla Tostada",
        calories=180, caffeine=145, prep=6, image="caramel",
        recipe={"MOK-CF-01": 0.018, "MOK-OB-06": 0.03, "MOK-PKG-01": 1},
    ),
    dict(
        slug="flat-white-doble-origen", cat="cafe", name="Flat White Doble Origen", price=420, badge="Recomendado Barista",
        subtitle="Doble ristretto con microespuma elástica", groups="size,temperature,milk,extra", tags="organic",
        description="Ristretto doble blend Etiopía Yirgacheffe con microespuma sedosa y elástica texturizada con precisión a 62°C.",
        meta=("Temperatura Barista Óptima", "thermostat"), origin="Etiopía Yirgacheffe", notes="Cacao Amargo,Avellana Silvestre",
        calories=150, caffeine=130, prep=5, image="flat_white",
        recipe={"MOK-CF-01": 0.018, "MOK-PKG-01": 1},
    ),
    dict(
        slug="americano-de-origen", cat="cafe", name="Americano de Origen", price=320, badge=None,
        subtitle="Espresso largo, limpio y brillante", groups="size,temperature,extra", tags="organic,gluten-free",
        description="Doble espresso alargado con agua filtrada a 92°C. Limpio, brillante y con final dulce.",
        meta=("Extracción de 28 segundos", "timer"), origin="Etiopía Yirgacheffe", notes="Cítricos,Miel",
        calories=10, caffeine=140, prep=4, image="americano",
        recipe={"MOK-CF-01": 0.018, "MOK-PKG-01": 1},
    ),
    dict(
        slug="espresso-doble", cat="cafe", name="Espresso Doble", price=280, badge=None,
        subtitle="Doble ristretto puro", groups="", tags="organic,gluten-free",
        description="Doble ristretto 1:1.8 extraído al momento. Cuerpo denso y crema persistente.",
        meta=("Servido en taza de cerámica", "coffee"), origin="Etiopía Yirgacheffe", notes="Chocolate,Caramelo",
        calories=5, caffeine=130, prep=3, image="espresso",
        recipe={"MOK-CF-01": 0.018, "MOK-PKG-01": 1},
    ),
    dict(
        slug="shot-extra-espresso", cat="cafe", name="Shot Extra de Espresso", price=90, badge=None,
        subtitle="Para reforzar cualquier bebida", groups="", tags="organic,gluten-free",
        description="Un ristretto adicional de origen único con notas a avellana.",
        meta=("Origen Etiopía", "bolt"), calories=2, caffeine=65, prep=2, image="espresso",
        recipe={"MOK-CF-01": 0.018},
    ),
    dict(
        slug="cold-brew-vainilla-sweet-cream", cat="frios", name="Cold Brew Vainilla Sweet Cream", price=450, badge="Favorito Verano",
        subtitle="16h de infusión fría", groups="size,sweetness,extra", tags="organic",
        description="Maceración lenta de 16 horas con cascada de crema dulce aromatizada con vainas bourbon de Madagascar.",
        meta=("Extracción por goteo frío", "water_drop"), origin="Colombia", notes="Vainilla,Cacao,Panela",
        calories=120, caffeine=180, prep=4, image="cold_brew",
        recipe={"MOK-CF-02": 0.03, "MOK-LK-05": 0.04, "MOK-PKG-01": 1},
    ),
    dict(
        slug="matcha-latte-ceremonial", cat="tes", name="Matcha Latte Ceremonial", price=510, badge="Antioxidante",
        subtitle="Uji, Kioto · Grado A", groups="size,temperature,milk,sweetness", tags="decaf,organic",
        description="Té verde matcha de primera cosecha de Uji, Kioto. Batido en chasen con toque de agave y la leche que prefieras.",
        meta=("Calidad ceremonial japonesa", "spa"), origin="Uji, Kioto", notes="Umami,Hierba Fresca,Dulzor Suave",
        calories=140, caffeine=45, prep=5, image="matcha",
        recipe={"MOK-CF-03": 0.004, "MOK-PKG-01": 1},
    ),
    dict(
        slug="croissant-de-almendras", cat="panaderia", name="Croissant de Almendras", price=395, badge="Recién Horneado",
        subtitle="Horno 06:30", groups="", tags="",
        description="Hojaldre de mantequilla AOP francesa, crema frangipane y lluvia de almendras tostadas crujientes.",
        meta=("Fermentación lenta de 36 h", "bakery_dining"), calories=420, prep=2, image="croissant",
        recipe={"MOK-OB-01": 0.05, "MOK-OB-02": 0.06, "MOK-OB-04": 0.01},
    ),
    dict(
        slug="cookie-valrhona-flor-de-sal", cat="panaderia", name="Cookie Valrhona & Flor de Sal", price=220, badge="Crujiente & Tierna",
        subtitle="Servida tibia", groups="", tags="",
        description="Galleta artesanal tibia con corazón fundido de chocolate Valrhona Guanaja 70% y cristales de flor de sal marina.",
        meta=("Servida tibia al momento", "local_fire_department"), calories=380, prep=2, image="cookie",
        recipe={"MOK-OB-01": 0.03, "MOK-OB-02": 0.04, "MOK-OB-03": 0.03},
    ),
    dict(
        slug="cinnamon-roll", cat="panaderia", name="Cinnamon Roll", price=380, badge="Horno 8:00 AM",
        subtitle="Receta tradicional", groups="", tags="",
        description="Canela de Ceilán pura envuelta en masa brioche esponjosa con glaseado de queso crema.",
        meta=("Glaseado de queso crema", "bakery_dining"), calories=460, prep=2, image="cinnamon",
        recipe={"MOK-OB-01": 0.04, "MOK-OB-02": 0.08},
    ),
    dict(
        slug="budin-limon-amapola", cat="panaderia", name="Budín Limón & Amapola", price=310, badge=None,
        subtitle="Glaseado cítrico", groups="", tags="",
        description="Budín húmedo de limón y semillas de amapola con glaseado cítrico fresco.",
        meta=("Horneado cada mañana", "bakery_dining"), calories=340, prep=2, image="budin",
        recipe={"MOK-OB-01": 0.03, "MOK-OB-02": 0.06},
    ),
    dict(
        slug="tosta-aguacate-ricotta-almendra", cat="brunch", name="Tosta Aguacate & Ricotta Almendra", price=650, badge="Plant Based",
        subtitle="Masa madre viva", groups="", tags="vegan",
        description="Hogaza de masa madre, aguacate Hass al limón, suave ricotta botánica de almendra y dukkah crujiente.",
        meta=("Alta en fibra y grasas nobles", "nutrition"), calories=390, prep=6, image="toast",
        recipe={"MOK-OB-07": 0.125, "MOK-OB-05": 0.5, "MOK-OB-04": 0.01},
    ),
    dict(
        slug="bolsa-etiopia-yirgacheffe-250g", cat="granos", name="Bolsa Etiopía Yirgacheffe 250g", price=1400, badge="Bolsa 250g",
        subtitle="Notas florales y cítricas", groups="", tags="organic",
        description="Grano tostado de altura, con notas florales de jazmín, lima y bergamota. Ideal para V60, Chemex y espresso.",
        meta=("Ideal V60, Chemex y espresso", "coffee_maker"), origin="Etiopía Yirgacheffe", notes="Jazmín,Lima,Bergamota", prep=1, image="bag",
        recipe={"MOK-CF-01": 0.25, "MOK-PKG-02": 1},
    ),
]


def seed_catalog():
    """Catálogo completo con stock en cero y cuentas del equipo. Idempotente."""
    if db.session.scalar(select(Category.id).limit(1)):
        return
    for slug, name, icon, order in CATEGORIES:
        db.session.add(Category(slug=slug, name=name, icon=icon, sort_order=order))

    items = {}
    for sku, name, category, unit, minimum, cost, supplier, _qty in INVENTORY:
        item = InventoryItem(sku=sku, name=name, category=category, unit=unit, min_stock=minimum, unit_cost_cents=cost, supplier=supplier, stock=0)
        db.session.add(item)
        items[sku] = item
    db.session.flush()

    for group, name, desc, badge, icon, delta, default, order, sku, qty in MODIFIERS:
        db.session.add(
            Modifier(
                group=group, name=name, description=desc, badge=badge, icon=icon, price_delta_cents=delta, is_default=default,
                sort_order=order, inventory_item_id=items[sku].id if sku else None, inventory_qty=qty,
            )
        )

    categories = {c.slug: c for c in db.session.scalars(select(Category))}
    for spec in PRODUCTS:
        meta_line, meta_icon = spec.get("meta", (None, None))
        product = Product(
            category_id=categories[spec["cat"]].id, slug=spec["slug"], name=spec["name"], subtitle=spec.get("subtitle"),
            description=spec["description"], price_cents=spec["price"], image_url=f"{IMAGE_DIR}/{spec['image']}.jpg" if spec.get("image") else None, badge=spec.get("badge"),
            tags=spec.get("tags", ""), option_groups=spec.get("groups", ""), meta_line=meta_line, meta_icon=meta_icon,
            origin=spec.get("origin"), tasting_notes=spec.get("notes"), calories=spec.get("calories"),
            caffeine_mg=spec.get("caffeine"), prep_minutes=spec.get("prep", 5), featured=spec.get("featured", False),
        )
        db.session.add(product)
        db.session.flush()
        for sku, qty in spec["recipe"].items():
            db.session.add(ProductIngredient(product_id=product.id, item_id=items[sku].id, qty=qty))

    db.session.add(Coupon(code="CAFELOVER", description="Beneficio comunidad Moka", kind="fijo", value=200, min_subtotal_cents=500))
    db.session.commit()


def seed_team():
    """Administrador (desde la configuración) y un barista. Idempotente."""
    cfg = current_app.config
    if not User.get_by_email(cfg["ADMIN_EMAIL"]):
        User.create("Administrador Moka", cfg["ADMIN_EMAIL"], cfg["ADMIN_PASSWORD"], role=ROLE_ADMIN)
    return User.get_by_email(cfg["ADMIN_EMAIL"])


# ------------------------------------------------------------------------------------
# Datos demo
# ------------------------------------------------------------------------------------
DEMO_CLIENT_PASSWORD = "moka1234"
DEMO_CUSTOMERS = [
    ("Elena Rostova", "elena@correo.com"),
    ("Sofía Alarcón", "sofia@correo.com"),
    ("Carlos Méndez", "carlos@correo.com"),
    ("Valeria Morales", "valeria@correo.com"),
    ("Diego Gómez", "diego@correo.com"),
    ("Ana Torres", "ana@correo.com"),
]


def _cart_for(rng, products):
    """Carrito aleatorio con opciones por defecto (mediano, avena, caliente)."""
    cart = Cart(store={})
    for product in rng.sample(products, k=rng.randint(1, 3)):
        extras = []
        if product.is_customizable and "extra" in product.option_group_list and rng.random() < 0.25:
            extras = [db.session.scalar(select(Modifier.id).where(Modifier.name == "Shot Extra de Espresso"))]
        cart.add(product, extras=extras, qty=rng.choice([1, 1, 1, 2]))
    return cart.summary()


def seed_demo():
    """Compra inicial, clientes y pedidos históricos (pasando por las mismas reglas del sistema)."""
    if db.session.scalar(select(Order.id).limit(1)):
        return
    rng = random.Random(7)
    now = datetime.now()
    admin = seed_team()
    barista = User.get_by_email("mateo@moka.com") or User.create(
        "Mateo Gómez", "mateo@moka.com", "barista1234", role=ROLE_BARISTA, created_at=now - timedelta(days=400)
    )
    customers = [
        User.get_by_email(email) or User.create(name, email, DEMO_CLIENT_PASSWORD, created_at=now - timedelta(days=rng.randint(20, 300)))
        for name, email in DEMO_CUSTOMERS
    ]

    # 1) Compra inicial de inventario (egresos en la cartera)
    first_day = (now - timedelta(days=10)).replace(hour=8, minute=0, second=0, microsecond=0)
    for sku, _name, _cat, _unit, _min, cost, supplier, qty in INVENTORY:
        item = db.session.scalar(select(InventoryItem).where(InventoryItem.sku == sku))
        item.purchase(qty, cost, supplier=supplier, user=admin, at=first_day)

    # 2) Pedidos históricos
    products = list(db.session.scalars(select(Product).where(Product.is_active.is_(True), Product.slug != "shot-extra-espresso")))

    def place(when, method, final):
        summary = _cart_for(rng, products)
        order = Order.create_from_cart(rng.choice(customers), summary, method, at=when)
        if final == "pendiente":
            return order
        if order.payment_status != "pagado":
            order.confirm_payment(by=barista, at=when + timedelta(minutes=2))
        if final == "cancelado":
            order.cancel(by=barista, reason="Cliente canceló antes de la preparación", at=when + timedelta(minutes=4))
            return order
        if final == "pagado":
            return order
        order.accept(barista, at=when + timedelta(minutes=3))
        if final == "en_barra":
            return order
        order.mark_ready(at=when + timedelta(minutes=9))
        if final == "listo":
            return order
        order.mark_delivered(at=when + timedelta(minutes=11))
        return order

    for days_ago in range(9, 0, -1):
        day = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(rng.randint(4, 7)):
            when = day + timedelta(hours=rng.randint(7, 19), minutes=rng.randint(0, 59))
            method = "tarjeta" if rng.random() < 0.7 else "efectivo"
            final = "cancelado" if rng.random() < 0.06 else "entregado"
            place(when, method, final)

    # Pedidos de hoy (varios estados para ver la pizarra en acción)
    for minutes_ago, method, final in [(95, "tarjeta", "entregado"), (60, "efectivo", "entregado"), (34, "tarjeta", "en_barra"),
                                       (22, "tarjeta", "pagado"), (12, "efectivo", "pendiente"), (5, "tarjeta", "pagado")]:
        place(now - timedelta(minutes=minutes_ago), method, final)

    # 3) Conteo físico: deja algunos insumos bajos para mostrar alertas y sugerencias
    for sku, stock in [("MOK-LK-01", 4), ("MOK-OB-01", 1.5), ("MOK-LK-05", 0.4)]:
        item = db.session.scalar(select(InventoryItem).where(InventoryItem.sku == sku))
        if item.stock != stock:
            item.adjust(stock, kind=MOV_ADJUSTMENT, note="Conteo físico del turno", user=admin)


def seed_database(demo=True):
    seed_catalog()
    seed_team()
    if demo:
        seed_demo()

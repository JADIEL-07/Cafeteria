"""Catálogo: categorías, productos, opciones de personalización y recetas."""
from datetime import datetime

from sqlalchemy import func, or_, select

from ..extensions import db

# --- Opciones de personalización -------------------------------------------
GROUP_SIZE = "size"
GROUP_TEMPERATURE = "temperature"
GROUP_MILK = "milk"
GROUP_SWEETNESS = "sweetness"
GROUP_EXTRA = "extra"
MODIFIER_GROUPS = (GROUP_SIZE, GROUP_TEMPERATURE, GROUP_MILK, GROUP_SWEETNESS, GROUP_EXTRA)
MODIFIER_GROUP_LABELS = {
    GROUP_SIZE: "Tamaño de la Copa",
    GROUP_TEMPERATURE: "Temperatura",
    GROUP_MILK: "Tipo de Leche",
    GROUP_SWEETNESS: "Nivel de Caramelo & Dulzor",
    GROUP_EXTRA: "Toques Artesanales Extras",
}

DIET_TAGS = {
    "vegan": "🌱 Vegano",
    "gluten-free": "🌾 Sin Gluten",
    "decaf": "🌙 Bajo en Cafeína",
    "organic": "🍃 Orgánico",
}
SORT_OPTIONS = {
    "popular": "Más Populares",
    "nuevo": "Novedades",
    "precio_asc": "Precio: Menor a Mayor",
    "precio_desc": "Precio: Mayor a Menor",
}


def _csv(value):
    return [part.strip() for part in (value or "").split(",") if part.strip()]


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(80), nullable=False)
    icon = db.Column(db.String(40), nullable=False, default="restaurant_menu")
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    products = db.relationship("Product", back_populates="category")

    @classmethod
    def all_sorted(cls):
        return db.session.scalars(select(cls).order_by(cls.sort_order, cls.name)).all()


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    slug = db.Column(db.String(90), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    subtitle = db.Column(db.String(160))
    description = db.Column(db.Text, nullable=False, default="")
    price_cents = db.Column(db.Integer, nullable=False)
    image_url = db.Column(db.String(600))
    badge = db.Column(db.String(40))
    tags = db.Column(db.String(200), nullable=False, default="")            # vegan,organic,...
    option_groups = db.Column(db.String(120), nullable=False, default="")   # size,milk,...
    meta_line = db.Column(db.String(120))                                   # "Fermentación lenta de 36h"
    meta_icon = db.Column(db.String(40))
    origin = db.Column(db.String(120))
    tasting_notes = db.Column(db.String(240))
    calories = db.Column(db.Integer)
    caffeine_mg = db.Column(db.Integer)
    prep_minutes = db.Column(db.Integer, nullable=False, default=5)
    featured = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    category = db.relationship("Category", back_populates="products")
    ingredients = db.relationship("ProductIngredient", back_populates="product", cascade="all, delete-orphan")

    # ---- propiedades --------------------------------------------------------
    @property
    def tag_list(self):
        return _csv(self.tags)

    @property
    def option_group_list(self):
        return [g for g in _csv(self.option_groups) if g in MODIFIER_GROUPS]

    @property
    def is_customizable(self):
        return bool(self.option_group_list)

    @property
    def tasting_note_list(self):
        return _csv(self.tasting_notes)

    @property
    def beans(self):
        """Granos Moka Club que gana el cliente al comprar 1 unidad (1 por cada $1)."""
        return self.price_cents // 100

    # ---- consultas ------------------------------------------------------------
    @classmethod
    def sold_map(cls):
        """{producto: unidades vendidas} en pedidos cobrados y no cancelados."""
        from .order import PAY_PAID, ST_CANCELLED, Order, OrderItem

        rows = db.session.execute(
            select(OrderItem.product_id, func.sum(OrderItem.qty))
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.payment_status == PAY_PAID, Order.status != ST_CANCELLED)
            .group_by(OrderItem.product_id)
        ).all()
        return {pid: int(qty) for pid, qty in rows}

    @classmethod
    def catalog(cls, category_slug=None, query=None, tags=(), sort="popular"):
        stmt = select(cls).where(cls.is_active.is_(True))
        if category_slug:
            stmt = stmt.join(Category).where(Category.slug == category_slug)
        if query:
            like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(
                or_(
                    cls.name.ilike(like, escape="\\"),
                    cls.description.ilike(like, escape="\\"),
                    cls.subtitle.ilike(like, escape="\\"),
                )
            )
        products = db.session.scalars(stmt).all()
        if tags:
            products = [p for p in products if all(t in p.tag_list for t in tags)]
        if sort == "precio_asc":
            products.sort(key=lambda p: (p.price_cents, p.name))
        elif sort == "precio_desc":
            products.sort(key=lambda p: (-p.price_cents, p.name))
        elif sort == "nuevo":
            products.sort(key=lambda p: (p.created_at, p.id), reverse=True)
        else:
            sold = cls.sold_map()
            products.sort(key=lambda p: (-sold.get(p.id, 0), p.name))
        return products

    @classmethod
    def category_counts(cls):
        rows = db.session.execute(
            select(Category.slug, func.count(cls.id)).join(cls, cls.category_id == Category.id).where(cls.is_active.is_(True)).group_by(Category.slug)
        ).all()
        return dict(rows)

    @classmethod
    def get_active_by_slug(cls, slug):
        return db.session.scalar(select(cls).where(cls.slug == slug, cls.is_active.is_(True)))

    @classmethod
    def featured_product(cls):
        return db.session.scalar(select(cls).where(cls.featured.is_(True), cls.is_active.is_(True)).order_by(cls.id))

    def pairings(self, limit=1):
        """Acompañamientos sugeridos: panadería que no sea el propio producto."""
        return db.session.scalars(
            select(Product)
            .join(Category)
            .where(Category.slug == "panaderia", Product.is_active.is_(True), Product.id != self.id)
            .order_by(Product.id)
            .limit(limit)
        ).all()

    def related_drinks(self, limit=3):
        return db.session.scalars(
            select(Product)
            .where(Product.is_active.is_(True), Product.id != self.id, Product.option_groups != "")
            .order_by(Product.id)
            .limit(limit)
        ).all()

    def __repr__(self):
        return f"<Product {self.slug}>"


class Modifier(db.Model):
    """Opción elegible al pedir una bebida (tamaño, leche, extra...)."""

    __tablename__ = "modifiers"

    id = db.Column(db.Integer, primary_key=True)
    group = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(160))
    badge = db.Column(db.String(30))
    icon = db.Column(db.String(40))
    price_delta_cents = db.Column(db.Integer, nullable=False, default=0)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    # Insumo que se descuenta del inventario al preparar (opcional)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_items.id"))
    inventory_qty = db.Column(db.Float, nullable=False, default=0)

    inventory_item = db.relationship("InventoryItem")

    @classmethod
    def by_group(cls):
        rows = db.session.scalars(select(cls).where(cls.is_active.is_(True)).order_by(cls.group, cls.sort_order, cls.id)).all()
        grouped = {g: [] for g in MODIFIER_GROUPS}
        for row in rows:
            grouped.setdefault(row.group, []).append(row)
        return grouped

    @classmethod
    def default_for(cls, group):
        return db.session.scalar(
            select(cls).where(cls.group == group, cls.is_active.is_(True)).order_by(cls.is_default.desc(), cls.sort_order, cls.id)
        )


class ProductIngredient(db.Model):
    """Receta: cuánto insumo consume cada unidad vendida de un producto."""

    __tablename__ = "product_ingredients"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("inventory_items.id"), nullable=False)
    qty = db.Column(db.Float, nullable=False)

    product = db.relationship("Product", back_populates="ingredients")
    item = db.relationship("InventoryItem")

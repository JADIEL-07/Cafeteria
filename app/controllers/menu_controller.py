"""Carta de productos, detalle con personalización y favoritos."""
from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Cart, Category, Favorite, Modifier, Order, Product
from ..models.product import DIET_TAGS, MODIFIER_GROUP_LABELS, SORT_OPTIONS
from ..utils.auth import login_required, safe_next_url, wants_json

bp = Blueprint("menu", __name__)


@bp.get("/")
def home():
    return redirect(url_for("menu.index"))


@bp.get("/menu")
def index():
    category = request.args.get("cat") or None
    query = request.args.get("q", "").strip()[:60]
    diets = [t for t in request.args.getlist("dieta") if t in DIET_TAGS]
    sort = request.args.get("orden") if request.args.get("orden") in SORT_OPTIONS else "popular"
    categories = Category.all_sorted()
    if category not in {c.slug for c in categories}:
        category = None
    products = Product.catalog(category, query or None, diets, sort)
    counts = Product.category_counts()
    filtered = bool(category or query or diets)
    mode, table = Cart().mode_info()
    return render_template(
        "customer/menu.html",
        products=products,
        categories=categories,
        counts=counts,
        total_products=sum(counts.values()),
        featured=None if filtered else Product.featured_product(),
        active_category=category,
        query=query,
        diets=diets,
        sort=sort,
        filtered=filtered,
        favorite_ids=Favorite.ids_for(g.user),
        wait=Order.estimated_wait(),
        mode=mode,
        table=table,
        diet_tags=DIET_TAGS,
        sort_options=SORT_OPTIONS,
    )


@bp.get("/menu/<slug>")
def product(slug):
    product = Product.get_active_by_slug(slug)
    if product is None:
        abort(404)
    modifiers = Modifier.by_group()
    groups = [(g_key, MODIFIER_GROUP_LABELS[g_key], modifiers[g_key]) for g_key in product.option_group_list if modifiers.get(g_key)]
    return render_template(
        "customer/product_detail.html",
        product=product,
        groups=groups,
        pairings=product.pairings(1),
        related=product.related_drinks(3),
        favorite_ids=Favorite.ids_for(g.user),
        wait=Order.estimated_wait(),
    )


@bp.get("/favoritos")
@login_required
def favorites():
    return render_template("customer/favorites.html", products=Favorite.products_for(g.user), favorite_ids=Favorite.ids_for(g.user))


@bp.post("/favoritos/<int:product_id>/toggle")
@login_required
def toggle_favorite(product_id):
    product = db.session.get(Product, product_id)
    if product is None or not product.is_active:
        abort(404)
    is_favorite = Favorite.toggle(g.user, product)
    if wants_json():
        return jsonify(favorite=is_favorite)
    return redirect(safe_next_url(request.form.get("next"), url_for("menu.favorites")))

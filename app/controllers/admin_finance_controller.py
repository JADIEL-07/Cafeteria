"""Panel: cartera (invertido en inventario, recuperado y ganancia)."""
import csv
import io

from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for

from ..extensions import db
from ..models import DomainError, InventoryItem, LedgerEntry, Order
from ..models.ledger import CONCEPT_LABELS, KIND_IN, KIND_OUT, METHOD_LABELS
from ..utils.auth import admin_required, safe_next_url
from ..utils.money import parse_money
from ..utils.params import page_arg
from ..utils.timefmt import PERIODS, period_range, start_of_day

bp = Blueprint("admin_finance", __name__, url_prefix="/admin/cartera")


def _filters():
    period = request.args.get("periodo", "hoy")
    if period not in PERIODS:
        period = "hoy"
    method = request.args.get("metodo") if request.args.get("metodo") in METHOD_LABELS else None
    concept = request.args.get("tipo") if request.args.get("tipo") in CONCEPT_LABELS else None
    return period, method, concept


@bp.get("/")
@admin_required
def index():
    period, method, concept = _filters()
    start, end = period_range(period)
    day_start, day_end = period_range("hoy")
    page = page_arg(request.args.get("page"))
    inventory = InventoryItem.kpis()
    overall = LedgerEntry.summary()
    pending_count, pending_amount = Order.pending_payments()
    return render_template(
        "admin/finance.html",
        period=period,
        periods=PERIODS,
        method=method,
        concept=concept,
        methods=METHOD_LABELS,
        concepts=CONCEPT_LABELS,
        summary=LedgerEntry.summary(start, end),
        overall=overall,
        stock_value=inventory["total_value_cents"],
        drawer=LedgerEntry.cash_drawer(day_start, day_end),
        chart=LedgerEntry.hourly_sales(start, end),
        transactions=LedgerEntry.transactions(start, end, method, concept, page),
        pending_count=pending_count,
        pending_amount=pending_amount,
    )


@bp.post("/ajuste")
@admin_required
def adjustment():
    kind = KIND_IN if request.form.get("kind") == KIND_IN else KIND_OUT
    try:
        LedgerEntry.record_adjustment(
            kind,
            parse_money(request.form.get("amount"), allow_zero=False),
            request.form.get("description"),
            method=request.form.get("method"),
            user=g.user,
        )
        flash("Ajuste registrado en la cartera.", "success")
    except (DomainError, ValueError) as exc:
        flash(str(exc) if isinstance(exc, DomainError) else "Escribe un importe válido mayor que cero.", "error")
    return redirect(safe_next_url(request.form.get("next"), url_for("admin_finance.index")))


def csv_safe(value):
    """Evita inyección de fórmulas al abrir el CSV en Excel/Sheets."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@bp.get("/exportar.csv")
@admin_required
def export():
    period, method, concept = _filters()
    start, end = period_range(period)
    entries = LedgerEntry.entries_query(start, end, method, concept)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["ID", "Fecha", "Concepto", "Referencia", "Cliente/Proveedor", "Método", "Monto", "Comisión", "Efecto neto"])
    for entry in db.session.scalars(entries):
        writer.writerow(
            [
                entry.tx_id,
                entry.created_at.strftime("%Y-%m-%d %H:%M"),
                entry.concept_label,
                csv_safe(entry.description),
                csv_safe(entry.party),
                entry.method or "",
                f"{entry.amount_cents / 100:.2f}",
                f"{entry.fee_cents / 100:.2f}",
                f"{entry.net_cents / 100:.2f}",
            ]
        )
    filename = f"cartera-{period}-{start_of_day():%Y%m%d}.csv"
    return Response(
        "﻿" + out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# Moka Café & Bakery — pedidos, inventario, usuarios y cartera

[![CI](https://github.com/JADIEL-07/Cafeteria/actions/workflows/ci.yml/badge.svg)](https://github.com/JADIEL-07/Cafeteria/actions/workflows/ci.yml)

Aplicación web para una cafetería sencilla, hecha con **Python + Flask** y arquitectura **MVC**.
Las pantallas son las de tu diseño (Tailwind + Literata / Plus Jakarta Sans), ahora conectadas a una base de datos SQLite.

## Cómo ejecutarla

```bash
pip install -r requirements.txt
python run.py            # http://127.0.0.1:5000
```

La primera vez crea `instance/cafeteria.db` con el catálogo y **datos de ejemplo** (clientes, pedidos e inventario).

| Rol | Correo | Contraseña |
|---|---|---|
| Administrador (todo) | `admin@moka.com` | `admin1234` |
| Barista (pedidos + inventario) | `mateo@moka.com` | `barista1234` |
| Cliente demo | `elena@correo.com` | `moka1234` |

> Para un uso real: `CAFE_DEMO_DATA=0` (arranca sólo con catálogo y administrador), `ADMIN_EMAIL` / `ADMIN_PASSWORD`
> (credenciales del administrador inicial) y `SECRET_KEY` (si no la defines se genera en `instance/secret.key`).
> Detrás de HTTPS añade `CAFE_HTTPS=1`. `flask --app run reset-db --no-demo` reinicia la base; `flask --app run create-user correo "Nombre" --role barista` crea cuentas.
> Con la base vacía no hay stock: registra tus compras en **Inventario** antes de aceptar pedidos.

Tailwind y las fuentes se cargan por CDN (necesitan internet, igual que en tus diseños).

## Estructura (MVC)

```
run.py                       punto de entrada
app/
├── __init__.py              fábrica de la app (config, hooks, errores, CLI)
├── config.py                impuestos, comisión, datos del local, variables de entorno
├── database.py              conexión SQLite / PostgreSQL (Supabase), arranque de tablas y RLS
├── seed.py                  catálogo, recetas, cuentas y datos demo
├── models/        (M)       entidades + reglas de negocio
│   ├── user.py  product.py  inventory.py  order.py  ledger.py  cart.py  coupon.py  favorite.py
├── controllers/   (C)       un blueprint por área
│   ├── auth_controller.py            login / registro / logout
│   ├── menu_controller.py            carta, detalle de producto, favoritos
│   ├── cart_controller.py            carrito, cupones, modo de entrega, checkout
│   ├── orders_controller.py          perfil y seguimiento de pedidos del cliente
│   ├── admin_orders_controller.py    pizarra de pedidos (panel)
│   ├── admin_inventory_controller.py inventario y compras
│   ├── admin_finance_controller.py   cartera
│   └── admin_users_controller.py     usuarios y Moka Club
├── utils/                   dinero (centavos), fechas, permisos, límite de intentos
└── views/         (V)
    ├── templates/
    │   ├── layouts/         base.html · customer.html · admin.html
    │   ├── partials/        config de Tailwind, componentes, cabecera/pie/navegación, macros
    │   ├── customer/        menu · product_detail · cart · order_status · favorites · profile
    │   ├── auth/            login (iniciar sesión + crear cuenta)
    │   ├── admin/           orders · inventory · finance · users
    │   └── errors/
    └── static/              css/ · js/ · img/logo.svg · img/products/*.jpg
conftest.py                  registra los fixtures de tests/fixtures
tests/                       686 pruebas (pytest)
├── fixtures/                un módulo de fixtures por modelo (usuarios, catálogo, inventario, cupones, carritos, pedidos, cartera, favoritos)
├── models/                  pruebas unitarias, un archivo por modelo
├── utils/                   dinero, fechas y capa de base de datos
└── integration/             rutas HTTP, permisos, pantallas y robustez
```

## Reglas de negocio

**Pedidos** — estados: *pendiente de pago → pago confirmado → en barra → listo → entregado* (o *cancelado*).
- Tarjeta / Apple Pay: se aprueba al instante (**pasarela simulada**, ver limitaciones). Efectivo: queda *pendiente* hasta que barra valida el cobro.
- **Sólo un pedido con pago confirmado puede aceptarse.** La regla se aplica en el modelo (`Order.accept`), en el panel (botón bloqueado) y con actualizaciones atómicas, así un doble clic no duplica cobros ni descuentos de inventario.
- Cancelar es posible hasta que el barista acepta; si ya estaba cobrado se reembolsa y se revierten los granos.
- El cliente ve el avance de su pedido en vivo; el panel se recarga solo cuando llega o cambia un pedido.

**Inventario** — cada producto tiene una **receta** (insumos por unidad) y algunas opciones (leche, shot extra) consumen su propio insumo.
Al aceptar el pedido se descuenta el stock; si falta algo, se bloquea con un mensaje claro. Compras, ajustes de conteo y mermas quedan en un historial.
Los insumos bajo su mínimo generan **compras sugeridas** (hasta 2× el mínimo, al último costo).

**Cartera** — un libro de movimientos con las tres cifras que pediste:

```
Invertido  = compras de inventario
Recuperado = ventas − comisión de pasarela (2.4 % en tarjeta) − reembolsos
Ganancia   = Recuperado − Invertido   (± ajustes manuales)
```
Incluye periodos (hoy / semana / mes / todo), desglose tarjeta vs efectivo, arqueo de caja del día, ajustes manuales, exportación CSV y el valor del stock que aún tienes en almacén.

**Moka Club** — 1 grano por cada $1 cobrado (Plata desde 25, Granos Dorados VIP desde 100). El administrador puede bonificar o descontar granos.

**Importes** — IVA 7.5 % sobre (subtotal − cupón). Todo se guarda en centavos enteros. Cupón de ejemplo: `CAFELOVER` (−$2.00, mínimo $5.00).

**Permisos** — cliente: tienda y sus pedidos · barista: pedidos e inventario · administrador: además cartera y usuarios.

## Base de datos: SQLite o Supabase

Por defecto la app usa **SQLite** (`instance/cafeteria.db`), sin configurar nada. Para usar **Supabase** (PostgreSQL administrado):

1. En el panel de tu proyecto: **Connect → Connection string** → copia la de **Session pooler** (funciona por IPv4; la *Direct connection* sólo por IPv6). El pooler en modo transacción (puerto 6543) también sirve.
2. Copia `.env.example` como `.env` y pega la cadena en `DATABASE_URL`, reemplazando `[YOUR-PASSWORD]` (si la contraseña tiene `@ : / # ? %`, escríbela codificada: `@` → `%40`). `.env` está en `.gitignore`: **la contraseña de tu base nunca debe subirse a git**.
3. Instala las dependencias y arranca: `pip install -r requirements.txt` y `python run.py`. En el primer arranque se crean las tablas y se siembra el catálogo (y las cuentas) igual que con SQLite.

Qué hace la app por ti con Postgres:
- **Row Level Security activado en todas las tablas.** Supabase publica el esquema `public` por su API REST; sin RLS, quien tenga la clave pública (*anon key*) podría leer `users` (correos y hashes de contraseña). Con RLS y sin políticas esa API no ve nada; la app no la usa: se conecta con el usuario de la cadena (dueño de las tablas), que no queda sujeto a RLS. Se comprobó con un rol `anon` simulado.
- Conexión cifrada (`sslmode=require`), *pre-ping* y reciclado del pool, y sin sentencias preparadas (compatible con el pooler de Supabase); pool pequeño (5 + 5) para el plan gratuito.
- Creación de tablas con candado de asesoría: varios procesos (gunicorn) pueden arrancar a la vez sin pisarse.
- `flask --app run reset-db` pide confirmación cuando la base no es SQLite (muestra a qué base apunta).

Limitaciones: `create_all` sólo **crea tablas que faltan**; si más adelante cambias columnas necesitarás migraciones (Flask-Migrate/Alembic). Migrar los datos existentes de SQLite a Supabase no está automatizado (para un local nuevo basta el primer arranque).

## Cambios respecto a los diseños

- Cada pantalla tenía una versión móvil y otra de escritorio: ahora es **una sola plantilla responsive** (barra inferior en móvil, cabecera/pie completos en escritorio).
- Quité lo que no tenía respaldo real: reseñas y "12,000 baristas", QR de retiro (no era escaneable; queda el código PIN), botones Google/Apple, boletín, tostaduría/lotes/radar de cata, "cifrado SSL 256-bit". La configuración/sucursales del panel no se implementó.
- **Cartera** se rehízo alrededor de Invertido / Recuperado / Ganancia. **Inventario** cambió el bloque de tueste por movimientos y compras sugeridas.
- "Vegano" ya no aparece en bebidas que admiten leche de vaca. "Continuar como invitado" → puedes armar el carrito sin cuenta; para pagar se pide iniciar sesión.
- Las fotos son copias locales (`static/img/products`) recortadas de tus diseños; cámbialas por las tuyas cuando quieras.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest                              # pruebas (SQLite en memoria)
python -m pytest --cov=app --cov-report=term-missing   # con cobertura
python -m ruff check .                        # lint

# contra PostgreSQL (el motor de Supabase). La base se VACÍA en cada prueba y su nombre debe contener "test":
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/cafeteria_test python -m pytest
```

Las pruebas **nunca** usan `DATABASE_URL`, así que no pueden tocar tu base de Supabase por accidente.

En cada *push* y *pull request* GitHub Actions ejecuta el lint, las pruebas en Python 3.11, 3.12 y 3.13 con SQLite, y toda la suite contra PostgreSQL 15 y 17
(`.github/workflows/ci.yml`); Dependabot propone las actualizaciones de dependencias y de acciones.

**Por modelo** (`tests/models/`, 515 pruebas): `User`, `Category`, `Product`, `Modifier`, `ProductIngredient`, `InventoryItem`, `InventoryMovement`, `Coupon`, `Favorite`, `Cart`, `LedgerEntry`, `Order` y `OrderItem`, más las bases comunes (`unit_of_work`, errores de dominio). Cada prueba corre en una base SQLite en memoria propia y con un hash de contraseña barato, así toda la suite tarda menos de un minuto.

**Fixtures** (`tests/fixtures/`, uno por modelo) — se cargan desde el `conftest.py` de la raíz con `pytest_plugins` y se pueden combinar:

| Módulo | Fixtures principales |
| --- | --- |
| `application` | `app`, `client`, `session` (config de pruebas, base en memoria) |
| `users` | `client_user`, `barista_user`, `admin_user`, `silver_user`, `vip_user`, `inactive_user`, `user_factory` |
| `catalog` | `category`, `bakery_category`, `drink` (personalizable), `pastry`, `inactive_product`, `drink_modifiers`, `category_factory`, `product_factory`, `modifier_factory`, `recipe_factory` |
| `inventory` | `coffee_item`, `milk_item`, `cup_item`, `butter_item`, `warning_item`, `critical_item`, movimientos de compra / ajuste / merma / consumo, `item_factory` |
| `coupons` | `fixed_coupon`, `percent_coupon`, `inactive_coupon`, `exhausted_coupon`, `coupon_factory` |
| `carts` | `cart`, `filled_cart`, `cart_summary`, `cart_store` |
| `orders` | `kitchen` (bebida, pastelería, opciones, recetas e insumos), `order_factory`, `card_order`, `cash_order`, `accepted_order`, `ready_order`, `delivered_order`, `cancelled_paid_order`, `cancelled_unpaid_order` |
| `ledger` | `sale_entry`, `refund_entry`, `purchase_entry`, `adjustment_in_entry`, `adjustment_out_entry`, `ledger_dataset` (con las cifras esperadas), `ledger_factory` |
| `favorites` | `favorite`, `favorite_factory` |

**Integración** (`tests/integration/`, 94 pruebas): carrito y precios, flujo completo de pedidos (incluida la regla de pago), inventario, cartera, permisos por rol, CSRF, redirecciones seguras, exportaciones CSV, el renderizado de todas las pantallas y una prueba de robustez que golpea cada ruta con datos basura y otra de entradas que PostgreSQL rechaza (byte NUL, valores fuera de rango): ninguna puede dar error 500.

La cobertura ronda el **97 %** (modelos entre 98 y 100 %). El CI la publica como artefacto (`coverage-xml`).

## Limitaciones conocidas

- El **pago con tarjeta está simulado** (no hay pasarela real; no se pide ni guarda ningún dato de tarjeta). Conectar Stripe u otra pasarela iría en `Order.create_from_cart`.
- Los granos se acumulan pero **no hay canje** todavía. Los productos, opciones y recetas se editan en `app/seed.py` (no hay pantalla de administración de catálogo).
- Una sola sucursal y horas locales del servidor. SQLite alcanza para una caja; para varias cajas concurrentes usa Supabase (ver arriba).

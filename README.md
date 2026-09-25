# Moka Café & Bakery — pedidos, inventario, usuarios y cartera

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
tests/                       102 pruebas (pytest)
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

## Cambios respecto a los diseños

- Cada pantalla tenía una versión móvil y otra de escritorio: ahora es **una sola plantilla responsive** (barra inferior en móvil, cabecera/pie completos en escritorio).
- Quité lo que no tenía respaldo real: reseñas y "12,000 baristas", QR de retiro (no era escaneable; queda el código PIN), botones Google/Apple, boletín, tostaduría/lotes/radar de cata, "cifrado SSL 256-bit". La configuración/sucursales del panel no se implementó.
- **Cartera** se rehízo alrededor de Invertido / Recuperado / Ganancia. **Inventario** cambió el bloque de tueste por movimientos y compras sugeridas.
- "Vegano" ya no aparece en bebidas que admiten leche de vaca. "Continuar como invitado" → puedes armar el carrito sin cuenta; para pagar se pide iniciar sesión.
- Las fotos son copias locales (`static/img/products`) recortadas de tus diseños; cámbialas por las tuyas cuando quieras.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Cubren carrito y precios, flujo completo de pedidos (incluida la regla de pago), inventario, cartera, permisos por rol, CSRF, redirecciones seguras, exportaciones CSV, el renderizado de todas las pantallas y una prueba de robustez que golpea cada ruta con datos basura (ninguna puede dar error 500).

## Limitaciones conocidas

- El **pago con tarjeta está simulado** (no hay pasarela real; no se pide ni guarda ningún dato de tarjeta). Conectar Stripe u otra pasarela iría en `Order.create_from_cart`.
- Los granos se acumulan pero **no hay canje** todavía. Los productos, opciones y recetas se editan en `app/seed.py` (no hay pantalla de administración de catálogo).
- Una sola sucursal, horas locales del servidor y SQLite (suficiente para una cafetería; para varias cajas concurrentes conviene PostgreSQL vía `DATABASE_URL`).

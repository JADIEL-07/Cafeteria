/* Comportamiento global de la interfaz (sin dependencias). */
(function () {
  'use strict';

  const csrfToken = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const AJAX_HEADERS = { 'X-Requested-With': 'fetch', Accept: 'application/json' };

  /* ---------- Avisos emergentes ---------- */
  const TONES = {
    success: 'bg-primary text-on-primary',
    error: 'bg-error-container text-on-error-container',
    info: 'bg-inverse-surface text-inverse-on-surface',
  };
  const GLYPHS = { success: 'check_circle', error: 'error', info: 'info' };

  function dismiss(el) {
    if (!el || !el.isConnected) return;
    el.style.transition = 'opacity .25s, transform .25s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(-6px)';
    setTimeout(() => el.remove(), 260);
  }

  window.showToast = function (message, kind) {
    const stack = document.getElementById('flash-stack');
    if (!stack) return;
    kind = TONES[kind] ? kind : 'info';
    const el = document.createElement('div');
    el.setAttribute('data-flash', '');
    el.className = 'pointer-events-auto flex items-start gap-2.5 rounded-xl px-4 py-3 font-label-md text-label-md shadow-xl ' + TONES[kind];
    const icon = document.createElement('span');
    icon.className = 'material-symbols-outlined mt-px text-[18px]';
    icon.textContent = GLYPHS[kind];
    const text = document.createElement('span');
    text.className = 'flex-1 font-medium leading-snug';
    text.textContent = message; // textContent: nunca interpreta HTML
    const close = document.createElement('button');
    close.type = 'button';
    close.setAttribute('data-flash-close', '');
    close.setAttribute('aria-label', 'Cerrar');
    close.className = 'opacity-70 hover:opacity-100';
    close.innerHTML = '<span class="material-symbols-outlined text-[16px]">close</span>';
    el.append(icon, text, close);
    stack.appendChild(el);
    setTimeout(() => dismiss(el), 4200);
  };

  document.querySelectorAll('[data-flash]').forEach((el) => setTimeout(() => dismiss(el), 5200));

  /* ---------- Globo del carrito ---------- */
  function updateCartCount(count) {
    document.querySelectorAll('[data-cart-count]').forEach((el) => {
      el.textContent = count;
      el.classList.toggle('hidden', !count);
    });
  }

  /* ---------- Delegación de clics ---------- */
  document.addEventListener('click', async (event) => {
    const target = event.target;

    const flashClose = target.closest('[data-flash-close]');
    if (flashClose) return dismiss(flashClose.closest('[data-flash]'));

    // Favoritos
    const fav = target.closest('[data-fav-toggle]');
    if (fav) {
      event.preventDefault();
      event.stopPropagation();
      try {
        const res = await fetch(fav.dataset.url, {
          method: 'POST',
          headers: { ...AJAX_HEADERS, 'X-CSRFToken': csrfToken() },
          credentials: 'same-origin',
        });
        if (res.status === 401) {
          window.location.href = fav.dataset.login;
          return;
        }
        const data = await res.json();
        const icon = fav.querySelector('.material-symbols-outlined');
        if (icon) icon.classList.toggle('fill-1', data.favorite);
        fav.classList.toggle('text-secondary', data.favorite);
        fav.setAttribute('aria-pressed', data.favorite ? 'true' : 'false');
        if (!data.favorite && fav.hasAttribute('data-remove-on-unfav')) {
          const card = fav.closest('[data-fav-card]');
          if (card) card.remove();
        }
        window.showToast(data.favorite ? 'Guardado en tus favoritos.' : 'Quitado de tus favoritos.', 'info');
      } catch (err) {
        window.showToast('No pudimos actualizar tus favoritos. Inténtalo de nuevo.', 'error');
      }
      return;
    }

    // Diálogos (abrir precargando campos con data-fill='{"campo": "valor"}')
    const opener = target.closest('[data-open-dialog]');
    if (opener) {
      const dialog = document.getElementById(opener.dataset.openDialog);
      if (dialog) {
        const dialogForm = dialog.querySelector('form');
        if (dialogForm) dialogForm.reset();
        dialog.querySelectorAll('select').forEach((select) => select.dispatchEvent(new Event('change', { bubbles: true })));
        if (opener.dataset.fill) {
          try {
            const values = JSON.parse(opener.dataset.fill);
            Object.keys(values).forEach((name) => {
              const field = dialog.querySelector('[name="' + name + '"]');
              if (field) {
                field.value = values[name];
                field.dispatchEvent(new Event('change', { bubbles: true }));
              }
              const label = dialog.querySelector('[data-fill-label="' + name + '"]');
              if (label) label.textContent = values[name];
            });
          } catch (err) { /* datos inválidos: se abre vacío */ }
        }
        dialog.showModal();
        const first = dialog.querySelector('input:not([type=hidden]), select, textarea');
        if (first) first.focus();
      }
      return;
    }
    const closer = target.closest('[data-close-dialog]');
    if (closer) return closer.closest('dialog').close();
    if (target.tagName === 'DIALOG') return target.close(); // clic en el fondo

    // Mostrar / ocultar contraseña
    const eye = target.closest('[data-toggle-password]');
    if (eye) {
      const input = document.getElementById(eye.dataset.target);
      if (input) {
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        eye.querySelector('.material-symbols-outlined').textContent = show ? 'visibility_off' : 'visibility';
      }
      return;
    }

    // Menú lateral del panel (móvil)
    if (target.closest('[data-sidebar-toggle]')) {
      const sidebar = document.getElementById('admin-sidebar');
      const scrim = document.getElementById('sidebar-scrim');
      if (sidebar) {
        const open = sidebar.classList.toggle('-translate-x-full') === false;
        if (scrim) scrim.classList.toggle('hidden', !open);
      }
    }
  });

  /* ---------- Formularios ---------- */
  document.addEventListener('submit', async (event) => {
    const form = event.target;

    // Confirmación previa (acciones delicadas)
    if (form.dataset && form.dataset.confirm && !form.dataset.confirmed) {
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        return;
      }
    }

    // Añadir al carrito sin recargar la página
    const skipAjax = event.submitter && event.submitter.hasAttribute('data-no-ajax');
    if (form.matches && form.matches('form[data-ajax-add]') && !skipAjax) {
      event.preventDefault();
      const button = event.submitter;
      if (button) button.disabled = true;
      try {
        const res = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          headers: AJAX_HEADERS,
          credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.ok) {
          window.showToast(data.message, 'success');
          updateCartCount(data.count);
        } else {
          window.showToast(data.message || 'No pudimos añadir el producto.', 'error');
        }
      } catch (err) {
        form.removeAttribute('data-ajax-add');
        form.submit(); // sin JS/red: envío tradicional
        return;
      } finally {
        if (button) button.disabled = false;
      }
    }
  });

  /* ---------- Selectores que envían solos ---------- */
  document.addEventListener('change', (event) => {
    const el = event.target;
    if (el.matches && el.matches('[data-autosubmit]') && el.form) el.form.submit();
  });

  /* ---------- Actualización automática (panel y seguimiento) ---------- */
  // <body data-poll-url="..." data-poll-key="signature" data-poll-value="...">
  const body = document.body;
  if (body.dataset.pollUrl) {
    let current = body.dataset.pollValue;
    const key = body.dataset.pollKey || 'signature';
    setInterval(async () => {
      if (document.hidden || document.querySelector('dialog[open]')) return;
      const active = document.activeElement;
      if (active && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName)) return; // no interrumpir a quien escribe
      try {
        const res = await fetch(body.dataset.pollUrl, { headers: AJAX_HEADERS, credentials: 'same-origin' });
        if (!res.ok) return;
        const data = await res.json();
        if (String(data[key]) !== String(current)) window.location.reload();
      } catch (err) { /* sin red: se reintenta en el siguiente ciclo */ }
    }, 8000);
  }
})();

/* Detalle de producto: precio en vivo, etiquetas de selección y cantidad. */
(function () {
  'use strict';
  const form = document.getElementById('product-form');
  if (!form) return;

  const base = parseInt(form.dataset.base, 10) || 0;
  const qtyInput = form.querySelector('input[name="qty"]');
  const notes = form.querySelector('textarea[name="notes"]');
  const MAX_QTY = 20;

  const money = (cents) =>
    '$' + (cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const setAll = (selector, text) => document.querySelectorAll(selector).forEach((el) => (el.textContent = text));

  function unitPrice() {
    let total = base;
    form.querySelectorAll('input[data-delta]:checked').forEach((input) => (total += parseInt(input.dataset.delta, 10) || 0));
    return total;
  }

  function render() {
    const unit = unitPrice();
    const qty = parseInt(qtyInput.value, 10) || 1;
    setAll('[data-unit-price]', money(unit));
    setAll('[data-total-price]', money(unit * qty));
    setAll('[data-qty-display]', qty);
    setAll('[data-beans]', '+' + Math.floor((unit * qty) / 100) + ' Granos');

    document.querySelectorAll('[data-group-label]').forEach((el) => {
      const group = el.dataset.groupLabel;
      const picked = Array.from(form.querySelectorAll('input[data-group="' + group + '"]:checked'));
      el.textContent = picked.length
        ? picked
            .map((i) => {
              const delta = parseInt(i.dataset.delta, 10) || 0;
              return i.dataset.label + (delta ? ' (+' + money(delta) + ')' : '');
            })
            .join(', ')
        : group === 'extra'
        ? 'Ninguno'
        : '';
    });
    if (notes) {
      const counter = document.querySelector('[data-notes-counter]');
      if (counter) counter.textContent = notes.value.length + ' / ' + (notes.maxLength > 0 ? notes.maxLength : 160);
    }
  }

  form.addEventListener('change', render);
  if (notes) notes.addEventListener('input', render);
  document.querySelectorAll('[data-qty-step]').forEach((button) =>
    button.addEventListener('click', () => {
      const next = (parseInt(qtyInput.value, 10) || 1) + parseInt(button.dataset.qtyStep, 10);
      qtyInput.value = Math.min(MAX_QTY, Math.max(1, next));
      render();
    })
  );
  render();
})();

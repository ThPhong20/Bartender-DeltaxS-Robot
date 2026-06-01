const DRINKS = [
  { id: 'nuoc_chanh', name: 'Nước Chanh', emoji: '🍋', desc: 'Fresh lemon juice, sugar syrup, ice' },
  { id: 'nuoc_dau',   name: 'Nước Dâu',   emoji: '🍓', desc: 'Strawberry syrup, milk, ice' },
  { id: 'nuoc_cam',   name: 'Nước Cam',   emoji: '🍊', desc: 'Fresh orange juice, sugar, ice' },
];

const STATUS = {
  idle:       { label: 'Idle',       detail: 'Ready to take orders',        cls: 's-idle' },
  received:   { label: 'Received',   detail: 'Order received, queuing…',    cls: 's-received' },
  preparing:  { label: 'Preparing',  detail: 'Mixing your drink…',          cls: 's-preparing' },
  dispensing: { label: 'Dispensing', detail: 'Pouring into cup…',           cls: 's-dispensing' },
  done:       { label: 'Done!',      detail: 'Your drink is ready! Enjoy!', cls: 's-done' },
  error:      { label: 'Error',      detail: 'Robot encountered an error.', cls: 's-error' },
};

const SIZE_LABEL = { S: 'Small', M: 'Medium', L: 'Large' };

let state = { drink: null, size: 'M', status: 'idle', polling: null };
let orders = [];
let nextOrderId = 1;

// DOM
const drinkGrid       = document.getElementById('drinkGrid');
const statusRow       = document.getElementById('statusIndicator');
const statusLabel     = document.getElementById('statusLabel');
const statusDetail    = document.getElementById('statusDetail');
const orderPill       = document.getElementById('orderPill');
const pillDrink       = document.getElementById('pillDrink');
const pillSize        = document.getElementById('pillSize');
const placeOrderBtn   = document.getElementById('placeOrderBtn');
const clearErrorBtn      = document.getElementById('clearErrorBtn');
const simulateErrorBtn   = document.getElementById('simulateErrorBtn');
const errorPanel      = document.getElementById('errorPanel');
const noErrorMsg      = document.getElementById('noErrorMsg');
const errorDetail     = document.getElementById('errorDetail');
const errorCode       = document.getElementById('errorCode');
const errorText       = document.getElementById('errorText');
const errorTime       = document.getElementById('errorTime');
const connectionBadge  = document.getElementById('connectionBadge');
const connectionLabel  = document.getElementById('connectionLabel');
const toast            = document.getElementById('toast');
const orderCountBadge  = document.getElementById('orderCountBadge');
const ordersEmpty      = document.getElementById('ordersEmpty');
const ordersTableWrap  = document.getElementById('ordersTableWrap');
const ordersBody       = document.getElementById('ordersBody');
const clearDoneBtn     = document.getElementById('clearDoneBtn');

// ── Drinks ────────────────────────────────────────────
function renderDrinks() {
  DRINKS.forEach(d => {
    const card = document.createElement('div');
    card.className = 'drink-card';
    card.dataset.id = d.id;
    card.innerHTML = `
      <span class="d-emoji">${d.emoji}</span>
      <span class="d-name">${d.name}</span>
      <span class="d-desc">${d.desc}</span>`;
    card.addEventListener('click', () => selectDrink(d.id));
    drinkGrid.appendChild(card);
  });
}

function selectDrink(id) {
  state.drink = id;
  drinkGrid.querySelectorAll('.drink-card').forEach(c =>
    c.classList.toggle('selected', c.dataset.id === id));
  refreshOrderBtn();
}

// ── Size ──────────────────────────────────────────────
document.querySelectorAll('.size-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    state.size = btn.dataset.size;
    document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('selected'));
    btn.classList.add('selected');
  });
});

// ── Status ────────────────────────────────────────────
function setStatus(key, opts = {}) {
  state.status = key;
  const s = STATUS[key];

  Object.values(STATUS).forEach(st => statusRow.classList.remove(st.cls));
  statusRow.classList.add(s.cls);

  statusLabel.textContent  = s.label;
  statusDetail.textContent = opts.detail || s.detail;

  if (opts.drink) {
    pillDrink.textContent = opts.drink;
    pillSize.textContent  = SIZE_LABEL[opts.size] || opts.size;
    orderPill.style.display = 'inline-flex';
  } else if (key === 'idle' || key === 'done') {
    orderPill.style.display = 'none';
  }

  refreshOrderBtn();
}

function refreshOrderBtn() {
  const busy = ['received', 'preparing', 'dispensing'].includes(state.status);
  placeOrderBtn.disabled = !state.drink || busy;
}

// ── Error ─────────────────────────────────────────────
function setError(code, msg) {
  errorPanel.classList.add('has-error');
  noErrorMsg.style.display   = 'none';
  errorDetail.style.display  = 'block';
  errorCode.textContent = `ERR-${String(code).padStart(3, '0')}`;
  errorText.textContent = msg;
  errorTime.textContent = `at ${new Date().toLocaleTimeString()}`;
  clearErrorBtn.disabled = false;
  setStatus('error');
}

function clearError() {
  errorPanel.classList.remove('has-error');
  noErrorMsg.style.display  = 'block';
  errorDetail.style.display = 'none';
  clearErrorBtn.disabled = true;
  setStatus('idle');
  // Sync backend state to idle so new orders are accepted after clearing
  fetch('/api/test/reset', { method: 'POST' }).catch(() => {});
}

clearErrorBtn.addEventListener('click', clearError);

simulateErrorBtn.addEventListener('click', async () => {
  try {
    await fetch('/api/test/error', { method: 'POST' });
    // Backend now returns error state — next poll will pick it up,
    // but trigger immediately so the UI responds without waiting 2 s
    const res = await fetch('/api/status');
    const data = await res.json();
    if (data.error) setError(data.error.code, data.error.message);
  } catch {
    // Backend offline — simulate locally so the demo still works
    setError(500, 'Simulated hardware fault — axis limit exceeded');
  }
});

// ── Order Management ──────────────────────────────────
function addOrder(drinkId, size) {
  const d = DRINKS.find(x => x.id === drinkId);
  const order = {
    id:        nextOrderId++,
    drinkId,
    drinkName: d.name,
    emoji:     d.emoji,
    size,
    status:    'queued',
    time:      new Date().toLocaleTimeString(),
    timers:    [],
  };
  orders.unshift(order);
  renderOrders();
  return order;
}

function updateOrderStatus(id, status) {
  const order = orders.find(o => o.id === id);
  if (order) {
    order.status = status;
    renderOrders();
  }
}

function cancelOrder(id) {
  const order = orders.find(o => o.id === id);
  if (!order || order.status !== 'queued') return;
  order.timers.forEach(t => clearTimeout(t));
  order.timers = [];
  order.status = 'cancelled';
  renderOrders();
  showToast(`Order #${String(id).padStart(3,'0')} cancelled`);
}

function clearCompleted() {
  orders = orders.filter(o => o.status !== 'done' && o.status !== 'cancelled');
  renderOrders();
}

clearDoneBtn.addEventListener('click', clearCompleted);

function renderOrders() {
  const active = orders.filter(o => o.status !== 'done' && o.status !== 'cancelled').length;
  const hasDone = orders.some(o => o.status === 'done' || o.status === 'cancelled');

  if (orders.length === 0) {
    ordersEmpty.style.display      = 'block';
    ordersTableWrap.style.display  = 'none';
    orderCountBadge.style.display  = 'none';
    clearDoneBtn.disabled          = true;
    return;
  }

  ordersEmpty.style.display     = 'none';
  ordersTableWrap.style.display = 'block';
  clearDoneBtn.disabled         = !hasDone;

  if (active > 0) {
    orderCountBadge.style.display = 'inline';
    orderCountBadge.textContent   = active;
  } else {
    orderCountBadge.style.display = 'none';
  }

  ordersBody.innerHTML = orders.map(o => {
    const num      = `#${String(o.id).padStart(3, '0')}`;
    const sizeText = SIZE_LABEL[o.size];
    const canCancel = o.status === 'queued';
    const rowCls   = o.status === 'done' ? 'row-done' : o.status === 'cancelled' ? 'row-cancelled' : '';

    return `
      <tr class="${rowCls}" data-id="${o.id}">
        <td><span class="order-num">${num}</span></td>
        <td>
          <div class="order-drink-cell">
            <span class="order-drink-emoji">${o.emoji}</span>
            <span class="order-drink-name">${o.drinkName}</span>
          </div>
        </td>
        <td>${sizeText}</td>
        <td>${statusBadgeHTML(o.status)}</td>
        <td><span class="order-time">${o.time}</span></td>
        <td>
          ${canCancel
            ? `<button class="btn-cancel-order" data-id="${o.id}">Cancel</button>`
            : '—'}
        </td>
      </tr>`;
  }).join('');

  ordersBody.querySelectorAll('.btn-cancel-order').forEach(btn =>
    btn.addEventListener('click', () => cancelOrder(Number(btn.dataset.id))));
}

function statusBadgeHTML(status) {
  const labels = {
    queued: 'Queued', preparing: 'Preparing', dispensing: 'Dispensing',
    done: 'Done', cancelled: 'Cancelled', error: 'Error',
  };
  return `<span class="status-badge badge-${status}">
    <span class="badge-dot"></span>${labels[status] || status}
  </span>`;
}

// ── Order ─────────────────────────────────────────────
placeOrderBtn.addEventListener('click', async () => {
  if (!state.drink) return;
  const d = DRINKS.find(x => x.id === state.drink);
  const order = addOrder(state.drink, state.size);
  setStatus('received', { drink: d.name, size: state.size });

  try {
    const res = await fetch('/api/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ drink: state.drink, size: state.size, orderId: order.id }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    startPolling(order.id);
  } catch {
    simulateOrder(order);
  }
});

function simulateOrder(order) {
  showToast(`Order #${String(order.id).padStart(3,'0')} placed: ${order.drinkName} (${SIZE_LABEL[order.size]})`);
  const steps = [
    { key: 'preparing',  ms: 1600, detail: `Mixing ${order.drinkName}…` },
    { key: 'dispensing', ms: 3800, detail: 'Pouring into cup…' },
    { key: 'done',       ms: 6000, detail: `${order.drinkName} is ready! Enjoy!` },
  ];
  steps.forEach(({ key, ms, detail }) => {
    const t = setTimeout(() => {
      if (order.status === 'cancelled') return;
      updateOrderStatus(order.id, key);
      setStatus(key, { drink: order.drinkName, size: order.size, detail });
      if (key === 'done') setTimeout(() => setStatus('idle'), 3500);
    }, ms);
    order.timers.push(t);
  });
}

// ── Polling ───────────────────────────────────────────
function startPolling(orderId) {
  stopPolling();
  state.polling = setInterval(async () => {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) return;
      const data = await res.json();
      if (data.status) {
        setStatus(data.status, { drink: data.drink, size: data.size, detail: data.detail });
        if (orderId) updateOrderStatus(orderId, data.status);
      }
      if (data.error) setError(data.error.code, data.error.message);
      if (['done', 'idle', 'error'].includes(data.status)) stopPolling();
    } catch { /* backend offline */ }
  }, 2000);
}

function stopPolling() {
  clearInterval(state.polling);
  state.polling = null;
}

// ── Connection ────────────────────────────────────────
async function checkConnection() {
  try {
    const res = await fetch('/api/status', { signal: AbortSignal.timeout(2000) });
    if (res.ok) {
      connectionBadge.classList.add('online');
      connectionLabel.textContent = 'Connected';
      return;
    }
  } catch { /* ignore */ }
  connectionBadge.classList.remove('online');
  connectionLabel.textContent = 'Offline';
}

// ── Toast ─────────────────────────────────────────────
let toastTimer;
function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3000);
}

// ── Init ──────────────────────────────────────────────
renderDrinks();
setStatus('idle');
checkConnection();
setInterval(checkConnection, 10000);

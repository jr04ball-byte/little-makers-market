// Shared helpers for every page.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const money = c => "$" + (c / 100).toFixed(2);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const slugFromPath = () => decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");

async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json);
    init.headers["Content-Type"] = "application/json";
    init.method = init.method || "POST";
  }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = data.reason || data.detail?.message || (typeof data.detail === "string" ? data.detail : null) || data.error || r.statusText;
    throw Object.assign(new Error(msg), { status: r.status, data });
  }
  return data;
}

function toast(text, ms = 3200) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = text;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

function topbar(extra = "") {
  const el = document.createElement("header");
  el.className = "top";
  el.innerHTML = `<div class="wrap"><a class="brand" href="/"><span class="logo">✏️</span>Little Makers Market</a>
    <nav>${extra}<a href="/#how">How it works</a><a href="/#start">Open a market</a></nav></div>`;
  document.body.prepend(el);
}

let _ppConfig;
async function ppConfig() { return _ppConfig ||= await api("/api/config"); }

function loadScript(src, attrs = {}) {
  return new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = src; Object.entries(attrs).forEach(([k, v]) => s.setAttribute(k, v));
    s.onload = ok; s.onerror = () => fail(new Error("Could not load " + src));
    document.head.appendChild(s);
  });
}

async function loadPayPal() {
  if (window.paypal) return window.paypal;
  const cfg = await ppConfig();
  await loadScript(`https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(cfg.paypal_client_id)}&currency=${cfg.currency}&components=buttons&enable-funding=venmo,paylater`,
    { "data-page-type": "product-details" });
  return window.paypal;
}

async function loadPayPalSubscriptions() {
  if (window.paypalSub) return window.paypalSub;
  const cfg = await ppConfig();
  await loadScript(`https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(cfg.paypal_client_id)}&vault=true&intent=subscription&components=buttons`,
    { "data-namespace": "paypalSub" });
  return window.paypalSub;
}

function confetti(ms = 2600) {
  const c = document.createElement("canvas");
  c.className = "confetti"; document.body.appendChild(c);
  const ctx = c.getContext("2d");
  const resize = () => { c.width = innerWidth; c.height = innerHeight; };
  resize();
  const colors = ["#7a4fd6", "#ffc93c", "#ff6b57", "#3fb86b", "#4aa8ff"];
  const bits = Array.from({ length: 140 }, () => ({ x: Math.random() * c.width, y: -20 - Math.random() * c.height * .5,
    r: 4 + Math.random() * 6, vy: 2 + Math.random() * 4, vx: -1.5 + Math.random() * 3, a: Math.random() * 6, col: colors[Math.random() * 5 | 0] }));
  const end = performance.now() + ms;
  (function frame(t) {
    ctx.clearRect(0, 0, c.width, c.height);
    bits.forEach(b => { b.x += b.vx; b.y += b.vy; b.a += .1; ctx.save(); ctx.translate(b.x, b.y); ctx.rotate(b.a);
      ctx.fillStyle = b.col; ctx.fillRect(-b.r / 2, -b.r / 2, b.r, b.r * .6); ctx.restore(); });
    if (t < end) requestAnimationFrame(frame); else c.remove();
  })(performance.now());
}

function jarsHTML(b) {
  return `<div class="jars">
    <div class="jar save">🐷<b>${money(b.save || 0)}</b><span class="small muted">Save</span></div>
    <div class="jar spend">🛍️<b>${money(b.spend || 0)}</b><span class="small muted">Spend</span></div>
    <div class="jar give">💝<b>${money(b.give || 0)}</b><span class="small muted">Give</span></div></div>`;
}

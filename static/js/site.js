(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var site = JSON.parse(($("#site-data") || {}).textContent || "{}");

  /* ---------- header, progress, parallax ---------- */
  var header = $("#header"), prog = $("#progress"), px = $$(".hero-slides, .why-bg"), ticking = false;
  function onScroll() {
    var y = window.scrollY, h = document.documentElement.scrollHeight - window.innerHeight;
    header.classList.toggle("stuck", y > 30);
    prog.style.width = (h > 0 ? (y / h) * 100 : 0) + "%";
    if (!reduce) px.forEach(function (el) {
      var r = el.parentElement.getBoundingClientRect();
      if (r.bottom > 0 && r.top < window.innerHeight) el.style.setProperty("--py", (-r.top * 0.18).toFixed(1) + "px");
    });
    ticking = false;
  }
  window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();

  /* ---------- mobile menu ---------- */
  var burger = $("#burger"), nav = $("#nav");
  burger.addEventListener("click", function () {
    var o = nav.classList.toggle("open");
    burger.setAttribute("aria-expanded", o ? "true" : "false");
  });
  nav.addEventListener("click", function (e) { if (e.target.tagName === "A") { nav.classList.remove("open"); burger.setAttribute("aria-expanded", "false"); } });

  /* ---------- hero slideshow ---------- */
  var slides = $$(".slide"), dots = $$("#slideDots button"), cap = $("#slideCap"), cur = 0, timer;
  function show(i) {
    slides[cur].classList.remove("on"); dots[cur].classList.remove("on");
    cur = (i + slides.length) % slides.length;
    slides[cur].classList.add("on");
    void dots[cur].offsetWidth; dots[cur].classList.add("on");
    cap.textContent = slides[cur].dataset.cap || "";
  }
  function play() { clearInterval(timer); if (!reduce && slides.length > 1) timer = setInterval(function () { show(cur + 1); }, 6000); }
  if (slides.length) {
    cap.textContent = slides[0].dataset.cap || "";
    dots.forEach(function (d, i) { d.addEventListener("click", function () { show(i); play(); }); });
    play();
    document.addEventListener("visibilitychange", function () { document.hidden ? clearInterval(timer) : play(); });
  }

  /* ---------- reveal + counters ---------- */
  function countUp(el) {
    var raw = el.dataset.value || "0", target = parseFloat(raw) || 0, dec = (raw.split(".")[1] || "").length, t0 = null, dur = 1900;
    function fmt(v) { return dec ? v.toFixed(dec) : Math.round(v).toLocaleString("en-US"); }
    if (reduce) { el.textContent = fmt(target); return; }
    function step(t) {
      if (!t0) t0 = t;
      var p = Math.min((t - t0) / dur, 1), e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * e);
      if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(target);
    }
    requestAnimationFrame(step);
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (!en.isIntersecting) return;
      en.target.classList.add("in");
      $$(".count", en.target).forEach(countUp);
      if (en.target.classList.contains("count")) countUp(en.target);
      io.unobserve(en.target);
    });
  }, { threshold: 0.18 });
  $$(".reveal").forEach(function (el) { io.observe(el); });

  /* ---------- active nav ---------- */
  var links = {};
  $$("#nav a").forEach(function (a) { links[a.getAttribute("href").slice(1)] = a; });
  var spy = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (en.isIntersecting) {
        Object.keys(links).forEach(function (k) { links[k].classList.remove("on"); });
        if (links[en.target.id]) links[en.target.id].classList.add("on");
      }
    });
  }, { rootMargin: "-40% 0px -55% 0px" });
  Object.keys(links).forEach(function (id) { var el = document.getElementById(id); if (el) spy.observe(el); });

  /* ---------- product tabs ---------- */
  $$(".tab").forEach(function (t) {
    t.addEventListener("click", function () {
      $$(".tab").forEach(function (x) { x.classList.toggle("on", x === t); x.setAttribute("aria-selected", x === t ? "true" : "false"); });
      $$(".tabpanel").forEach(function (p) {
        var on = p.dataset.panel === t.dataset.tab;
        p.classList.toggle("on", on);
        if (on) $$(".reveal", p).forEach(function (el) { el.classList.add("in"); });
      });
    });
  });

  /* ---------- quote form ---------- */
  var form = $("#qform"), qProduct = $("#qProduct"), qMessage = $("#qMessage"), qExtra = $("#qExtra"), qMsg = $("#qMsg");
  function toQuote(product, message, extra) {
    if (product !== undefined) qProduct.value = product || "";
    if (message) qMessage.value = message;
    qExtra.value = extra || "";
    $("#contact").scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
    setTimeout(function () { $("[name=name]", form).focus({ preventScroll: true }); }, 700);
  }
  $$("[data-quote]").forEach(function (b) {
    b.addEventListener("click", function (e) {
      var p = b.getAttribute("data-quote");
      e.preventDefault();
      toQuote(p, p ? "Hello, I would like a quote for: " + p + "." : "", "");
    });
  });
  function waLink(text) { return "https://wa.me/" + (site.wa || "") + "?text=" + encodeURIComponent(text); }
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var d = {}; new FormData(form).forEach(function (v, k) { d[k] = v; });
    qMsg.className = "msg";
    if (!d.name || !(d.phone || d.email) || !d.message) { qMsg.className = "msg err"; qMsg.textContent = "Please add your name, a phone number or email, and a short message."; return; }
    qMsg.textContent = "Sending...";
    fetch("/api/quote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok) { form.reset(); qExtra.value = ""; qMsg.textContent = "Thank you. Your request has been received and we will contact you soon."; }
        else { qMsg.className = "msg err"; qMsg.textContent = res.j.error || "Something went wrong. Please call or WhatsApp us."; }
      })
      .catch(function () {
        qMsg.className = "msg err"; qMsg.textContent = "We could not send that here, so we are opening WhatsApp for you.";
        window.open(waLink("Hello Solar Support. " + d.message + " (" + d.name + ", " + (d.phone || d.email) + ")"), "_blank", "noopener");
      });
  });

  /* ---------- calculator ---------- */
  var data = JSON.parse(($("#calc-data") || {}).textContent || "{}");
  var apps = data.appliances || [], pk = data.packages || [], sun = data.sun || 5.5, qty = apps.map(function (a) { return a.qty || 0; });
  var grid = $("#appl");
  function fmt(n, d) { return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  apps.forEach(function (a, i) {
    var row = document.createElement("div"); row.className = "ap";
    row.innerHTML = '<div><b></b><small></small></div><div class="step"><button type="button" aria-label="Fewer">&minus;</button><output>0</output><button type="button" aria-label="More">+</button></div>';
    $("b", row).textContent = a.name;
    $("small", row).textContent = a.watts + " W, " + a.hours + " h per day";
    var out = $("output", row), bt = $$("button", row);
    out.textContent = qty[i]; row.classList.toggle("on", qty[i] > 0);
    function set(n) { qty[i] = Math.max(0, Math.min(30, n)); out.textContent = qty[i]; row.classList.toggle("on", qty[i] > 0); calc(); }
    bt[0].addEventListener("click", function () { set(qty[i] - 1); });
    bt[1].addEventListener("click", function () { set(qty[i] + 1); });
    grid.appendChild(row);
  });
  var share = $("#cShare");
  share.addEventListener("change", calc);
  var last = null;
  function calc() {
    var kwh = 0, sumW = 0, maxW = 0, list = [];
    apps.forEach(function (a, i) {
      if (!qty[i]) return;
      kwh += qty[i] * a.watts * a.hours / 1000; sumW += qty[i] * a.watts; maxW = Math.max(maxW, a.watts);
      list.push(qty[i] + " x " + a.name);
    });
    var peak = Math.max(sumW * 0.7, maxW) / 1000, inv = peak * 1.25, bat = kwh * parseFloat(share.value) / 0.9, pv = kwh / (sun * 0.8);
    $("#rKwh").textContent = fmt(kwh, 1); $("#rPeak").textContent = fmt(peak, 1);
    $("#tInv").textContent = fmt(inv, 1) + " kVA"; $("#tBat").textContent = fmt(bat, 1) + " kWh"; $("#tPv").textContent = fmt(pv, 1) + " kW";
    var big = pk.length ? pk[pk.length - 1] : { kva: 8, battery: 10, pv: 6 };
    $("#bInv").style.width = Math.min(100, inv / big.kva * 100) + "%";
    $("#bBat").style.width = Math.min(100, bat / big.battery * 100) + "%";
    $("#bPv").style.width = Math.min(100, pv / big.pv * 100) + "%";
    var reco = $("#reco"), qb = $("#cQuote"), wa = $("#cWa");
    if (!kwh) {
      reco.className = "reco"; reco.innerHTML = '<p class="muted">Add an appliance to see your recommended system.</p>';
      qb.disabled = true; wa.href = waLink("Hello Solar Support, I would like help choosing a solar system."); last = null; return;
    }
    var pick = null;
    for (var k = 0; k < pk.length; k++) { if (pk[k].kva >= inv && pk[k].battery >= bat * 0.8 && pk[k].pv >= pv * 0.8) { pick = pk[k]; break; } }
    var summary = "Appliances: " + list.join(", ") + ". Daily energy " + fmt(kwh, 1) + " kWh, peak load " + fmt(peak, 1) + " kW.";
    var name, lines, price = "";
    if (pick) {
      name = pick.name;
      lines = [fmt(pick.kva, 1) + " kVA inverter", fmt(pick.battery, 1) + " kWh battery", fmt(pick.pv, 1) + " kW of solar panels", "Makes about " + fmt(pick.pv * sun * 0.8, 1) + " kWh on a sunny day"];
      price = pick.price != null ? "US$" + fmt(pick.price, 0) + (pick.unit ? " " + pick.unit : "") : "Request price";
    } else {
      name = "Custom system";
      lines = ["Your load is larger than our standard packages.", "We will design a bigger system after a site survey.", "Needed: about " + fmt(inv, 1) + " kVA, " + fmt(bat, 1) + " kWh battery, " + fmt(pv, 1) + " kW solar"];
      price = "Free site survey";
    }
    reco.className = "reco has";
    reco.innerHTML = "<small>Recommended</small><h4></h4><ul></ul><div class='rp'></div>";
    $("h4", reco).textContent = name; $(".rp", reco).textContent = price;
    lines.forEach(function (l) { var li = document.createElement("li"); li.textContent = l; $("ul", reco).appendChild(li); });
    qb.disabled = false;
    last = { name: name, summary: summary };
    wa.href = waLink("Hello Solar Support, I used your calculator. " + summary + " Recommended: " + name + ". Please send me a quote.");
  }
  $("#cQuote").addEventListener("click", function () {
    if (!last) return;
    toQuote(last.name, "I used the solar calculator. " + last.summary + " Please send me a quote for the " + last.name + ".", last.summary);
  });
  calc();

  /* ---------- gallery filter + lightbox ---------- */
  var items = $$(".gitem");
  $$(".gfilters .chip").forEach(function (c) {
    c.addEventListener("click", function () {
      $$(".gfilters .chip").forEach(function (x) { x.classList.toggle("on", x === c); });
      items.forEach(function (it) { it.hidden = !(c.dataset.f === "all" || it.dataset.cat === c.dataset.f); });
    });
  });
  var lb = $("#lightbox"), lbImg = $("img", lb), lbCap = $("p", lb), idx = 0;
  function vis() { return items.filter(function (i) { return !i.hidden; }); }
  function open(i) { var v = vis(); idx = (i + v.length) % v.length; lbImg.src = v[idx].dataset.full; lbImg.alt = v[idx].dataset.title; lbCap.textContent = v[idx].dataset.title; lb.hidden = false; document.body.style.overflow = "hidden"; }
  function close() { lb.hidden = true; document.body.style.overflow = ""; }
  items.forEach(function (it) { it.addEventListener("click", function () { open(vis().indexOf(it)); }); });
  $(".lb-x", lb).addEventListener("click", close); $(".lb-p", lb).addEventListener("click", function () { open(idx - 1); }); $(".lb-n", lb).addEventListener("click", function () { open(idx + 1); });
  lb.addEventListener("click", function (e) { if (e.target === lb) close(); });
  document.addEventListener("keydown", function (e) { if (lb.hidden) return; if (e.key === "Escape") close(); if (e.key === "ArrowLeft") open(idx - 1); if (e.key === "ArrowRight") open(idx + 1); });

  /* ---------- video reels: load and play only when visible ---------- */
  var vio = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      var v = en.target;
      if (en.isIntersecting) {
        if (!v.src && v.dataset.src) v.src = v.dataset.src;
        var p = v.play(); if (p && p.catch) p.catch(function () {});
      } else { v.pause(); }
    });
  }, { threshold: 0.35 });
  $$(".reel video").forEach(function (v) { vio.observe(v); });
})();

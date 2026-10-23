// BA WorkTrack front-end behaviour. No inline scripts: everything is wired from data-* attributes.
(function () {
  "use strict";

  var csrf = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrf ? csrf.content : "";

  // ---- theme ---------------------------------------------------------------
  function setTheme(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    try { localStorage.setItem("wt-theme", theme); } catch (e) { /* ignore */ }
    document.dispatchEvent(new CustomEvent("themechange"));
  }
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (toggle) {
      var current = document.documentElement.getAttribute("data-bs-theme");
      setTheme(current === "dark" ? "light" : "dark");
    }
    var sidebarToggle = event.target.closest("[data-sidebar-toggle]");
    if (sidebarToggle) document.body.classList.toggle("sidebar-open");
    if (event.target.classList.contains("sidebar-backdrop")) document.body.classList.remove("sidebar-open");
  });

  // ---- toasts --------------------------------------------------------------
  function showToast(message, category) {
    var container = document.getElementById("toasts");
    if (!container || !message) return;
    var icons = { success: "bi-check-circle-fill", danger: "bi-exclamation-octagon-fill", warning: "bi-exclamation-triangle-fill", info: "bi-info-circle-fill" };
    var el = document.createElement("div");
    el.className = "toast align-items-center border-0 text-bg-" + (category === "danger" ? "danger" : category === "warning" ? "warning" : "dark");
    el.setAttribute("role", category === "danger" ? "alert" : "status");
    el.setAttribute("aria-live", "polite");
    var body = document.createElement("div");
    body.className = "d-flex";
    var text = document.createElement("div");
    text.className = "toast-body";
    var icon = document.createElement("i");
    icon.className = "bi me-2 " + (icons[category] || icons.info);
    text.appendChild(icon);
    text.appendChild(document.createTextNode(message));
    var close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close btn-close-white me-2 m-auto";
    close.setAttribute("data-bs-dismiss", "toast");
    close.setAttribute("aria-label", "Close");
    body.appendChild(text);
    body.appendChild(close);
    el.appendChild(body);
    container.appendChild(el);
    var toast = new bootstrap.Toast(el, { delay: category === "danger" ? 7000 : 3500 });
    el.addEventListener("hidden.bs.toast", function () { el.remove(); });
    toast.show();
  }
  window.wtToast = showToast;
  document.body.addEventListener("toast", function (event) {
    showToast(event.detail.message, event.detail.category);
  });

  // ---- HTMX: send the CSRF token with every request --------------------------
  document.body.addEventListener("htmx:configRequest", function (event) {
    event.detail.headers["X-CSRF-Token"] = csrfToken;
  });
  document.body.addEventListener("htmx:afterRequest", function (event) {
    var form = event.detail.elt;
    if (event.detail.successful && form && form.matches && form.matches("form[data-reset-after]")) form.reset();
  });
  document.body.addEventListener("htmx:responseError", function () {
    showToast("Something went wrong. Please try again.", "danger");
  });
  document.body.addEventListener("htmx:sendError", function () {
    showToast("Can't reach the server. Check your connection.", "danger");
  });

  // ---- confirm before destructive actions ------------------------------------
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  }, true);

  // ---- auto-submit filters ---------------------------------------------------
  document.addEventListener("change", function (event) {
    var el = event.target;
    if (el.matches("[data-autosubmit]")) {
      var form = el.form;
      if (form && form.requestSubmit) form.requestSubmit(); else if (form) form.submit();
    }
    if (el.matches("[data-keep-toggle]")) {
      var item = el.closest(".review-item");
      if (item) item.classList.toggle("excluded", !el.checked);
    }
    if (el.matches("[data-show-when]")) syncConditional();
  });

  // Show/hide fields that only apply to one choice (e.g. JIRA vs ADO settings)
  function syncConditional() {
    document.querySelectorAll("[data-visible-for]").forEach(function (block) {
      var source = document.querySelector(block.dataset.visibleSource);
      if (!source) return;
      var value = source.type === "radio" ? (document.querySelector(block.dataset.visibleSource + ":checked") || {}).value : source.value;
      var visible = block.dataset.visibleFor.split(",").indexOf(value) !== -1;
      block.hidden = !visible;
      block.querySelectorAll("input,select,textarea").forEach(function (f) { f.disabled = !visible; });
    });
  }

  // ---- keyboard: "/" focuses search ------------------------------------------
  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && !event.target.closest("input,textarea,select,[contenteditable]")) {
      var search = document.getElementById("global-search");
      if (search) { event.preventDefault(); search.focus(); }
    }
    if (event.key === "Escape") {
      var results = document.getElementById("search-results");
      if (results) results.innerHTML = "";
    }
  });
  document.addEventListener("click", function (event) {
    var results = document.getElementById("search-results");
    if (results && !event.target.closest(".search-box")) results.innerHTML = "";
  });

  // ---- running timer -----------------------------------------------------------
  function tickTimers() {
    document.querySelectorAll("[data-timer-started]").forEach(function (el) {
      var started = new Date(el.dataset.timerStarted).getTime();
      var seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
      var h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
      el.textContent = h + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
    });
  }
  setInterval(tickTimers, 1000);

  // ---- charts ------------------------------------------------------------------
  var charts = [];
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  var PALETTE = ["#6366f1", "#06b6d4", "#f59e0b", "#10b981", "#ec4899", "#8b5cf6", "#ef4444", "#84cc16"];
  var STATUS_COLORS = { "To Do": "#94a3b8", "In Progress": "#0ea5e9", "In Review": "#f59e0b", "Done": "#22c55e" };

  function buildCharts() {
    if (typeof Chart === "undefined") return;
    charts.forEach(function (c) { c.destroy(); });
    charts = [];
    var dataEl = document.getElementById("chart-data");
    if (!dataEl) return;
    var data = JSON.parse(dataEl.textContent);
    var text = cssVar("--wt-muted"), grid = cssVar("--wt-border");
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = text;
    document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
      var spec = data[canvas.dataset.chart];
      if (!spec) return;
      var type = canvas.dataset.type || "bar";
      var colors = canvas.dataset.chart === "status"
        ? spec.labels.map(function (l) { return STATUS_COLORS[l] || PALETTE[0]; })
        : (type === "doughnut" || canvas.dataset.multicolor ? PALETTE : cssVar("--wt-brand"));
      var dataset = {
        label: canvas.dataset.label || "",
        data: spec.values,
        backgroundColor: type === "line" ? "rgba(99,102,241,.12)" : colors,
        borderColor: type === "line" ? cssVar("--wt-brand") : (type === "doughnut" ? cssVar("--wt-surface") : colors),
        borderWidth: type === "doughnut" ? 2 : (type === "line" ? 2.5 : 0),
        borderRadius: type === "bar" ? 6 : 0,
        fill: type === "line",
        tension: 0.35,
        pointRadius: type === "line" ? 2.5 : 0,
        maxBarThickness: 38
      };
      var horizontal = canvas.dataset.horizontal === "1";
      var options = {
        responsive: true, maintainAspectRatio: false,
        indexAxis: horizontal ? "y" : "x",
        plugins: { legend: { display: type === "doughnut", position: "bottom", labels: { boxWidth: 10, usePointStyle: true } },
                   tooltip: { backgroundColor: "#111827", padding: 10, cornerRadius: 8 } },
        scales: type === "doughnut" ? {} : {
          x: { grid: { display: horizontal, color: grid }, ticks: { color: text } },
          y: { grid: { display: !horizontal, color: grid }, ticks: { color: text, precision: 0 }, beginAtZero: true }
        }
      };
      if (type === "doughnut") options.cutout = "68%";
      charts.push(new Chart(canvas, { type: type, data: { labels: spec.labels, datasets: [dataset] }, options: options }));
    });
  }
  document.addEventListener("themechange", buildCharts);

  // ---- Kanban drag and drop --------------------------------------------------------
  function initBoard() {
    if (typeof Sortable === "undefined") return;
    var workflowEl = document.getElementById("workflow-data");
    if (!workflowEl) return;
    var workflow = JSON.parse(workflowEl.textContent);
    document.querySelectorAll(".board-list").forEach(function (list) {
      Sortable.create(list, {
        group: "board", animation: 150, ghostClass: "sortable-ghost", dragClass: "sortable-drag",
        filter: ".is-locked", preventOnFilter: false,  // read-only item types stay where they are
        onMove: function (evt) {
          var from = evt.from.dataset.status, to = evt.to.dataset.status;
          document.querySelectorAll(".board-list").forEach(function (l) { l.classList.remove("drop-denied"); });
          if (from !== to && workflow[from].indexOf(to) === -1) {
            evt.to.classList.add("drop-denied");
            return false;
          }
          return true;
        },
        onEnd: function (evt) {
          document.querySelectorAll(".board-list").forEach(function (l) { l.classList.remove("drop-denied"); });
          if (evt.from === evt.to) return;
          var card = evt.item, status = evt.to.dataset.status;
          var body = new URLSearchParams({ status: status });
          fetch("/tasks/" + card.dataset.taskId + "/status", {
            method: "POST", body: body, credentials: "same-origin",
            headers: { "X-CSRF-Token": csrfToken, "HX-Request": "true" }
          }).then(function (response) {
            var trigger = response.headers.get("HX-Trigger");
            var detail = trigger ? JSON.parse(trigger).toast : null;
            if (!response.ok || (detail && detail.category === "danger")) {
              evt.from.insertBefore(card, evt.from.children[evt.oldIndex] || null);
            }
            if (detail) showToast(detail.message, detail.category);
            updateCounts();
          }).catch(function () {
            evt.from.insertBefore(card, evt.from.children[evt.oldIndex] || null);
            showToast("Couldn't save the move. Check your connection.", "danger");
          });
        }
      });
    });
  }
  function updateCounts() {
    document.querySelectorAll(".board-col").forEach(function (col) {
      var counter = col.querySelector("[data-count]");
      if (counter) counter.textContent = col.querySelectorAll(".board-card").length;
    });
  }

  // Keyboard alternative to drag and drop: the card menu buttons post the status change
  document.addEventListener("click", function (event) {
    var move = event.target.closest("[data-move-to]");
    if (!move) return;
    event.preventDefault();
    var card = move.closest(".board-card");
    var target = document.querySelector('.board-list[data-status="' + move.dataset.moveTo + '"]');
    fetch("/tasks/" + card.dataset.taskId + "/status", {
      method: "POST", body: new URLSearchParams({ status: move.dataset.moveTo }), credentials: "same-origin",
      headers: { "X-CSRF-Token": csrfToken, "HX-Request": "true" }
    }).then(function (response) {
      var trigger = response.headers.get("HX-Trigger");
      var detail = trigger ? JSON.parse(trigger).toast : null;
      if (response.ok && !(detail && detail.category === "danger") && target) target.prepend(card);
      if (detail) showToast(detail.message, detail.category);
      updateCounts();
    });
  });

  document.addEventListener("DOMContentLoaded", function () {
    buildCharts();
    initBoard();
    tickTimers();
    syncConditional();
    var flash = document.getElementById("flash-data");
    if (flash) {
      var f = JSON.parse(flash.textContent);
      showToast(f.message, f.category);
    }
  });
})();

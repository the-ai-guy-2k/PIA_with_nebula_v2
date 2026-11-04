(() => {
  const byId = (id) => document.getElementById(id);
  const labels = { exact: "Exact image", representative: "Representative image", "text-only": "No image" };
  const esc = (value) => value == null || value === "" ? "Unknown" : String(value);

  // Render each source independently. A slow optional enrichment/status request
  // must not hold remembered purchases or deterministic patterns behind it.
  [
    ["/api/memory", renderMemory],
    ["/api/analytics", renderAnalytics],
    ["/api/ai-status", renderAi],
    ["/api/visual-recall?view=all", renderFood],
  ].forEach(([url, render]) => {
    loadJson(url).then(
      (value) => render({ status: "fulfilled", value }),
      () => render({ status: "rejected" }),
    );
  });

  async function loadJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) throw new Error("Data could not be loaded.");
    return payload;
  }

  function renderMemory(result) {
    const container = byId("recent-list");
    if (result.status !== "fulfilled" || !Array.isArray(result.value.purchases)) {
      container.replaceChildren(message("Purchase history could not be loaded.", true));
      return;
    }
    const purchases = result.value.purchases;
    byId("kpi-purchases").textContent = String(purchases.length);
    container.replaceChildren();
    if (!purchases.length) {
      container.append(message("No purchases yet", false, "Upload a receipt to begin building Purchase Memory."));
      return;
    }
    purchases.slice(0, 5).forEach((purchase) => {
      const link = document.createElement("a");
      link.className = "recent-row";
      link.href = `/memory#${encodeURIComponent(purchase.memory_id)}`;
      const info = document.createElement("span");
      const merchant = document.createElement("span");
      merchant.className = "recent-merchant";
      merchant.textContent = esc(purchase.merchant);
      const meta = document.createElement("span");
      meta.className = "recent-meta";
      const count = Number.isFinite(Number(purchase.item_count)) ? Number(purchase.item_count) : 0;
      meta.textContent = `${count} purchased item${count === 1 ? "" : "s"}`;
      info.append(merchant, meta);
      const date = document.createElement("span");
      date.className = "recent-date";
      date.textContent = purchase.purchase_date || "Date unknown";
      link.append(info, date);
      container.appendChild(link);
    });
  }

  function renderAnalytics(result) {
    const repeatList = byId("overview-repeat-list");
    const repeated = byId("most-repeated");
    const merchants = byId("top-merchants");
    const needs = byId("need-want-counts");
    if (result.status !== "fulfilled" || !result.value.summary) {
      byId("kpi-repeats").textContent = "—";
      byId("kpi-food").textContent = "—";
      [repeatList, repeated, merchants, needs].forEach((node) => node.replaceChildren(message("Purchase patterns could not be loaded.", true)));
      return;
    }
    const report = result.value;
    byId("kpi-repeats").textContent = String(report.summary.repeating_items ?? 0);
    byId("kpi-food").textContent = String(report.classifications?.food?.food ?? 0);
    const repeats = (report.repeat_items || []).filter((item) => item.repeating);
    renderBars(repeatList, repeats.slice(0, 5));
    byId("repeat-scope").textContent = `Top ${Math.min(5, repeats.length)} of ${repeats.length} repeating item identities · all remembered history. Bars show recorded purchase occurrences, not a forecast.`;
    renderMostRepeated(repeated, repeats.slice(0, 4));
    renderMerchants(merchants, (report.merchants || []).slice(0, 5));
    renderNeeds(needs, report.classifications?.need_want || {});
  }

  function renderBars(container, records) {
    container.replaceChildren();
    if (!records.length) {
      container.append(message("No repeat patterns yet", false, "More confirmed purchases are needed."));
      return;
    }
    const max = Math.max(...records.map((item) => Number(item.occurrence_count) || 0), 1);
    records.forEach((item) => {
      const row = document.createElement("div");
      row.className = "bar-row";
      const name = document.createElement("span");
      name.className = "bar-label";
      name.textContent = esc(item.item_name);
      const meter = document.createElement("meter");
      meter.min = 0;
      meter.max = max;
      meter.value = Math.min(max, Number(item.occurrence_count) || 0);
      meter.setAttribute("aria-label", `${esc(item.item_name)}: ${item.occurrence_count} purchase occurrences`);
      const count = document.createElement("span");
      count.className = "bar-count";
      count.textContent = `${item.occurrence_count} purchases`;
      row.append(name, meter, count);
      container.appendChild(row);
    });
  }

  function renderMostRepeated(container, records) {
    container.replaceChildren();
    if (!records.length) {
      container.append(message("No repeat patterns yet", false, "More confirmed purchases are needed."));
      return;
    }
    records.forEach((item) => {
      const card = document.createElement("article");
      card.className = "line-card";
      const title = document.createElement("h3");
      title.textContent = esc(item.item_name);
      const count = document.createElement("p");
      count.className = "hint";
      count.textContent = `${item.occurrence_count} purchase occurrences`;
      card.append(title, count);
      const interval = document.createElement("p");
      interval.className = "hint";
      interval.textContent = item.frequency_status === "calculated"
        ? `Observed average interval: ${item.average_interval_days} days · latest interval: ${item.latest_interval_days} days`
        : "Not enough dated purchases to calculate an interval.";
      card.appendChild(interval);
      container.appendChild(card);
    });
  }

  function renderMerchants(container, records) {
    container.replaceChildren();
    if (!records.length) {
      container.append(message("No merchant counts yet.", false));
      return;
    }
    records.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "mini-count";
      const merchant = document.createElement("span");
      merchant.textContent = esc(entry.merchant);
      const count = document.createElement("strong");
      count.textContent = `${entry.purchase_count} ${Number(entry.purchase_count) === 1 ? "purchase" : "purchases"}`;
      row.append(merchant, count);
      container.appendChild(row);
    });
  }

  function renderNeeds(container, counts) {
    container.replaceChildren();
    const rows = [["Need", counts.need ?? 0], ["Want", counts.want ?? 0], ["Unknown", counts.unknown ?? 0]];
    const max = Math.max(...rows.map((row) => Number(row[1]) || 0), 1);
    rows.forEach(([label, value]) => {
      const row = document.createElement("div");
      row.className = "meter-row";
      const name = document.createElement("span");
      name.textContent = label;
      const meter = document.createElement("meter");
      meter.min = 0;
      meter.max = max;
      meter.value = Number(value) || 0;
      meter.setAttribute("aria-label", `${label}: ${value} remembered items`);
      const amount = document.createElement("strong");
      amount.textContent = String(value);
      row.append(name, meter, amount);
      container.appendChild(row);
    });
  }

  function renderAi(result) {
    const status = byId("kpi-ai");
    const note = byId("kpi-ai-note");
    if (result.status !== "fulfilled" || !result.value) {
      status.textContent = "Unavailable";
      note.textContent = "Status could not be checked";
      return;
    }
    const configured = result.value.status === "configured";
    status.textContent = configured ? "Available" : "Unavailable";
    note.textContent = configured ? "Configured · health not verified" : "Query capability unavailable";
  }

  function renderFood(result) {
    const container = byId("food-preview");
    container.replaceChildren();
    const report = result.status === "fulfilled" ? result.value : null;
    if (!report || !Array.isArray(report.items)) {
      container.append(message("Food recall preview is unavailable.", true, "Your other purchase history remains available."));
      return;
    }
    if (!report.items.length) {
      container.append(message("No food recall yet", false, "Walmart food purchases classified as food will appear here."));
      return;
    }
    report.items.slice(0, 3).forEach((item) => {
      const card = document.createElement("article");
      card.className = "food-preview";
      if (item.image_available && (item.display === "exact" || item.display === "representative")) {
        const image = document.createElement("img");
        image.src = `/api/visual-recall/enrichments/${encodeURIComponent(item.enrichment_id)}/image`;
        image.alt = `${labels[item.display]} for ${esc(item.confirmed_item_name)}`;
        image.addEventListener("error", () => {
          image.remove();
          type.textContent = "No image";
        }, { once: true });
        card.appendChild(image);
      }
      const name = document.createElement("p");
      name.className = "food-preview-name";
      name.textContent = esc(item.confirmed_item_name);
      const type = document.createElement("p");
      type.className = "food-preview-label";
      type.textContent = labels[item.display] || "No image";
      const trace = document.createElement("a");
      trace.href = `/memory#${encodeURIComponent(item.memory_id)}`;
      trace.className = "food-preview-label";
      trace.textContent = `${esc(item.purchase_date)} · View purchase`;
      card.append(name, type, trace);
      container.appendChild(card);
    });
  }

  function message(title, isError, detail) {
    const box = document.createElement("div");
    box.className = "empty-state";
    if (isError) box.setAttribute("role", "alert");
    const heading = document.createElement("strong");
    heading.textContent = title;
    box.appendChild(heading);
    if (detail) {
      const text = document.createElement("span");
      text.textContent = detail;
      box.appendChild(text);
    }
    if (isError) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "button-secondary";
      retry.textContent = "Retry";
      retry.addEventListener("click", () => window.location.reload());
      box.appendChild(retry);
    }
    return box;
  }
})();
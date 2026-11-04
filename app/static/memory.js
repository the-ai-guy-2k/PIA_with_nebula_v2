const list = document.querySelector("#memory-list");
const detail = document.querySelector("#memory-detail");
const summary = document.querySelector("#memory-summary");
const items = document.querySelector("#memory-items");

const FOOD = ["food", "non-food", "unknown"];
const NEED = ["need", "want", "unknown"];
const DURABILITY = ["consumable", "long-term", "unknown"];

loadHistory();
window.addEventListener("hashchange", openHashedPurchase);

async function loadHistory() {
  list.replaceChildren();
  const filter = new URLSearchParams(window.location.search).get("filter");
  const query = filter ? `?filter=${encodeURIComponent(filter)}` : "";
  showPending(list, "Loading purchase history…");
  try {
    const response = await fetch(`/api/memory${query}`);
    const payload = await readJson(response);
    if (!response.ok || !payload || !Array.isArray(payload.purchases)) {
      showRejected(list, "Purchase history", payload && payload.reason ? payload.reason : "Purchase history could not be loaded.");
      return;
    }
    renderList(payload.purchases);
    openHashedPurchase();
  } catch (_error) {
    showRejected(list, "Purchase history", "Purchase history could not be loaded.");
  }
}

function renderList(purchases) {
  list.replaceChildren();
  if (!purchases.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No remembered purchases match this view.";
    list.appendChild(empty);
    return;
  }
  purchases.forEach((purchase) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "memory-card";
    button.dataset.memoryId = purchase.memory_id;
    const heading = document.createElement("strong");
    heading.textContent = purchase.merchant || "Unknown merchant";
    const meta = document.createElement("p");
    meta.className = "hint";
    meta.textContent = `${purchase.purchase_date || "Unknown date"} · ${purchase.item_count} purchased item${purchase.item_count === 1 ? "" : "s"}`;
    button.append(heading, meta);
    button.addEventListener("click", () => {
      window.location.hash = purchase.memory_id;
    });
    list.appendChild(button);
  });
}

function openHashedPurchase() {
  const memoryId = window.location.hash.replace("#", "").trim();
  if (!memoryId) {
    detail.hidden = true;
    return;
  }
  loadMemory(memoryId);
}

async function loadMemory(memoryId) {
  detail.hidden = false;
  summary.replaceChildren();
  items.replaceChildren();
  showPending(summary, "Loading remembered purchase…");
  try {
    const response = await fetch(`/api/memory/${encodeURIComponent(memoryId)}`);
    const payload = await readJson(response);
    if (!response.ok || !payload || payload.status !== "remembered") {
      showRejected(summary, "Remembered purchase", payload && payload.reason ? payload.reason : "The remembered purchase was not found.");
      return;
    }
    renderMemory(payload);
  } catch (_error) {
    showRejected(summary, "Remembered purchase", "The remembered purchase was not found.");
  }
}

function renderMemory(memory) {
  summary.replaceChildren();
  const fields = document.createElement("dl");
  addField(fields, "Purchase date", memory.purchase_date);
  addField(fields, "Purchase time", memory.purchase_time);
  addField(fields, "Merchant", memory.merchant);
  addField(fields, "Purchase ID", memory.purchase_id);
  addField(fields, "Memory ID", memory.memory_id);
  summary.appendChild(fields);
  items.replaceChildren();
  (memory.items || []).forEach((item) => {
    items.appendChild(renderItem(memory.memory_id, item));
  });
}

function renderItem(memoryId, item) {
  const card = document.createElement("article");
  card.className = "line-card";
  const heading = document.createElement("h3");
  heading.textContent = item.item_name;
  const fields = document.createElement("dl");
  addField(fields, "Quantity", item.quantity);
  addField(fields, "Unit price", item.unit_price);
  addField(fields, "Line total", item.line_total);
  const form = document.createElement("form");
  form.className = "classification-grid";
  form.append(
    choiceField("Food or non-food", "food_classification", FOOD, item.food_classification),
    choiceField("Need or want", "need_want_classification", NEED, item.need_want_classification),
    choiceField("Consumable or long-term", "durability_classification", DURABILITY, item.durability_classification),
  );
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "Save classification";
  const status = document.createElement("p");
  status.className = "hint";
  status.setAttribute("role", "status");
  form.append(button, status);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    saveClassification(form, memoryId, item.memory_item_id, status);
  });
  card.append(heading, fields, form);
  return card;
}

function choiceField(label, name, values, selected) {
  const wrap = document.createElement("label");
  wrap.textContent = label;
  const select = document.createElement("select");
  select.name = name;
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    option.selected = value === selected;
    select.appendChild(option);
  });
  wrap.appendChild(select);
  return wrap;
}

async function saveClassification(form, memoryId, memoryItemId, status) {
  const button = form.querySelector("button");
  button.disabled = true;
  status.textContent = "Saving classification…";
  const body = {
    food_classification: form.querySelector("[name='food_classification']").value,
    need_want_classification: form.querySelector("[name='need_want_classification']").value,
    durability_classification: form.querySelector("[name='durability_classification']").value,
  };
  try {
    const response = await fetch(`/api/memory/${encodeURIComponent(memoryId)}/items/${encodeURIComponent(memoryItemId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await readJson(response);
    if (response.ok && payload && payload.status === "remembered") {
      status.textContent = "Classification saved.";
      renderMemory(payload);
      return;
    }
    status.textContent = payload && payload.reason ? payload.reason : "The classification could not be saved.";
  } catch (_error) {
    status.textContent = "The classification could not be saved.";
  } finally {
    button.disabled = false;
  }
}

function addField(listElement, label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value == null || value === "" ? "Unknown" : String(value);
  listElement.append(term, description);
}

function showPending(container, message) {
  container.replaceChildren();
  const title = document.createElement("p");
  title.className = "result-title";
  title.textContent = message;
  container.appendChild(title);
}

function showRejected(container, title, reason) {
  container.replaceChildren();
  const heading = document.createElement("p");
  heading.className = "result-title";
  heading.textContent = title;
  const detailText = document.createElement("p");
  detailText.textContent = reason;
  container.append(heading, detailText);
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

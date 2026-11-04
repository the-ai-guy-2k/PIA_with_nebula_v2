const statusBox = document.querySelector("#analytics-status");
const summarySection = document.querySelector("#summary-section");
const summaryGrid = document.querySelector("#summary-grid");
const repeatSection = document.querySelector("#repeat-section");
const repeatList = document.querySelector("#repeat-list");
const merchantSection = document.querySelector("#merchant-section");
const merchantList = document.querySelector("#merchant-list");
const classificationSection = document.querySelector("#classification-section");
const classificationList = document.querySelector("#classification-list");

loadAnalytics();

async function loadAnalytics() {
  showMessage(statusBox, "Loading purchase patterns…");
  try {
    const response = await fetch("/api/analytics");
    const report = await readJson(response);
    if (!response.ok || !report || !report.summary) {
      showMessage(statusBox, report && report.reason ? report.reason : "Purchase patterns could not be loaded.");
      return;
    }
    renderReport(report);
  } catch (_error) {
    showMessage(statusBox, "Purchase patterns could not be loaded.");
  }
}

function renderReport(report) {
  statusBox.replaceChildren();
  if (report.status === "empty") {
    showMessage(statusBox, report.reason || "No remembered purchases yet.");
  }
  summarySection.hidden = false;
  repeatSection.hidden = false;
  merchantSection.hidden = false;
  classificationSection.hidden = false;
  renderSummary(report.summary);
  renderItems(report.repeat_items || []);
  renderMerchants(report.merchants || []);
  renderClassifications(report.classifications || {});
}

function renderSummary(summary) {
  summaryGrid.replaceChildren();
  const cards = [
    ["Remembered purchases", summary.remembered_purchases],
    ["Remembered items", summary.remembered_items],
    ["Unique items", summary.unique_items],
    ["Repeating items", summary.repeating_items],
    ["Earliest purchase", summary.earliest_purchase_date],
    ["Latest purchase", summary.latest_purchase_date],
  ];
  cards.forEach(([label, value]) => summaryGrid.appendChild(statCard(label, value)));
}

function renderItems(items) {
  repeatList.replaceChildren();
  if (!items.length) {
    repeatList.appendChild(note("No remembered items yet."));
    return;
  }
  items.forEach((item) => repeatList.appendChild(renderItem(item)));
}

function renderItem(item) {
  const card = document.createElement("article");
  card.className = "line-card";
  const heading = document.createElement("h3");
  heading.textContent = item.item_name;
  const fields = document.createElement("dl");
  addField(fields, "Purchases", item.occurrence_count);
  addField(fields, "Repeat", item.repeating ? "Purchased more than once" : "Purchased once");
  addField(fields, "First purchase", item.first_purchase_date);
  addField(fields, "Latest purchase", item.latest_purchase_date);
  addField(fields, "Known quantity", item.known_quantity);
  if (item.frequency_status === "calculated") {
    addField(fields, "Average days between purchases", item.average_interval_days);
    addField(fields, "Latest interval in days", item.latest_interval_days);
  } else {
    addField(fields, "Days between purchases", "Not enough purchase dates");
  }
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Show remembered purchases";
  const sources = document.createElement("div");
  sources.hidden = true;
  button.addEventListener("click", () => {
    const open = sources.hidden;
    sources.hidden = !open;
    if (open && !sources.childElementCount) {
      (item.sources || []).forEach((source) => sources.appendChild(renderSource(source)));
    }
    button.textContent = sources.hidden ? "Show remembered purchases" : "Hide remembered purchases";
  });
  card.append(heading, fields, button, sources);
  return card;
}

function renderSource(source) {
  const block = document.createElement("div");
  block.className = "line-card";
  const fields = document.createElement("dl");
  addField(fields, "Confirmed name", source.item_name);
  addField(fields, "Purchase date", source.purchase_date);
  addField(fields, "Merchant", source.merchant);
  addField(fields, "Quantity", source.quantity);
  addField(fields, "Purchase ID", source.purchase_id);
  addField(fields, "Memory ID", source.memory_id);
  const link = document.createElement("a");
  link.href = `/memory#${source.memory_id}`;
  link.textContent = "View remembered purchase";
  block.append(fields, link);
  return block;
}

function renderMerchants(merchants) {
  merchantList.replaceChildren();
  if (!merchants.length) {
    merchantList.appendChild(note("No merchants in purchase history."));
    return;
  }
  merchants.forEach((merchant) => {
    const card = document.createElement("article");
    card.className = "line-card";
    const fields = document.createElement("dl");
    addField(fields, "Merchant", merchant.merchant);
    addField(fields, "Remembered purchases", merchant.purchase_count);
    card.appendChild(fields);
    merchantList.appendChild(card);
  });
}

function renderClassifications(classifications) {
  classificationList.replaceChildren();
  const groups = [
    ["Food or non-food", classifications.food || {}],
    ["Need or want", classifications.need_want || {}],
    ["Consumable or long-term", classifications.durability || {}],
  ];
  groups.forEach(([title, counts]) => {
    Object.keys(counts).forEach((label) => {
      classificationList.appendChild(statCard(`${title}: ${label}`, counts[label]));
    });
  });
}

function statCard(label, value) {
  const card = document.createElement("article");
  const term = document.createElement("span");
  term.textContent = label;
  const amount = document.createElement("strong");
  amount.textContent = value == null || value === "" ? "Unknown" : String(value);
  card.append(term, amount);
  return card;
}

function note(message) {
  const paragraph = document.createElement("p");
  paragraph.className = "hint";
  paragraph.textContent = message;
  return paragraph;
}

function addField(listElement, label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value == null || value === "" ? "Unknown" : String(value);
  listElement.append(term, description);
}

function showMessage(container, message) {
  container.replaceChildren();
  const title = document.createElement("p");
  title.className = "result-title";
  title.textContent = message;
  container.appendChild(title);
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

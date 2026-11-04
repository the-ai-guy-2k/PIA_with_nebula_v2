const statusBox = document.querySelector("#recall-status");
const list = document.querySelector("#recall-list");

const LABELS = {
  exact: "Exact image",
  representative: "Representative image",
  "text-only": "No image",
};

loadRecall();

async function loadRecall() {
  showMessage(statusBox, "Loading food you purchased…");
  const view = new URLSearchParams(window.location.search).get("view");
  const query = view ? `?view=${encodeURIComponent(view)}` : "";
  try {
    const response = await fetch(`/api/visual-recall${query}`);
    const report = await readJson(response);
    if (!response.ok || !report) {
      showMessage(statusBox, report && report.reason ? report.reason : "Food recall could not be loaded.");
      return;
    }
    renderRecall(report);
  } catch (_error) {
    showMessage(statusBox, "Food recall could not be loaded.");
  }
}

function renderRecall(report) {
  statusBox.replaceChildren();
  list.replaceChildren();
  if (!report.items || !report.items.length) {
    showMessage(statusBox, report.reason || "No Walmart food purchases are in purchase history.");
    return;
  }
  report.items.forEach((item) => list.appendChild(renderItem(item)));
}

function renderItem(item) {
  const card = document.createElement("article");
  card.className = "line-card recall-card";
  const heading = document.createElement("h2");
  heading.textContent = item.confirmed_item_name;
  const label = document.createElement("p");
  label.textContent = LABELS[item.display] || "No image";
  card.append(heading, label);
  if (item.image_available && (item.display === "exact" || item.display === "representative")) {
    const image = document.createElement("img");
    image.src = `/api/visual-recall/enrichments/${encodeURIComponent(item.enrichment_id)}/image`;
    image.alt = `${LABELS[item.display]} of ${item.confirmed_item_name}`;
    image.addEventListener("error", () => {
      image.remove();
      label.textContent = "No image";
    });
    card.appendChild(image);
  }
  const fields = document.createElement("dl");
  addField(fields, "Purchase date", item.purchase_date);
  addField(fields, "Merchant", item.merchant);
  addField(fields, "Image source", item.source_reference);
  const link = document.createElement("a");
  link.href = `/memory#${item.memory_id}`;
  link.textContent = "View remembered purchase";
  card.append(fields, link);
  return card;
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

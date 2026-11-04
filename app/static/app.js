const form = document.querySelector("#intake-form");
const fileInput = document.querySelector("#receipt-file");
const submitButton = document.querySelector("#submit-button");
const result = document.querySelector("#result");
const extractForm = document.querySelector("#extract-form");
const evidenceInput = document.querySelector("#evidence-id");
const extractButton = document.querySelector("#extract-button");
const extractionResult = document.querySelector("#extraction-result");

fileInput.addEventListener("change", () => {
  clearResult(result);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const selected = fileInput.files && fileInput.files[0];
  if (!selected) {
    showRejected(result, "Upload rejected", "Choose a receipt image before submitting.");
    return;
  }
  submitReceipt(selected);
});

extractForm.addEventListener("submit", (event) => {
  event.preventDefault();
  extractEvidence(evidenceInput.value);
});

async function submitReceipt(file) {
  submitButton.disabled = true;
  showPending(result, "Preserving receipt…");
  const body = new FormData();
  body.append("file", file, file.name);
  try {
    const response = await fetch("/api/receipts", { method: "POST", body });
    const payload = await readJson(response);
    if (response.ok && payload && payload.status === "accepted") {
      showAccepted(payload);
      return;
    }
    const reason = payload && payload.reason
      ? payload.reason
      : "The upload could not be processed.";
    showRejected(result, "Upload rejected", reason);
  } catch (_error) {
    showRejected(result, "Upload rejected", "The upload could not be processed.");
  } finally {
    submitButton.disabled = false;
  }
}

async function extractEvidence(evidenceId) {
  const id = String(evidenceId || "").trim();
  evidenceInput.value = id;
  if (!id) {
    showRejected(extractionResult, "Extraction failed", "Enter an evidence ID.");
    return;
  }
  extractButton.disabled = true;
  showPending(extractionResult, "Reading preserved receipt…");
  try {
    const response = await fetch(`/api/receipts/${encodeURIComponent(id)}/extraction`, {
      method: "POST",
    });
    const payload = await readJson(response);
    if (payload && payload.extraction_id) {
      showExtraction(payload);
      return;
    }
    const reason = payload && payload.reason
      ? payload.reason
      : "The receipt could not be read.";
    showRejected(extractionResult, "Extraction failed", reason);
  } catch (_error) {
    showRejected(extractionResult, "Extraction failed", "The receipt could not be read.");
  } finally {
    extractButton.disabled = false;
  }
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

function clearResult(container) {
  container.dataset.state = "";
  container.replaceChildren();
}

function showPending(container, message) {
  container.dataset.state = "pending";
  container.replaceChildren();
  const title = document.createElement("p");
  title.className = "result-title";
  title.textContent = message;
  container.appendChild(title);
}

function showRejected(container, titleText, reason) {
  container.dataset.state = "rejected";
  container.replaceChildren();
  const title = document.createElement("p");
  title.className = "result-title";
  title.textContent = titleText;
  const detail = document.createElement("p");
  detail.className = "result-detail";
  detail.textContent = reason;
  container.append(title, detail);
}

function showAccepted(payload) {
  result.dataset.state = "accepted";
  result.replaceChildren();
  const title = document.createElement("p");
  title.className = "result-title";
  title.textContent = "Upload accepted";
  const list = document.createElement("dl");
  addField(list, "Evidence ID", payload.evidence_id);
  addField(list, "Original filename", payload.original_filename);
  addField(list, "MIME type", payload.mime_type);
  addField(list, "File size", formatBytes(payload.byte_size));
  const extract = document.createElement("button");
  extract.type = "button";
  extract.textContent = "Extract this receipt";
  extract.addEventListener("click", () => {
    extractEvidence(payload.evidence_id);
  });
  result.append(title, list, extract);
}

function showExtraction(payload) {
  const status = payload.extraction_status;
  if (status === "failed") {
    showRejected(
      extractionResult,
      "Extraction failed",
      payload.failure_reason || "The receipt could not be read.",
    );
    return;
  }
  extractionResult.dataset.state = status === "extracted" ? "accepted" : "empty";
  extractionResult.replaceChildren();
  const title = document.createElement("p");
  title.className = "result-title";
  title.textContent = extractionTitle(status);
  const list = document.createElement("dl");
  addField(list, "Evidence ID", payload.evidence_id);
  addField(list, "Merchant candidate", payload.merchant_normalized_candidate);
  addField(list, "Merchant raw", payload.merchant_raw);
  addField(list, "Date candidate", payload.purchase_date_candidate);
  addField(list, "Time candidate", payload.purchase_time_candidate);
  addField(list, "Subtotal candidate", payload.subtotal_candidate);
  addField(list, "Tax candidate", payload.tax_candidate);
  addField(list, "Total candidate", payload.total_candidate);
  extractionResult.append(title, list);

  const lines = Array.isArray(payload.lines) ? payload.lines : [];
  if (lines.length) {
    const lineList = document.createElement("div");
    lineList.className = "line-list";
    lines.forEach((line) => {
      lineList.appendChild(renderLine(line));
    });
    extractionResult.appendChild(lineList);
  }

  if (payload.raw_text) {
    const rawHeading = document.createElement("h3");
    rawHeading.textContent = "Raw receipt text";
    const raw = document.createElement("p");
    raw.className = "raw-text";
    raw.textContent = payload.raw_text;
    extractionResult.append(rawHeading, raw);
  }

  if (status === "extracted" && lines.length) {
    extractionResult.appendChild(renderReview(payload));
  }
}

function extractionTitle(status) {
  if (status === "no_text") {
    return "No text detected";
  }
  if (status === "insufficient_data") {
    return "Not enough receipt text";
  }
  return "Unconfirmed extraction";
}

function renderLine(line) {
  const card = document.createElement("article");
  card.className = "line-card";
  const heading = document.createElement("h3");
  heading.textContent = `Item ${line.line_order}`;
  const list = document.createElement("dl");
  addField(list, "Raw text", line.raw_text);
  addField(list, "Normalized candidate", line.normalized_name_candidate);
  addField(list, "Quantity candidate", line.quantity_candidate);
  addField(list, "Unit price candidate", line.unit_price_candidate);
  addField(list, "Line total candidate", line.line_total_candidate);
  card.append(heading, list);
  return card;
}

function addField(list, label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value == null || value === "" ? "Unknown" : String(value);
  list.append(term, description);
}

function formatBytes(byteSize) {
  const size = Number(byteSize);
  if (!Number.isFinite(size)) {
    return "";
  }
  const exact = `${new Intl.NumberFormat("en-US").format(size)} bytes`;
  if (size < 1024) {
    return exact;
  }
  const megabytes = size / (1024 * 1024);
  if (megabytes >= 1) {
    return `${megabytes.toFixed(2)} MB (${exact})`;
  }
  return `${(size / 1024).toFixed(1)} KB (${exact})`;
}

const purchaseLookup = document.querySelector("#purchase-lookup");
const purchaseIdInput = document.querySelector("#purchase-id");
const purchaseLookupResult = document.querySelector("#purchase-lookup-result");

purchaseLookup.addEventListener("submit", (event) => {
  event.preventDefault();
  loadConfirmedPurchase(purchaseIdInput.value, purchaseLookupResult);
});

function renderReview(payload) {
  const form = document.createElement("form");
  form.id = "review-form";
  form.className = "review-form";
  const heading = document.createElement("h3");
  heading.textContent = "Review and confirm";
  const note = document.createElement("p");
  note.className = "hint";
  note.textContent = payload.confirmation_state === "confirmed"
    ? "This extraction is already confirmed. The confirmed purchase is read-only."
    : "Unconfirmed extraction. Review marks fields to check. Confirm purchase saves a separate record and does not change the raw text or the original receipt.";
  form.append(heading, note);
  const confidence = payload.confidence || {};
  form.append(
    reviewField("Merchant", "merchant", payload.merchant_normalized_candidate, confidence.merchant),
    reviewField("Purchase date", "purchase_date", payload.purchase_date_candidate, confidence.purchase_date),
    reviewField("Purchase time", "purchase_time", payload.purchase_time_candidate, confidence.purchase_time),
    reviewField("Subtotal", "subtotal", payload.subtotal_candidate, confidence.subtotal),
    reviewField("Tax", "tax", payload.tax_candidate, confidence.tax),
    reviewField("Total", "total", payload.total_candidate, confidence.total),
  );
  const lineLevels = Array.isArray(confidence.lines) ? confidence.lines : [];
  payload.lines.forEach((line) => {
    const levels = lineLevels.find((item) => item.line_id === line.line_id) || {};
    form.appendChild(renderReviewLine(line, levels));
  });
  const button = document.createElement("button");
  button.id = "confirm-purchase";
  button.type = "submit";
  button.textContent = "Confirm purchase";
  const confirmed = document.createElement("div");
  confirmed.id = "confirmed-result";
  confirmed.className = "result";
  confirmed.setAttribute("role", "status");
  form.append(button, confirmed);
  if (payload.confirmation_state === "confirmed") {
    button.disabled = true;
    form.querySelectorAll("input").forEach((input) => {
      input.disabled = true;
    });
    loadConfirmedPurchase(payload.purchase_id, confirmed);
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitConfirmation(form, payload);
  });
  return form;
}

function renderReviewLine(line, levels) {
  const card = document.createElement("fieldset");
  card.className = "line-card";
  card.dataset.sourceLineId = line.line_id;
  const legend = document.createElement("legend");
  legend.textContent = `Item ${line.line_order}`;
  const rawLabel = document.createElement("p");
  rawLabel.className = "hint";
  rawLabel.textContent = "Raw line";
  const raw = document.createElement("p");
  raw.className = "raw-text";
  raw.textContent = line.raw_text || "";
  card.append(
    legend,
    rawLabel,
    raw,
    reviewField("Item name", "item_name", line.normalized_name_candidate, levels.item_name),
    reviewField("Quantity", "quantity", line.quantity_candidate, levels.quantity),
    reviewField("Unit price", "unit_price", line.unit_price_candidate, levels.unit_price),
    reviewField("Line total", "line_total", line.line_total_candidate, levels.line_total),
  );
  return card;
}

function reviewField(label, name, value, level) {
  const wrap = document.createElement("div");
  wrap.className = "review-field";
  if (level === "low") {
    wrap.classList.add("needs-review");
  } else if (level === "medium") {
    wrap.classList.add("check-field");
  }
  const fieldLabel = document.createElement("label");
  const title = document.createElement("span");
  title.textContent = label;
  if (level === "low" || level === "medium") {
    const badge = document.createElement("span");
    badge.className = `badge badge-${level}`;
    badge.textContent = level === "low" ? "Review" : "Check";
    title.append(" ", badge);
  }
  const input = document.createElement("input");
  input.type = "text";
  input.name = name;
  input.value = value == null ? "" : String(value);
  input.autocomplete = "off";
  input.spellcheck = false;
  fieldLabel.append(title, input);
  wrap.appendChild(fieldLabel);
  return wrap;
}

async function submitConfirmation(form, payload) {
  const button = form.querySelector("#confirm-purchase");
  const confirmed = form.querySelector("#confirmed-result");
  button.disabled = true;
  showPending(confirmed, "Confirming purchase…");
  const body = {
    evidence_id: payload.evidence_id,
    extraction_id: payload.extraction_id,
    merchant: blankToNull(form.querySelector("[name='merchant']").value),
    purchase_date: blankToNull(form.querySelector("[name='purchase_date']").value),
    purchase_time: blankToNull(form.querySelector("[name='purchase_time']").value),
    subtotal: blankToNull(form.querySelector("[name='subtotal']").value),
    tax: blankToNull(form.querySelector("[name='tax']").value),
    total: blankToNull(form.querySelector("[name='total']").value),
    items: Array.from(form.querySelectorAll("fieldset.line-card")).map((card) => ({
      source_line_id: card.dataset.sourceLineId,
      item_name: card.querySelector("[name='item_name']").value.trim(),
      quantity: blankToNull(card.querySelector("[name='quantity']").value),
      unit_price: blankToNull(card.querySelector("[name='unit_price']").value),
      line_total: blankToNull(card.querySelector("[name='line_total']").value),
    })),
  };
  try {
    const response = await fetch("/api/purchases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const result = await readJson(response);
    if (response.status === 201 && result && result.status === "confirmed") {
      const note = form.querySelector(".hint");
      if (note) {
        note.textContent = "Confirmed purchase saved. The extraction above stays unconfirmed candidate data, and this confirmed record is read-only.";
      }
      showConfirmedPurchase(confirmed, result);
      purchaseIdInput.value = result.purchase_id;
      if (result.memory_id) {
        const history = document.createElement("a");
        history.href = `/memory#${result.memory_id}`;
        history.textContent = "View remembered purchase";
        confirmed.appendChild(history);
      }
      form.querySelectorAll("input").forEach((input) => {
        input.disabled = true;
      });
      return;
    }
    const reason = result && result.reason ? result.reason : "The purchase could not be confirmed.";
    showRejected(confirmed, "Confirmation rejected", reason);
    button.disabled = false;
    if (result && result.purchase_id) {
      purchaseIdInput.value = result.purchase_id;
    }
  } catch (_error) {
    showRejected(confirmed, "Confirmation rejected", "The purchase could not be confirmed.");
    button.disabled = false;
  }
}

async function loadConfirmedPurchase(purchaseId, container) {
  const id = String(purchaseId || "").trim();
  if (!id) {
    showRejected(container, "Confirmed purchase", "Enter a purchase ID.");
    return;
  }
  showPending(container, "Loading confirmed purchase…");
  try {
    const response = await fetch(`/api/purchases/${encodeURIComponent(id)}`);
    const result = await readJson(response);
    if (response.ok && result && result.status === "confirmed") {
      showConfirmedPurchase(container, result);
      return;
    }
    showRejected(
      container,
      "Confirmed purchase",
      result && result.reason ? result.reason : "The confirmed purchase was not found.",
    );
  } catch (_error) {
    showRejected(container, "Confirmed purchase", "The confirmed purchase was not found.");
  }
}

function showConfirmedPurchase(container, purchase) {
  container.dataset.state = "accepted";
  container.replaceChildren();
  const title = document.createElement("p");
  title.className = "result-title";
  title.textContent = "Confirmed purchase";
  const list = document.createElement("dl");
  addField(list, "Purchase ID", purchase.purchase_id);
  addField(list, "Evidence ID", purchase.evidence_id);
  addField(list, "Extraction ID", purchase.extraction_id);
  addField(list, "Merchant", purchase.merchant);
  addField(list, "Purchase date", purchase.purchase_date);
  addField(list, "Purchase time", purchase.purchase_time);
  addField(list, "Subtotal", purchase.subtotal);
  addField(list, "Tax", purchase.tax);
  addField(list, "Total", purchase.total);
  addField(list, "Confirmed at", purchase.confirmed_at);
  container.append(title, list);
  const lineList = document.createElement("div");
  lineList.className = "line-list";
  (purchase.items || []).forEach((item) => {
    const card = document.createElement("article");
    card.className = "line-card";
    const heading = document.createElement("h3");
    heading.textContent = `Item ${item.line_order}`;
    const fields = document.createElement("dl");
    addField(fields, "Confirmed name", item.item_name);
    addField(fields, "Raw line", item.raw_line_text);
    addField(fields, "Quantity", item.quantity);
    addField(fields, "Unit price", item.unit_price);
    addField(fields, "Line total", item.line_total);
    addField(fields, "Source line ID", item.source_line_id);
    card.append(heading, fields);
    lineList.appendChild(card);
  });
  container.appendChild(lineList);
}

function blankToNull(value) {
  const text = String(value || "").trim();
  return text ? text : null;
}

window.submitReceipt = submitReceipt;
window.extractEvidence = extractEvidence;
window.loadConfirmedPurchase = loadConfirmedPurchase;

(() => {
  const form = document.getElementById("ask-form");
  const questionInput = document.getElementById("question");
  const counter = document.getElementById("question-count");
  const submitButton = document.getElementById("ask-button");
  const resultRegion = document.getElementById("ask-result");
  const statusRegion = document.getElementById("ask-status");
  const answerPanel = document.getElementById("answer-panel");
  const answerText = document.getElementById("answer-text");
  const answerState = document.getElementById("answer-state");
  const provenance = document.getElementById("answer-provenance");
  const factsList = document.getElementById("supporting-facts");
  const factsEmpty = document.getElementById("facts-empty");
  const starterButtons = document.querySelectorAll(".starter-button");

  const statusLabels = {
    ready: "Ready",
    empty: "No matching purchases",
    unsupported: "Not supported by history",
    insufficient_history: "Not enough history",
    degraded: "Fallback answer",
  };

  function setText(element, value) {
    element.textContent = value == null ? "" : String(value);
  }

  function clearAnswer() {
    setText(answerText, "");
    setText(answerState, "");
    provenance.replaceChildren();
    factsList.replaceChildren();
    factsEmpty.hidden = true;
    answerPanel.hidden = true;
  }

  function showStatus(message, state) {
    resultRegion.hidden = false;
    statusRegion.dataset.state = state;
    setText(statusRegion, message);
  }

  function addProvenance(label, value) {
    if (value === null || value === undefined || String(value).trim() === "") return;
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    setText(term, label);
    setText(detail, value);
    provenance.append(term, detail);
  }

  function renderFacts(facts) {
    const validFacts = Array.isArray(facts) ? facts : [];
    if (validFacts.length === 0) {
      factsEmpty.hidden = false;
      return;
    }

    validFacts.forEach((fact) => {
      const item = document.createElement("li");
      const kind = document.createElement("span");
      const factId = document.createElement("span");
      const text = document.createElement("span");
      kind.className = "fact-kind";
      factId.className = "fact-id";
      text.className = "fact-text";
      setText(kind, fact && fact.kind ? fact.kind : "Supporting fact");
      setText(factId, fact && fact.fact_id ? `Fact ID · ${fact.fact_id}` : "Fact ID unavailable");
      setText(text, fact && fact.text ? fact.text : "Fact text unavailable.");
      item.append(kind, factId, text);
      factsList.append(item);
    });
  }

  function renderResponse(payload) {
    clearAnswer();
    const status = payload.status;
    const answer = typeof payload.answer === "string" ? payload.answer : "";
    const degraded = payload.degraded === true || status === "degraded";
    answerPanel.hidden = false;

    if (status === "empty" || status === "unsupported" || status === "insufficient_history") {
      showStatus(statusLabels[status] || "No supported answer", "empty");
    } else if (degraded) {
      const reason = payload.degraded_reason ? ` ${payload.degraded_reason}` : "";
      showStatus(`AI answering is unavailable or degraded; showing the returned fallback where possible.${reason}`, "pending");
    } else {
      statusRegion.replaceChildren();
      statusRegion.removeAttribute("data-state");
      resultRegion.hidden = false;
    }

    setText(answerState, degraded ? "Fallback answer" : (statusLabels[status] || status || "Answer"));
    setText(answerText, answer || "No answer text was returned.");

    const sourceLabels = {
      ai_grounded: "AI-grounded answer",
      deterministic: "Deterministic answer",
      deterministic_fallback: "Deterministic fallback",
    };
    addProvenance("Answer source", sourceLabels[payload.answer_source] || payload.answer_source || "Not provided");
    addProvenance("Provider", payload.provider || (payload.answer_source === "deterministic_fallback" ? "AI unavailable" : null));
    addProvenance("Model", payload.model);
    addProvenance("Generated", payload.generated_at);
    addProvenance("Grounded facts", payload.grounded_fact_count);
    addProvenance("Context scope", payload.context_scope);
    addProvenance("Query ID", payload.query_id);
    renderFacts(payload.supporting_facts);
  }

  function updateCounter() {
    setText(counter, `${questionInput.value.length} / 500`);
  }

  const initialQuestion = new URLSearchParams(window.location.search).get("question");
  if (initialQuestion) {
    questionInput.value = initialQuestion.slice(0, 500);
    updateCounter();
  }

  questionInput.addEventListener("input", updateCounter);

  starterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      questionInput.value = button.dataset.question || "";
      updateCounter();
      questionInput.focus();
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = questionInput.value.trim();
    if (!question || submitButton.disabled) {
      if (!question) {
        questionInput.setCustomValidity("Enter a question before asking.");
        questionInput.reportValidity();
        questionInput.addEventListener("input", () => questionInput.setCustomValidity(""), { once: true });
      }
      return;
    }

    clearAnswer();
    showStatus("Searching confirmed purchase history…", "pending");
    submitButton.disabled = true;
    submitButton.textContent = "Searching…";
    questionInput.disabled = true;

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question }),
      });
      const payload = await response.json().catch(() => null);

      if (response.status === 400 && payload && payload.status === "rejected") {
        clearAnswer();
        showStatus(payload.reason || "This question was rejected. Please revise it and try again.", "rejected");
        return;
      }

      if (!response.ok || !payload || typeof payload !== "object") {
        throw new Error("The purchase-history service could not return a valid answer. Please try again.");
      }
      renderResponse(payload);
    } catch (error) {
      clearAnswer();
      showStatus(error instanceof Error ? error.message : "The purchase-history service is unavailable. Please try again.", "error");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Ask";
      questionInput.disabled = false;
    }
  });
})();
const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const questionInput = document.getElementById("question-input");
const fileInput = document.getElementById("document-upload");
const uploadButton = document.getElementById("upload-button");

const els = {
  docsCount: document.getElementById("docs-count"),
  revenueTotal: document.getElementById("revenue-total"),
  marginRate: document.getElementById("margin-rate"),
  growthRate: document.getElementById("growth-rate"),
  sourceTotal: document.getElementById("source-total"),
  documentList: document.getElementById("document-list")
};

function addMessage(text, role = "bot") {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;
  wrapper.innerHTML = text;
  chatLog.appendChild(wrapper);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function renderDocuments(list) {
  els.documentList.innerHTML = "";
  list.forEach((doc) => {
    const item = document.createElement("li");
    item.innerHTML = `
      <div>
        <strong>${doc.name}</strong><br />
        <small>${doc.type}</small>
      </div>
      <small>#${doc.id}</small>
    `;
    els.documentList.appendChild(item);
  });
  els.sourceTotal.textContent = `${list.length} files`;
}

async function loadDashboard() {
  const docsResponse = await fetch("/api/documents");
  const docs = await docsResponse.json();
  renderDocuments(docs);
  els.docsCount.textContent = docs.length;

  const metricsResponse = await fetch("/api/metrics");
  const metrics = await metricsResponse.json();
  els.revenueTotal.textContent = `$${metrics.total_revenue_usd_m || 0}M`;
  els.marginRate.textContent = `${metrics.avg_net_margin_pct || 0}%`;
  els.growthRate.textContent = `${metrics.avg_growth_pct || 0}%`;
}

async function submitQuestion(event) {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  addMessage(`<p>${question}</p>`, "user");
  questionInput.value = "";

  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  });

  const payload = await response.json();
  let html = `<p>${payload.answer}</p>`;
  if (payload.citations && payload.citations.length) {
    html += `<ul class="citation-list">${payload.citations.map((citation) => `<li>${citation.source}</li>`).join("")}</ul>`;
  }
  addMessage(html, "bot");

  loadDashboard();
}

async function uploadDocuments() {
  const files = Array.from(fileInput.files || []);
  if (!files.length) return;

  for (const file of files) {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch("/api/upload", { method: "POST", body: formData });
    const payload = await response.json();
    addMessage(`<p>${payload.message}</p>`, "bot");
  }

  fileInput.value = "";
  await loadDashboard();
}

chatForm.addEventListener("submit", submitQuestion);
uploadButton.addEventListener("click", uploadDocuments);

loadDashboard();

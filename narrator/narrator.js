async function api(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Request failed");
  return body;
}

function metadataFormData(form) {
  const data = new FormData(form);
  for (const name of ["genres", "listeningContexts", "contentWarnings", "keywords"]) {
    const values = data.getAll(name).map((value) => String(value).trim()).filter(Boolean);
    data.delete(name);
    data.append(name, JSON.stringify(values));
  }
  return data;
}

async function load() {
  const session = await api("/api/session");
  if (!session.authenticated || session.role !== "narrator") {
    window.location.replace("/");
    return;
  }
  document.querySelector("#username").textContent = session.username;
  const data = await api("/api/narrator/dashboard");
  const assets = await api("/api/narrator/assets");
  const total = Object.values(data.counts).reduce((sum, value) => sum + value, 0);
  document.querySelector("#stats").innerHTML = [
    ["My uploads", total, "Files in your pipeline"],
    ["Published", data.counts.published || 0, "Visible to listeners"],
    ["In review", data.counts["needs-review"] || 0, "Editorial review required"],
    ["Credits", data.credits, "One credit per approved audio"],
  ].map(([label, value, note]) => `<div><strong>${value}</strong><span>${label}</span><small>${note}</small></div>`).join("");
  const profile = data.profile || {};
  const profileForm = document.querySelector("#profile-form");
  profileForm.displayName.value = profile.displayName || session.username;
  profileForm.biography.value = profile.biography || "";
  document.querySelector("#credit-history").innerHTML = data.creditHistory.length
    ? data.creditHistory.map(item => `<article><div><strong>${item.title}</strong><span>v${item.versionNumber || 1} · ${item.awardedAt}</span></div><span>${item.reason}</span></article>`).join("")
    : "<p>No credits awarded yet.</p>";
  const published = document.querySelector("#published");
  const audioUrl = (sourcePath) => `/audio/${encodeURI((sourcePath || "").replaceAll("\\", "/").replace(/^audio\//, ""))}`;
  published.innerHTML = data.published.length
    ? data.published.map(item => `<article><div><strong>${item.title}</strong><span>${item.album || "Uncategorized"} · v${item.versionNumber || 1} · Published ${item.published_at || "pending"}</span><audio controls preload="none" src="${audioUrl(item.sourcePath)}"></audio></div><form class="replacement-form" data-parent="${item.id}"><input name="audio" type="file" accept="audio/*" required><button type="submit">Submit replacement</button></form></article>`).join("")
    : "<p>No published audio yet.</p>";
  document.querySelector("#pipeline").innerHTML = assets.items.length
    ? assets.items.map(item => `<article><div><strong>${item.title}</strong><span>${item.status} · v${item.versionNumber || 1}${item.parentAssetId ? ` · replacement of ${item.parentAssetId}` : ""}</span><audio controls preload="none" src="${audioUrl(item.sourcePath)}"></audio></div><span>${item.reviewRequired ? "Review required" : ""}</span></article>`).join("")
    : "<p>Your pipeline is empty.</p>";
  document.querySelectorAll(".replacement-form").forEach((form) => form.addEventListener("submit", submitReplacement));
}

async function submitReplacement(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  data.append("parentAssetId", form.dataset.parent);
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "Uploading...";
  try {
    const response = await fetch("/api/narrator/upload", { method: "POST", body: data });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Replacement upload failed.");
    button.textContent = "Submitted for review";
    await load();
  } catch (error) {
    button.disabled = false;
    button.textContent = error.message;
  }
}

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#upload-message");
  message.textContent = "Uploading...";
  try {
    const response = await fetch("/api/narrator/upload", { method: "POST", body: metadataFormData(form) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Upload failed.");
    message.textContent = `Uploaded ${result.filename}. Transcription is queued for review.`;
    form.reset();
    await load();
  } catch (error) {
    message.textContent = error.message;
  }
});
document.querySelector("#profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = document.querySelector("#profile-message");
  try {
    await api("/api/narrator/profile", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))});
    message.textContent = "Profile saved.";
  } catch (error) { message.textContent = error.message; }
});

document.querySelector("#logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  window.location.replace("/");
});
load().catch(() => window.location.replace("/"));

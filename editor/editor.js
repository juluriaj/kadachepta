const appView = document.querySelector("#app-view");
let currentQueue = "transcripts";
let assetPollTimer = null;

async function api(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Request failed");
  return body;
}
function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message; toast.classList.add("show");
  clearTimeout(showToast.timer); showToast.timer = setTimeout(() => toast.classList.remove("show"), 2200);
}
function audioUrl(sourcePath) {
  return `/audio/${encodeURI((sourcePath || "").replaceAll("\\", "/").replace(/^audio\//, ""))}`;
}
function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}
async function loadDashboard() {
  const data = await api("/api/dashboard");
  const transcriptTotal = Object.values(data.transcripts).reduce((sum, value) => sum + value, 0);
  const teaserTotal = Object.values(data.teasers).reduce((sum, value) => sum + value, 0);
  document.querySelector("#stats").innerHTML = [
    ["Audio assets", data.assets, "Imported into local catalog"],
    ["Transcripts", transcriptTotal, `${data.transcripts.approved || 0} approved`],
    ["Teaser drafts", teaserTotal, `${data.teasers.approved || 0} approved`],
    ["Needs attention", (data.transcripts["needs-review"] || 0) + (data.teasers["needs-review"] || 0), "Human review required"],
  ].map(([label, value, note]) => `<div class="stat"><strong>${value}</strong><span>${label}</span><small>${note}</small></div>`).join("");
}
async function loadQueue() {
  const data = await api(`/api/queue?queue=${currentQueue}`);
  const queue = document.querySelector("#queue");
  if (!data.items.length) { queue.innerHTML = `<div class="queue-card"><div><h3>Nothing here yet</h3><p>Your ${currentQueue} queue is clear.</p></div></div>`; return; }
  queue.innerHTML = data.items.map(item => {
    const preview = currentQueue === "transcripts"
      ? (item.text || "").slice(0, 420)
      : currentQueue === "teasers"
        ? (item.longText || item.shortText || "No teaser text yet.")
        : `Narrator: ${item.narrator} · Submitted ${item.submittedAt || "unknown"}`;
    const submissionActions = currentQueue === "narrator-submissions"
      ? `<button class="approve" data-publish="${item.assetId}">Publish</button><button class="reject" data-reject="${item.assetId}">Reject</button>`
      : `${item.status !== "approved" ? `<button class="approve" data-id="${item.id}" data-decision="approved">Approve</button>` : ""}
         ${item.status !== "rejected" ? `<button class="reject" data-id="${item.id}" data-decision="rejected">Reject</button>` : ""}`;
    return `<article class="queue-card">
      <div><h3>${currentQueue === "narrator-submissions" ? `<button class="asset-title" data-detail="${item.assetId}" type="button">${item.title}</button>` : item.title}</h3><div class="meta">${item.album || "Uncategorized"} · ${item.status} ${item.version ? `· v${item.version}` : ""}</div>
      <p class="transcript-preview">${preview || "No content available."}</p></div>
      <div class="queue-side"><span class="badge ${item.status}">${item.status}</span><div class="actions">
      ${submissionActions}
      </div></div>
    </article>`;
  }).join("");
  queue.querySelectorAll("[data-id]").forEach(button => button.addEventListener("click", () => review(button.dataset.id, button.dataset.decision)));
  queue.querySelectorAll("[data-publish]").forEach(button => button.addEventListener("click", () => publish(button.dataset.publish)));
  queue.querySelectorAll("[data-reject]").forEach(button => button.addEventListener("click", () => rejectSubmission(button.dataset.reject)));
  queue.querySelectorAll("[data-detail]").forEach(button => button.addEventListener("click", () => loadAssetDetail(button.dataset.detail, true)));
}
function jobLabel(job) {
  if (!job) return "Not started";
  if (job.status === "running") return "Running";
  if (job.status === "queued") return "Queued";
  if (job.status === "needs-review") return "Finished · needs review";
  if (job.status === "completed") return "Finished";
  if (job.status === "failed") return "Failed";
  return job.status;
}
function jobBadgeClass(job) {
  if (!job) return "blocked";
  if (job.status === "failed") return "rejected";
  if (job.status === "running" || job.status === "queued") return "needs-review";
  return job.status;
}
function contentActions(type, item) {
  if (!item) return "";
  const label = type === "transcript" ? "transcript" : "teaser";
  const text = escapeHtml(type === "transcript" ? (item.text || "") : (item.longText || item.shortText || ""));
  return `<div class="content-actions"><textarea class="content-editor" data-edit-content="${label}" data-content-id="${item.id}" rows="6">${text}</textarea>
    <div class="edit-actions"><button class="secondary-action" data-save-content="${label}" data-content-id="${item.id}">Save edits</button></div>
    <textarea class="review-notes" data-review-notes="${label}" rows="2" placeholder="Optional approval or rejection comments"></textarea>
    <div class="review-buttons">
    ${item.status !== "approved" ? `<button class="approve" data-content-review="${label}" data-content-id="${item.id}" data-decision="approved">Approve ${label}</button>` : ""}
    ${item.status !== "rejected" ? `<button class="reject" data-content-review="${label}" data-content-id="${item.id}" data-decision="rejected">Reject ${label}</button>` : ""}
    </div>
  </div>`;
}

async function saveMetadata(assetId, reviewStatus) {
  const root = document.querySelector(".metadata-review");
  const value = (name) => root.querySelector(`[name="${name}"]`)?.value.trim() || "";
  const list = (name) => value(name).split(",").map((item) => item.trim()).filter(Boolean);
  try {
    await api("/api/narrator/metadata-review", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
      audioAssetId: assetId, title: value("metadataTitle"), genres: list("metadataGenres"),
      album: value("metadataAlbum"), collection: value("metadataCollection"),
      episodeNumber: value("metadataEpisodeNumber"), language: value("metadataLanguage"),
      audienceAgeRange: value("metadataAudienceAgeRange"), mood: value("metadataMood"),
      listeningContexts: list("metadataListeningContexts"), contentWarnings: list("metadataContentWarnings"),
      sourceAdaptation: value("metadataSourceAdaptation"), keywords: list("metadataKeywords"),
      moralTakeaway: value("metadataMoralTakeaway"), metadataReviewStatus: reviewStatus,
    })});
    showToast(reviewStatus === "approved" ? "Metadata approved" : "Metadata saved");
    await loadAssetDetail(assetId, true);
  } catch (error) { showToast(error.message); }
}

async function loadAssetDetail(assetId, announceCompletion = false, focusReviewId = null) {
  const data = await api(`/api/narrator/asset?id=${encodeURIComponent(assetId)}`);
  const asset = data.asset;
  const transcript = data.transcript;
  const teaser = data.teaser;
  const transcriptionJob = data.jobs.find((job) => job.jobType === "transcription");
  const teaserJob = data.jobs.find((job) => job.jobType === "teaser");
  const activeJob = data.jobs.find((job) => job.status === "running" || job.status === "queued");
  const transcriptionAction = !transcript && transcriptionJob?.status !== "running"
    ? `<button class="approve" data-process="transcription">Start transcription</button>` : "";
  const teaserAction = transcript?.status === "approved" && !teaser && teaserJob?.status !== "running"
    ? `<button class="approve" data-process="teaser">Generate teaser</button>` : "";
  const transcriptReview = transcript
    ? `<section class="content-review"><h3>Transcript review</h3><span class="badge ${transcript.status}">${transcript.status}</span><p>${escapeHtml(transcript.text || "Transcript text is not available.")}</p>${contentActions("transcript", transcript)}</section>` : "";
  const teaserReview = teaser
    ? `<section class="content-review"><h3>Teaser review</h3><span class="badge ${teaser.status}">${teaser.status}</span><p>${escapeHtml(teaser.longText || teaser.shortText || "Teaser text is not available.")}</p>${contentActions("teaser", teaser)}</section>` : "";
  const metadata = asset.metadata || {};
  const missingMetadata = [
    ["title", "Story title"], ["genres", "Genre"], ["language", "Language"],
    ["audienceAgeRange", "Audience / age range"], ["moralTakeaway", "Moral or takeaway"],
    ["sourceAdaptation", "Source / adaptation"],
  ].filter(([key]) => !metadata[key] || (Array.isArray(metadata[key]) && !metadata[key].length)).map(([, label]) => label);
  const rights = data.rights.status === "not-configured" ? {} : data.rights;
  document.querySelector("#asset-title").textContent = asset.title;
  document.querySelector("#delete-notes").value = "";
  document.querySelector("#asset-detail").innerHTML = `
    <div class="asset-summary"><span><b>Status</b>${asset.status}</span><span><b>Narrator</b>${asset.narratorUsername}</span><span><b>Version</b>v${asset.versionNumber}</span><span><b>Duration</b>${asset.duration || 0}s</span></div>
    <audio controls preload="metadata" src="${audioUrl(asset.sourcePath)}"></audio>
    <section class="metadata-review">
      <h3>Narrator metadata</h3>
      <p class="${missingMetadata.length ? "job-error" : "metadata-ready"}">${missingMetadata.length ? `Missing before publishing: ${missingMetadata.join(", ")}` : "Required metadata is present."}</p>
      <span class="badge ${asset.metadataReviewStatus === "approved" ? "approved" : "needs-review"}">Metadata: ${asset.metadataReviewStatus || "not-reviewed"}</span>
      <div class="metadata-editor">
        <label>Title<input name="metadataTitle" value="${escapeHtml(metadata.title || "")}"></label>
        <label>Genres<input name="metadataGenres" value="${escapeHtml((metadata.genres || []).join(", "))}" placeholder="Fantasy, Folklore"></label>
        <label>Album<input name="metadataAlbum" value="${escapeHtml(metadata.album || "")}"></label>
        <label>Collection<input name="metadataCollection" value="${escapeHtml(metadata.collection || "")}"></label>
        <label>Episode/chapter<input name="metadataEpisodeNumber" value="${escapeHtml(metadata.episodeNumber || "")}"></label>
        <label>Language<input name="metadataLanguage" value="${escapeHtml(metadata.language || "te-IN")}"></label>
        <label>Audience / age range<input name="metadataAudienceAgeRange" value="${escapeHtml(metadata.audienceAgeRange || "")}"></label>
        <label>Mood<input name="metadataMood" value="${escapeHtml(metadata.mood || "")}"></label>
        <label>Listening contexts<input name="metadataListeningContexts" value="${escapeHtml((metadata.listeningContexts || []).join(", "))}"></label>
        <label>Content warnings<input name="metadataContentWarnings" value="${escapeHtml((metadata.contentWarnings || []).join(", "))}"></label>
        <label>Source / adaptation<input name="metadataSourceAdaptation" value="${escapeHtml(metadata.sourceAdaptation || "")}"></label>
        <label>Keywords<input name="metadataKeywords" value="${escapeHtml((metadata.keywords || []).join(", "))}"></label>
        <label class="wide">Moral / takeaway<textarea name="metadataMoralTakeaway" rows="2">${escapeHtml(metadata.moralTakeaway || "")}</textarea></label>
      </div>
      <div class="review-buttons">
        <button class="secondary-action" data-save-metadata="${asset.id}">Save metadata</button>
        <button class="approve" data-review-metadata="${asset.id}" data-review-status="approved">Approve metadata</button>
        <button class="reject" data-review-metadata="${asset.id}" data-review-status="needs-changes">Request changes</button>
      </div>
    </section>
    <div class="readiness">
      <div><b>Transcript</b><span class="badge ${transcript?.status || "blocked"}">${transcript?.status || "missing"}</span></div>
      <div><b>Teaser</b><span class="badge ${teaser?.status || "blocked"}">${teaser?.status || "missing"}</span></div>
      <div><b>Rights</b><span class="badge ${data.rights.status === "approved" ? "approved" : "blocked"}">${data.rights.status}</span></div>
    </div>
    ${transcriptReview}
    ${teaserReview}
    <section class="rights-review">
      <h3>Rights checklist</h3>
      <div class="rights-grid">
        <input name="rightsHolder" placeholder="Rights holder" value="${rights.rightsHolder || ""}">
        <input name="territory" placeholder="Territory, e.g. India" value="${rights.territory || ""}">
        <input name="licenseStart" type="date" value="${rights.licenseStart || ""}">
        <input name="licenseEnd" type="date" value="${rights.licenseEnd || ""}">
        <input name="allowedUses" placeholder="Allowed uses, e.g. streaming" value="${rights.allowedUses || ""}">
        <input name="evidenceReference" placeholder="Evidence or contract reference" value="${rights.evidenceReference || ""}">
      </div>
      <div class="rights-checks">
        ${["recordingRights:Recording","performanceRights:Narrator performance","adaptationRights:Adaptation or translation","artworkRights:Artwork","musicRights:Music and effects"].map(([key,label]) => `<label><input type="checkbox" data-rights="${key}" ${rights[key] ? "checked" : ""}> ${label}</label>`).join("")}
      </div>
      <textarea data-rights-notes rows="2" placeholder="Optional rights review comments">${rights.reviewNotes || ""}</textarea>
      <div class="review-buttons"><button class="approve" data-save-rights="${asset.id}" data-rights-status="approved">Save and approve rights</button><button class="reject" data-save-rights="${asset.id}" data-rights-status="needs-review">Save as needs review</button></div>
    </section>
    <div class="job-status">
      <b>Processing status</b>
      <div><span>Transcription</span><span class="badge ${jobBadgeClass(transcriptionJob)}">${jobLabel(transcriptionJob)}</span></div>
      <div><span>Teaser generation</span><span class="badge ${jobBadgeClass(teaserJob)}">${jobLabel(teaserJob)}</span></div>
      ${transcriptionJob?.status === "failed" && transcriptionJob.error ? `<p class="job-error">Transcription error: ${transcriptionJob.error}</p>` : ""}
      ${teaserJob?.status === "failed" && teaserJob.error ? `<p class="job-error">Teaser error: ${teaserJob.error}</p>` : ""}
    </div>
    <p class="asset-note">${data.rights.message}</p>
    <div class="actions">${transcriptionAction}${teaserAction}
      <button class="approve" data-modal-publish="${asset.id}">Publish</button>
      <button class="reject" data-modal-reject="${asset.id}">Reject</button>
      <button class="delete-action" data-modal-delete="${asset.id}">Delete submission</button>
    </div>`;
  document.querySelector("#asset-modal").hidden = false;
  document.querySelector("[data-modal-publish]").addEventListener("click", async () => {
    await publish(asset.id, {transcript: transcript?.status, teaser: teaser?.status, rights: data.rights.status});
    closeAssetDetail();
  });
  document.querySelector("[data-modal-reject]").addEventListener("click", async () => { await rejectSubmission(asset.id); closeAssetDetail(); });
  document.querySelector("[data-save-metadata]").addEventListener("click", () => saveMetadata(asset.id, "not-reviewed"));
  document.querySelectorAll("[data-review-metadata]").forEach((button) => button.addEventListener("click", () => saveMetadata(asset.id, button.dataset.reviewStatus)));
  document.querySelector("[data-modal-delete]").addEventListener("click", async () => {
    const notes = document.querySelector("[data-delete-notes]")?.value.trim() || "";
    await deleteSubmission(asset.id, notes);
  });
  document.querySelectorAll("[data-save-rights]").forEach((button) => button.addEventListener("click", async () => {
    const root = button.closest(".rights-review");
    const value = (name) => root.querySelector(`[name="${name}"]`)?.value.trim() || "";
    const checks = {};
    root.querySelectorAll("[data-rights]").forEach((input) => { checks[input.dataset.rights] = input.checked; });
    button.disabled = true;
    try {
      await api("/api/narrator/rights", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
        audioAssetId: asset.id, status: button.dataset.rightsStatus, rightsHolder: value("rightsHolder"),
        territory: value("territory"), licenseStart: value("licenseStart"), licenseEnd: value("licenseEnd"),
        allowedUses: value("allowedUses"), evidenceReference: value("evidenceReference"),
        reviewNotes: root.querySelector("[data-rights-notes]")?.value.trim() || "", ...checks,
      })});
      showToast("Rights checklist saved");
      await loadAssetDetail(asset.id, true);
    } catch (error) { button.disabled = false; showToast(error.message); }
  }));
  document.querySelectorAll("[data-save-content]").forEach((button) => button.addEventListener("click", async () => {
    const type = button.dataset.saveContent;
    const editor = document.querySelector(`[data-edit-content="${type}"][data-content-id="${button.dataset.contentId}"]`);
    button.disabled = true;
    try {
      await api("/api/narrator/content-edit", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({type, id: button.dataset.contentId, text: editor.value}),
      });
      showToast(`${type[0].toUpperCase()}${type.slice(1)} saved and sent for re-review`);
      await loadAssetDetail(asset.id, true, button.dataset.contentId);
      await loadDashboard();
    } catch (error) {
      button.disabled = false;
      showToast(error.message);
    }

  }));
  document.querySelectorAll("[data-process]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Starting...";
    try {
      await api("/api/narrator/process", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({assetId: asset.id, action: button.dataset.process}),
      });
      showToast(`${button.dataset.process === "teaser" ? "Teaser generation" : "Transcription"} started`);
      await loadAssetDetail(asset.id, true);
    } catch (error) {
      button.disabled = false;
      button.textContent = error.message;
    }
  }));
  document.querySelectorAll("[data-content-review]").forEach((button) => button.addEventListener("click", async () => {
    const type = button.dataset.contentReview;
    const decision = button.dataset.decision;
    const notes = document.querySelector(`[data-review-notes="${type}"]`)?.value.trim() || "";
    button.disabled = true;
    try {
      await api(`/api/${type}/review`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: button.dataset.contentId, decision, notes}),
      });
      showToast(`${type[0].toUpperCase()}${type.slice(1)} ${decision}`);
      await loadAssetDetail(asset.id, true, button.dataset.contentId);
      await loadDashboard();
    } catch (error) {
      button.disabled = false;
      showToast(error.message);
    }
  }));
  if (focusReviewId) {
    const updatedSection = document.querySelector(`[data-content-id="${focusReviewId}"]`)?.closest(".content-review");
    updatedSection?.scrollIntoView({block: "nearest"});
  }
  if (assetPollTimer) {
    clearTimeout(assetPollTimer);
    assetPollTimer = null;
  }
  if (activeJob) {
    assetPollTimer = setTimeout(async () => {
      try {
        await loadAssetDetail(asset.id, announceCompletion);
      } catch (error) {
        showToast(`Could not refresh processing status: ${error.message}`);
      }
    }, 3000);
  } else if (announceCompletion && (
    transcriptionJob?.status === "needs-review" ||
    teaserJob?.status === "completed" ||
    transcriptionJob?.status === "failed" ||
    teaserJob?.status === "failed"
  )) {
    const failed = transcriptionJob?.status === "failed" || teaserJob?.status === "failed";
    showToast(failed ? "Processing failed. See the job status for details." : "Processing finished. Review the updated content.");
    await loadDashboard();
    await loadQueue();
  }
}
function closeAssetDetail() {
  document.querySelector("#asset-modal").hidden = true;
  if (assetPollTimer) {
    clearTimeout(assetPollTimer);
    assetPollTimer = null;
  }
}
async function review(id, decision) {
  const notes = window.prompt(`Notes for ${decision} (optional):`, "") ?? "";
  await api(`/api/${currentQueue === "transcripts" ? "transcript" : "teaser"}/review`, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({id, decision, notes})
  });
  showToast(`${currentQueue === "transcripts" ? "Transcript" : "Teaser"} ${decision}`);
  await loadDashboard(); await loadQueue();
}
async function publish(audioAssetId, readiness = {}) {
  const ready = readiness.transcript === "approved" && readiness.teaser === "approved" && readiness.rights === "approved";
  const message = ready
    ? "Publish this narrator audio? It will become available to listeners."
    : "This audio is not ready to publish yet. Approved transcript, teaser, and rights are required. Continue?";
  if (!window.confirm(message)) return;
  try {
    await api("/api/content/publish", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({audioAssetId})
    });
    showToast("Audio published and narrator credit awarded");
    await loadDashboard(); await loadQueue();
  } catch (error) {
    showToast(error.message);
  }
}
async function rejectSubmission(audioAssetId) {
  const notes = window.prompt("Reason for rejection (optional):", "") ?? "";
  await api("/api/narrator/review", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({audioAssetId, decision: "rejected", notes})
  });
  showToast("Narrator submission rejected");
  await loadDashboard(); await loadQueue();
}
async function deleteSubmission(audioAssetId, notes) {
  if (!window.confirm("Delete this narrator submission and its local audio file? This cannot be undone.")) return;
  try {
    await api("/api/narrator/delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({audioAssetId, notes}),
    });
    showToast("Narrator submission deleted");
    closeAssetDetail();
    await loadDashboard();
    await loadQueue();
  } catch (error) {
    showToast(error.message);
  }
}
async function enter() {
  const session = await api("/api/session");
  if (!session.authenticated) {
    window.location.replace("/");
    return;
  }
  if (session.role !== "editor" && session.role !== "admin") {
    window.location.replace("/");
    return;
  }
  appView.hidden = false; document.querySelector("#username").textContent = session.username; await loadDashboard(); await loadQueue();
}
document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", async () => {
  document.querySelector(".tab.active").classList.remove("active"); tab.classList.add("active"); currentQueue = tab.dataset.queue; await loadQueue();
}));
document.querySelector("#refresh").addEventListener("click", async () => { await loadDashboard(); await loadQueue(); showToast("Workspace refreshed"); });
document.querySelector("#logout").addEventListener("click", async () => { await api("/api/logout", {method:"POST"}); window.location.reload(); });
document.querySelector("#asset-close").addEventListener("click", closeAssetDetail);
document.querySelector("#asset-modal").addEventListener("click", (event) => { if (event.target.id === "asset-modal") closeAssetDetail(); });
enter().catch(() => { window.location.replace("/"); });

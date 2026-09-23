const appView = document.querySelector("#app-view");
let currentQueue = "transcripts";
let assetPollTimer = null;
let watchingJobsFor = null;

const REQUIRED_PROCESSING_ACTIONS = ["transcription", "teaser", "artwork"];

async function api(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    // Keep enough detail to tell a bad request from a stale or different server process.
    const server = response.headers.get("X-KathaChepta-Server") || "server version unknown (restart it)";
    const error = new Error(body.error || `Request failed (HTTP ${response.status})`);
    error.diagnostics = `${options?.method || "GET"} ${url} → HTTP ${response.status} · ${server}`
      + (body.received ? ` · sent ${JSON.stringify(body.received)}` : "");
    console.error("[KathaChepta]", error.message, error.diagnostics, body);
    throw error;
  }
  return body;
}
async function checkServerHealth() {
  const pill = document.querySelector(".status-pill");
  let health = null;
  try {
    const response = await fetch("/api/health");
    if (response.ok) health = await response.json();
  } catch (error) { /* reported below */ }
  const missing = REQUIRED_PROCESSING_ACTIONS.filter((action) => !health?.processingActions?.includes(action));
  if (!health || missing.length) {
    const banner = document.createElement("div");
    banner.className = "server-warning";
    banner.textContent = health
      ? `The editor server (pid ${health.pid}) is missing: ${missing.join(", ")}. Stop every running server and start it again with npm start.`
      : "The editor server is running old code (no /api/health). Stop every running server on port 4173 (netstat -ano | findstr :4173) and start it again with npm start.";
    document.querySelector(".shell").prepend(banner);
  }
  if (pill && health) pill.title = `Server pid ${health.pid} · build ${health.build} · started ${health.startedAt} · Python ${health.python}`;
}
function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message; toast.classList.add("show");
  clearTimeout(showToast.timer); showToast.timer = setTimeout(() => toast.classList.remove("show"), 2200);
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
    ["Audio processed", `${data.media?.ready || 0}/${data.assets}`, `${data.jobs?.queued || 0} queued · ${data.jobs?.leased || 0} running · ${data.media?.failed || 0} failed`],
  ].map(([label, value, note]) => `<div class="stat"><strong>${value}</strong><span>${label}</span><small>${note}</small></div>`).join("");
}
async function loadQueue() {
  const search = document.querySelector("#queue-search")?.value.trim() || "";
  const data = await api(`/api/queue?queue=${currentQueue}${search ? `&q=${encodeURIComponent(search)}` : ""}`);
  const queue = document.querySelector("#queue");
  if (!data.items.length) { queue.innerHTML = `<div class="queue-card"><div><h3>Nothing here yet</h3><p>Your ${currentQueue} queue is clear.</p></div></div>`; return; }
  queue.innerHTML = data.items.map(item => {
    const preview = currentQueue === "transcripts"
      ? (item.text || "").slice(0, 420)
      : currentQueue === "teasers"
        ? (item.longText || item.shortText || "No teaser text yet.")
        : currentQueue === "catalog"
          ? [(item.metadata?.genres || []).join(", "), item.duration ? `${Math.round(item.duration / 60)} min` : "", item.mediaStatus === "ready" ? `audio ${item.qc?.verdict || "processed"}` : `audio ${item.mediaStatus}`].filter(Boolean).join(" · ")
        : currentQueue === "published"
          ? (item.metadata?.moralTakeaway ? `Moral: ${item.metadata.moralTakeaway}` : (item.metadata?.genres || []).join(", ") || "Published story")
          : `Narrator: ${item.narrator} · Submitted ${item.submittedAt || "unknown"}`;
    const submissionActions = currentQueue === "narrator-submissions"
      ? `<button class="approve" data-publish="${item.assetId}">Publish</button><button class="reject" data-reject="${item.assetId}">Reject</button>`
      : currentQueue === "published" || currentQueue === "catalog"
        ? `<button class="secondary-action" data-detail="${item.assetId}">${currentQueue === "catalog" ? "Review" : "Edit metadata"}</button>`
        : `${item.status !== "approved" ? `<button class="approve" data-id="${item.id}" data-decision="approved">Approve</button>` : ""}
           ${item.status !== "rejected" ? `<button class="reject" data-id="${item.id}" data-decision="rejected">Reject</button>` : ""}`;
    const isDetail = ["narrator-submissions", "published", "catalog"].includes(currentQueue);
    return `<article class="queue-card">
      <div><h3>${isDetail ? `<button class="asset-title" data-detail="${item.assetId}" type="button">${escapeHtml(item.title)}</button>` : escapeHtml(item.title)}</h3><div class="meta">${escapeHtml(item.album || "Uncategorized")} · ${item.status} ${item.versionNumber ? `· v${item.versionNumber}` : (item.version ? `· v${item.version}` : "")} ${item.publishedAt ? `· Published ${item.publishedAt.slice(0, 10)}` : ""}</div>
      <p class="transcript-preview">${escapeHtml(preview || "No content available.")}</p></div>
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
function qcPanel(asset) {
  const qc = asset.qc || {};
  const status = asset.mediaStatus === "ready"
    ? `<span class="badge ${qc.verdict === "fail" ? "rejected" : qc.verdict === "warn" ? "needs-review" : "approved"}">Audio QC: ${escapeHtml(qc.verdict || "processed")}</span>`
    : `<span class="badge ${asset.mediaStatus === "failed" ? "rejected" : "needs-review"}">Audio ${escapeHtml(asset.mediaStatus || "pending")}</span>`;
  const numbers = qc.integratedLufs != null
    ? `<small>Source loudness ${qc.integratedLufs.toFixed(1)} LUFS · peak ${qc.truePeakDb?.toFixed(1)} dBTP · noise floor ${qc.noiseFloorDb?.toFixed?.(0) ?? "?"} dB · silence ${Math.round((qc.silenceRatio || 0) * 100)}% · normalised to −16 LUFS</small>` : "";
  const checks = (qc.checks || []).map((check) => `<li class="${check.level}">${escapeHtml(check.message)}${check.tip ? ` <em>${escapeHtml(check.tip)}</em>` : ""}</li>`).join("");
  return `<div class="qc-panel">${status} <button class="secondary-action" data-process="media">Reprocess audio</button>${numbers}${checks ? `<ul>${checks}</ul>` : ""}</div>`;
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
    showToast(reviewStatus === "approved" ? "Metadata approved and updated" : "Metadata saved");
    await loadAssetDetail(assetId, true);
    if (currentQueue === "published" || currentQueue === "narrator-submissions") {
      await loadQueue();
    }
  } catch (error) { showToast(error.message); }
}

async function loadAssetDetail(assetId, announceCompletion = false, focusReviewId = null) {
  const data = await api(`/api/narrator/asset?id=${encodeURIComponent(assetId)}`);
  const asset = data.asset;
  const isPublished = asset.status === "published";
  const eyebrowEl = document.querySelector("#asset-modal-eyebrow");
  if (eyebrowEl) eyebrowEl.textContent = isPublished ? "Published audio detail" : "Narrator submission detail";
  const transcript = data.transcript;
  const teaser = data.teaser;
  const transcriptionJob = data.jobs.find((job) => job.jobType === "transcription");
  const teaserJob = data.jobs.find((job) => job.jobType === "teaser");
  const artworkJob = data.jobs.find((job) => job.jobType === "artwork");
  const mediaJob = data.jobs.find((job) => job.jobType === "media");
  const artworkRunning = artworkJob?.status === "running" || artworkJob?.status === "queued";
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
  const deleteNotes = document.querySelector("#delete-notes");
  if (deleteNotes) {
    deleteNotes.value = "";
    deleteNotes.hidden = isPublished;
  }
  const bottomActions = isPublished
    ? `<span class="badge published">Published</span>`
    : `${transcriptionAction}${teaserAction}
       <button class="approve" data-modal-publish="${asset.id}">Publish</button>
       <button class="reject" data-modal-reject="${asset.id}">Reject</button>
       ${asset.isSubmission ? `<button class="delete-action" data-modal-delete="${asset.id}">Delete submission</button>` : ""}`;

  document.querySelector("#asset-detail").innerHTML = `
    <div class="asset-summary"><span><b>Status</b>${asset.status}</span><span><b>Narrator</b>${escapeHtml(asset.narratorUsername)}</span><span><b>Version</b>v${asset.versionNumber}</span><span><b>Duration</b>${asset.duration || 0}s</span></div>
    <audio controls preload="metadata" src="${escapeHtml(asset.audioUrl || "")}"></audio>${qcPanel(asset)}
    <section class="artwork-review">
      <div class="artwork-frame">${asset.artworkUrl
        ? `<img src="${escapeHtml(asset.artworkUrl)}" alt="Cover artwork for ${escapeHtml(asset.title)}">`
        : `<span>${artworkRunning ? "Painting cover…" : "No artwork yet"}</span>`}</div>
      <div>
        <h3>Cover artwork</h3>
        <p class="asset-note">AI-generated from the title, genres, mood and moral. Save metadata first for a better result, and confirm artwork rights before publishing.</p>
        ${artworkJob?.status === "failed" && artworkJob.error ? `<p class="job-error">Artwork error: ${escapeHtml(artworkJob.error)}</p>` : ""}
        ${artworkRunning
          ? `<span class="badge needs-review">Generating…</span>`
          : `<button class="secondary-action" data-process="artwork">${asset.artworkUrl ? "Regenerate artwork" : "Generate artwork"}</button>`}
      </div>
    </section>
    <section class="metadata-review">
      <h3>${isPublished ? "Published audio metadata" : "Narrator metadata"}</h3>
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
        <button class="secondary-action" data-save-metadata="${asset.id}">${isPublished ? "Update metadata" : "Save metadata"}</button>
        <button class="approve" data-review-metadata="${asset.id}" data-review-status="approved">${isPublished ? "Approve & save" : "Approve metadata"}</button>
        ${!isPublished ? `<button class="reject" data-review-metadata="${asset.id}" data-review-status="needs-changes">Request changes</button>` : ""}
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
      ${rights.sourceType === "kathachepta-owned" && data.rights.status === "approved"
        ? `<p class="metadata-ready">✓ KathaChepta owns this story${rights.attestedBy ? ` (confirmed by ${escapeHtml(rights.attestedBy)}${rights.attestedAt ? ` on ${escapeHtml(rights.attestedAt.slice(0, 10))}` : ""})` : ""}. All rights granted worldwide.</p>`
        : `<div class="owned-shortcut"><button class="approve" data-rights-owned="${asset.id}" type="button">KathaChepta owns this story</button><small>Grants every right, worldwide, with no expiry, and records you as the person who confirmed it. Use the checklist below for anything licensed from someone else.</small></div>`}
      <div class="rights-grid">
        <input name="rightsHolder" placeholder="Rights holder" value="${escapeHtml(rights.rightsHolder || "")}">
        <input name="territory" placeholder="Territory, e.g. India" value="${escapeHtml(rights.territory || "")}">
        <input name="licenseStart" type="date" value="${escapeHtml(rights.licenseStart || "")}">
        <input name="licenseEnd" type="date" value="${escapeHtml(rights.licenseEnd || "")}">
        <input name="allowedUses" placeholder="Allowed uses, e.g. streaming" value="${escapeHtml(rights.allowedUses || "")}">
        <input name="evidenceReference" placeholder="Evidence or contract reference" value="${escapeHtml(rights.evidenceReference || "")}">
      </div>
      <div class="rights-checks">
        ${["recordingRights:Recording","performanceRights:Narrator performance","adaptationRights:Adaptation or translation","artworkRights:Artwork","musicRights:Music and effects"].map((entry) => entry.split(":")).map(([key, label]) => `<label><input type="checkbox" data-rights="${key}" ${rights[key] ? "checked" : ""}> ${label}</label>`).join("")}
      </div>
      <textarea data-rights-notes rows="2" placeholder="Optional rights review comments">${escapeHtml(rights.reviewNotes || "")}</textarea>
      <div class="review-buttons"><button class="approve" data-save-rights="${asset.id}" data-rights-status="approved">Save and approve rights</button><button class="reject" data-save-rights="${asset.id}" data-rights-status="needs-review">Save as needs review</button></div>
    </section>
    <div class="job-status">
      <b>Processing status</b>
      <div><span>Transcription</span><span class="badge ${jobBadgeClass(transcriptionJob)}">${jobLabel(transcriptionJob)}</span></div>
      <div><span>Teaser generation</span><span class="badge ${jobBadgeClass(teaserJob)}">${jobLabel(teaserJob)}</span></div>
      <div><span>Artwork</span><span class="badge ${jobBadgeClass(artworkJob)}">${jobLabel(artworkJob)}</span></div>
      <div><span>Audio processing</span><span class="badge ${jobBadgeClass(mediaJob)}">${jobLabel(mediaJob)}</span></div>
      ${mediaJob?.status === "failed" && mediaJob.error ? `<p class="job-error">Audio processing error: ${escapeHtml(mediaJob.error)}${mediaJob.logTail ? `<code>${escapeHtml(mediaJob.logTail.slice(-600))}</code>` : ""}</p>` : ""}
      ${transcriptionJob?.status === "failed" && transcriptionJob.error ? `<p class="job-error">Transcription error: ${escapeHtml(transcriptionJob.error)}</p>` : ""}
      ${teaserJob?.status === "failed" && teaserJob.error ? `<p class="job-error">Teaser error: ${escapeHtml(teaserJob.error)}</p>` : ""}
    </div>
    <p class="asset-note">${escapeHtml(data.rights.message || "")}</p>
    <div class="actions">${bottomActions}</div>`;
  document.querySelector("#asset-modal").hidden = false;
  const modalPublish = document.querySelector("[data-modal-publish]");
  if (modalPublish) {
    modalPublish.addEventListener("click", async () => {
      await publish(asset.id, {transcript: transcript?.status, teaser: teaser?.status, rights: data.rights.status});
      closeAssetDetail();
    });
  }
  const modalReject = document.querySelector("[data-modal-reject]");
  if (modalReject) {
    modalReject.addEventListener("click", async () => { await rejectSubmission(asset.id); closeAssetDetail(); });
  }
  document.querySelector("[data-save-metadata]").addEventListener("click", () => saveMetadata(asset.id, isPublished ? "approved" : "not-reviewed"));
  document.querySelectorAll("[data-review-metadata]").forEach((button) => button.addEventListener("click", () => saveMetadata(asset.id, button.dataset.reviewStatus)));
  const modalDelete = document.querySelector("[data-modal-delete]");
  if (modalDelete) {
    modalDelete.addEventListener("click", async () => {
      const notes = document.querySelector("[data-delete-notes]")?.value.trim() || "";
      await deleteSubmission(asset.id, notes);
    });
  }
  document.querySelector("[data-rights-owned]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await api("/api/narrator/rights/owned", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({audioAssetId: asset.id})});
      showToast("Rights approved: KathaChepta owns this story");
      await loadAssetDetail(asset.id, true);
    } catch (error) { button.disabled = false; showToast(error.message); }
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
      showToast(`${{teaser: "Teaser generation", artwork: "Artwork generation", media: "Audio processing"}[button.dataset.process] || "Transcription"} queued`);
      await loadAssetDetail(asset.id, true);
    } catch (error) {
      button.disabled = false;
      button.textContent = "Retry";
      button.parentElement.querySelector(".process-error")?.remove();
      button.insertAdjacentHTML("afterend", `<div class="process-error job-error"><b>${escapeHtml(error.message)}</b>${error.diagnostics ? `<code>${escapeHtml(error.diagnostics)}</code>` : ""}</div>`);
      showToast(error.message);
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
  // Announce only when a job we were watching has just finished, not for old job history.
  const wasWatching = watchingJobsFor === asset.id;
  watchingJobsFor = activeJob ? asset.id : null;
  if (activeJob) {
    assetPollTimer = setTimeout(async () => {
      try {
        await loadAssetDetail(asset.id, announceCompletion);
      } catch (error) {
        showToast(`Could not refresh processing status: ${error.message}`);
      }
    }, 3000);
  } else if (announceCompletion && wasWatching) {
    const failed = [transcriptionJob, teaserJob, artworkJob, mediaJob].some((job) => job?.status === "failed");
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
  appView.hidden = false; document.querySelector("#username").textContent = session.username;
  checkServerHealth();
  await loadDashboard(); await loadQueue();
}
document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", async () => {
  document.querySelector(".tab.active").classList.remove("active"); tab.classList.add("active"); currentQueue = tab.dataset.queue; await loadQueue();
}));
let searchTimer = null;
document.querySelector("#queue-search")?.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadQueue().catch((error) => showToast(error.message)), 300);
});
document.querySelector("#refresh").addEventListener("click", async () => { await loadDashboard(); await loadQueue(); showToast("Workspace refreshed"); });
document.querySelector("#logout").addEventListener("click", async () => { await api("/api/logout", {method:"POST"}); window.location.reload(); });
document.querySelector("#asset-close").addEventListener("click", closeAssetDetail);
document.querySelector("#asset-modal").addEventListener("click", (event) => { if (event.target.id === "asset-modal") closeAssetDetail(); });
enter().catch(() => { window.location.replace("/"); });

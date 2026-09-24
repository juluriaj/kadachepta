let stories = [
  { id: "chandamama", title: "చందమామ కథలు", narrator: "సుజాతా రావు", category: "bedtime", label: "Bedtime", duration: "8 min", cover: "cover-orange", audio: "" },
  { id: "ramayana", title: "శ్రీరాముని వనవాసం", narrator: "వేణు మాధవ్", category: "epics", label: "Ramayana", duration: "24 min", cover: "cover-blue", audio: "" },
  { id: "tenali", title: "తెలివైన తెనాలి రామకృష్ణ", narrator: "రమేష్ కుమార్", category: "folklore", label: "Folklore", duration: "12 min", cover: "", audio: "" },
  { id: "mahabharatam", title: "మహాభారతం: కర్ణుడు", narrator: "అనురాధ", category: "epics", label: "Mahabharatam", duration: "31 min", cover: "cover-purple", audio: "" },
  { id: "little-light", title: "చిన్న దీపం కథ", narrator: "సుజాతా రావు", category: "inspiration", label: "Inspiration", duration: "9 min", cover: "cover-blue", audio: "" },
  { id: "panchatantra", title: "పంచతంత్ర కథలు", narrator: "వేణు మాధవ్", category: "folklore", label: "Folklore", duration: "15 min", cover: "cover-orange", audio: "" },
  { id: "sleeping-forest", title: "నిద్రించే అడవి", narrator: "అనురాధ", category: "bedtime", label: "Bedtime", duration: "11 min", cover: "cover-purple", audio: "" },
  { id: "vivekananda", title: "వివేకానందుని ప్రేరణ", narrator: "రమేష్ కుమార్", category: "inspiration", label: "Inspiration", duration: "18 min", cover: "", audio: "" },
];

const state = { filter: "all", query: "", currentIndex: 0, playing: false };
const saved = new Set();
const accountDialog = document.querySelector("#account-dialog");
const grid = document.querySelector("#story-grid");
const emptyState = document.querySelector("#empty-state");
const audio = document.querySelector("#audio");
const loginView = document.querySelector("#login-view");
const loginForm = document.querySelector("#login-form");
const loginError = document.querySelector("#login-error");
const profileButton = document.querySelector("#profile-button");
const profileMenu = document.querySelector("#profile-menu");
let currentSession = null;

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function loadCatalog() {
  const response = await fetch("/api/catalog");
  if (!response.ok) throw new Error("Published catalog is unavailable.");
  const data = await response.json();
  stories = data.items.map((item) => ({
    id: item.id,
    title: item.title,
    narrator: item.narrator || "KathaChepta",
    category: ((item.metadata?.genres || [item.genre || "stories"])[0] || "stories").toLowerCase(),
    label: item.album || item.collection || "Stories",
    duration: `${Math.max(1, Math.round((item.duration || 0) / 60))} min`,
    cover: "",
    artwork: item.artworkUrl || "",
    audio: item.audioUrl || "",
    audioDataSaver: item.audioUrlDataSaver || "",
    teaser: item.longText || item.shortText || "",
    keywords: item.metadata?.keywords || [],
  }));
  const genres = [...new Set(data.items.flatMap((item) => item.metadata?.genres || (item.genre ? [item.genre] : [])))].sort();
  const filters = document.querySelector(".filters");
  filters.innerHTML = [`<button class="filter active" data-filter="all" type="button">All stories</button>`,
    ...genres.map((genre) => `<button class="filter" data-filter="${escapeHtml(genre.toLowerCase())}" type="button">${escapeHtml(genre)}</button>`)].join("");
  filters.querySelectorAll(".filter").forEach((button) => button.addEventListener("click", () => {
    filters.querySelector(".filter.active")?.classList.remove("active");
    button.classList.add("active");
    state.filter = button.dataset.filter;
    renderStories();
  }));
  state.currentIndex = 0;
  renderStories();
  await loadFavorites();
}

async function loadFavorites() {
  let ids = [];
  try {
    ids = (await apiJson("/api/me/favorites")).ids;
    // One-time move of favorites saved in this browser before they were stored per account.
    const legacy = JSON.parse(localStorage.getItem("kadachepta-saved") || "[]")
      .filter((id) => stories.some((story) => story.id === id) && !ids.includes(id));
    if (legacy.length) ids = (await apiJson("/api/me/favorites", { method: "POST", body: { assetIds: legacy, saved: true } })).ids;
    localStorage.removeItem("kadachepta-saved");
  } catch (error) {
    showToast("Favorites are unavailable right now.");
  }
  saved.clear();
  ids.forEach((id) => saved.add(id));
  updateFavoritesCount();
  renderStories();
}

async function apiJson(url, { method = "GET", body } = {}) {
  const response = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}

function redirectForRole(session) {
  if (session.role === "editor" || session.role === "admin") {
    window.location.replace("/editor/");
    return;
  }
  if (session.role === "narrator") {
    window.location.replace("/narrator/");
    return;
  }
  document.body.classList.add("authenticated");
  loginView.hidden = true;
  currentSession = session;
  const displayName = session.username || "Profile";
  document.querySelector("#profile-name").textContent = displayName;
  document.querySelector("#profile-menu-name").textContent = displayName;
  document.querySelector("#profile-menu-role").textContent = session.role || "Listener";
  if (session.permissions?.includes("transcript.review")) {
    document.querySelector("#editor-link").hidden = false;
    document.querySelector("#profile-editor-link").hidden = false;
  }
}

async function loadSession() {
  const response = await fetch("/api/session");
  const session = await response.json();
  if (session.authenticated && (session.mfaRequired || session.mfaEnrollmentRequired)) return startMfa(session);
  if (session.authenticated) {
    redirectForRole(session);
    if (session.permissions?.includes("catalog.read")) {
      try { await loadCatalog(); } catch (error) { showToast(error.message); }
    }
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  const payload = Object.fromEntries(new FormData(loginForm));
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to sign in.");
    if (result.mfaRequired || result.mfaEnrollmentRequired) return startMfa(result);
    redirectForRole(result);
    if (result.permissions?.includes("catalog.read")) await loadCatalog();
  } catch (error) {
    loginError.textContent = error.message;
  }
});

const mfaForm = document.querySelector("#mfa-form");
async function startMfa(result) {
  loginForm.hidden = true;
  mfaForm.hidden = false;
  if (result.mfaEnrollmentRequired) {
    const setup = await apiJson("/api/auth/totp/setup", { method: "POST", body: {} });
    document.querySelector("#mfa-enroll").hidden = false;
    document.querySelector("#mfa-intro").hidden = true;
    document.querySelector("#mfa-secret").textContent = setup.secret;
  }
  mfaForm.querySelector("input").focus();
}
mfaForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorText = document.querySelector("#mfa-error");
  errorText.textContent = "";
  try {
    const result = await apiJson("/api/auth/totp/verify", { method: "POST", body: { code: new FormData(mfaForm).get("code") } });
    redirectForRole(result);
    if (result.permissions?.includes("catalog.read")) await loadCatalog();
  } catch (error) {
    errorText.textContent = error.message;
  }
});

function renderStories() {
  const visible = stories.filter((story) => {
    const matchesFilter = state.filter === "all" || story.category === state.filter;
    const searchText = `${story.title} ${story.narrator} ${story.label} ${(story.keywords || []).join(" ")}`.toLowerCase();
    return matchesFilter && searchText.includes(state.query.toLowerCase());
  });
  if (!stories.length) {
    grid.innerHTML = "";
    emptyState.textContent = "No published stories are available yet.";
    emptyState.hidden = false;
    return;
  }
  emptyState.textContent = "No stories match your search yet.";
  grid.innerHTML = visible.map((story) => `
    <article class="story-card">
      <button class="card-save ${saved.has(story.id) ? "saved" : ""}" data-save="${story.id}" type="button" aria-label="Save ${story.title}">${saved.has(story.id) ? "♥" : "♡"}</button>
      <div class="cover ${story.cover}"${story.artwork ? ` style="background-image: url('${escapeHtml(story.artwork)}')"` : ""}><span class="cover-title">${escapeHtml(story.title)}</span></div>
      <div class="card-body">
        <h3>${escapeHtml(story.title)}</h3>
        <p>${escapeHtml(story.narrator)}</p>
        <div class="card-meta">
          <span>${story.label} · ${story.duration}</span>
          <button class="card-play" data-play="${story.id}" type="button" aria-label="Play ${story.title}">▶</button>
        </div>
      </div>
    </article>
  `).join("");
  emptyState.hidden = visible.length !== 0;
  grid.querySelectorAll("[data-play]").forEach((button) => button.addEventListener("click", () => playStory(button.dataset.play)));
  grid.querySelectorAll("[data-save]").forEach((button) => button.addEventListener("click", () => toggleSaved(button.dataset.save)));
}

function currentStory() { return stories[state.currentIndex]; }

// Listening time counts only real playback (not seeking) and is reported in small batches.
const listening = { assetId: null, pending: 0, lastTime: null, started: false };
function localDay() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
function flushListening({ completed = false, beacon = false } = {}) {
  if (!listening.assetId || (!listening.pending && !listening.started && !completed)) return;
  const body = JSON.stringify({
    assetId: listening.assetId, seconds: Math.round(listening.pending * 10) / 10,
    position: audio.currentTime || 0, started: listening.started, completed, day: localDay(),
  });
  listening.pending = 0;
  listening.started = false;
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon("/api/me/listening", new Blob([body], { type: "application/json" }));
    return;
  }
  fetch("/api/me/listening", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => {});
}
function beginListening(id) {
  if (listening.assetId === id) return;
  flushListening();
  Object.assign(listening, { assetId: id, pending: 0, lastTime: null, started: true });
}
audio.addEventListener("timeupdate", () => {
  const now = audio.currentTime;
  if (!audio.paused && listening.lastTime !== null) {
    const delta = now - listening.lastTime;
    if (delta > 0 && delta < 3) listening.pending += delta;
  }
  listening.lastTime = now;
  if (listening.pending >= 15) flushListening();
});
audio.addEventListener("seeking", () => { listening.lastTime = null; });
audio.addEventListener("pause", () => { listening.lastTime = null; flushListening(); });
audio.addEventListener("ended", () => flushListening({ completed: true }));
window.addEventListener("pagehide", () => flushListening({ beacon: true }));
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flushListening({ beacon: true }); });

function playStory(id) {
  const index = stories.findIndex((story) => story.id === id);
  if (index < 0) return;
  state.currentIndex = index;
  const story = currentStory();
  document.querySelector("#player-title").textContent = story.title;
  document.querySelector("#player-narrator").textContent = `${story.narrator} · ${story.duration}`;
  const playerCover = document.querySelector("#player-cover");
  playerCover.textContent = story.artwork ? "" : story.title.slice(0, 1);
  playerCover.style.backgroundImage = story.artwork ? `url('${story.artwork}')` : "";
  if (story.audio) {
    if (audio.src !== new URL(story.audio, window.location.href).href) audio.src = story.audio;
    if (currentSession) beginListening(story.id);
    audio.play().catch(() => showToast("Add the story audio file to begin playback."));
    state.playing = true;
    document.querySelector("#play-button").textContent = "Ⅱ";
  } else {
    state.playing = false;
    document.querySelector("#play-button").textContent = "▶";
    showToast("This story is ready for audio. Add its file in /audio to play it.");
  }
}
async function toggleSaved(id) {
  const willSave = !saved.has(id);
  if (willSave) saved.add(id); else saved.delete(id);
  renderStories();
  updateFavoritesCount();
  try {
    const result = await apiJson("/api/me/favorites", { method: "POST", body: { assetId: id, saved: willSave } });
    saved.clear();
    result.ids.forEach((savedId) => saved.add(savedId));
    showToast(willSave ? "Added to favorites" : "Removed from favorites");
  } catch (error) {
    if (willSave) saved.delete(id); else saved.add(id);
    showToast(`Could not update favorites: ${error.message}`);
  }
  renderStories();
  updateFavoritesCount();
  if (accountDialog.open && accountDialog.dataset.view === "favorites") renderFavorites();
}
function updateFavoritesCount() {
  document.querySelector("#favorites-count").textContent = saved.size;
}
function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timeout);
  showToast.timeout = setTimeout(() => toast.classList.remove("show"), 2800);
}
function goToStory(offset) {
  const next = (state.currentIndex + offset + stories.length) % stories.length;
  playStory(stories[next].id);
}

document.querySelector("#search-input").addEventListener("input", (event) => { state.query = event.target.value; renderStories(); });
document.querySelectorAll(".filter").forEach((button) => button.addEventListener("click", () => {
  document.querySelector(".filter.active").classList.remove("active");
  button.classList.add("active");
  state.filter = button.dataset.filter;
  renderStories();
}));
document.querySelector("#play-button").addEventListener("click", () => {
  if (!currentStory()) return;
  if (!audio.src) return playStory(currentStory().id);
  if (audio.paused) { audio.play(); state.playing = true; } else { audio.pause(); state.playing = false; }
  document.querySelector("#play-button").textContent = state.playing ? "Ⅱ" : "▶";
});
document.querySelector("#back-button").addEventListener("click", () => goToStory(-1));
document.querySelector("#next-button").addEventListener("click", () => goToStory(1));
document.querySelector("#browse-button").addEventListener("click", () => document.querySelector("#library").scrollIntoView());
document.querySelector("#resume-button").addEventListener("click", () => playStory("chandamama"));
document.querySelector("#sleep-button").addEventListener("click", () => showToast("Sleep timer set for 30 minutes"));
document.querySelector("#caption-button").addEventListener("click", () => showToast("Telugu and English captions are coming with the next catalog update"));
document.querySelector("#queue-button").addEventListener("click", () => showToast("Your listening queue is ready"));
audio.addEventListener("timeupdate", () => {
  document.querySelector("#progress").value = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
  document.querySelector("#current-time").textContent = formatTime(audio.currentTime);
  document.querySelector("#total-time").textContent = formatTime(audio.duration);
});
document.querySelector("#progress").addEventListener("input", (event) => { if (audio.duration) audio.currentTime = (event.target.value / 100) * audio.duration; });
function formatTime(seconds) { return Number.isFinite(seconds) ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}` : "0:00"; }

function setProfileMenu(open) {
  profileMenu.hidden = !open;
  profileButton.setAttribute("aria-expanded", String(open));
}
profileButton.addEventListener("click", (event) => {
  event.stopPropagation();
  setProfileMenu(profileMenu.hidden);
});
document.addEventListener("click", (event) => {
  if (!profileMenu.hidden && !profileMenu.contains(event.target)) setProfileMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !profileMenu.hidden) { setProfileMenu(false); profileButton.focus(); }
});
document.querySelector("#logout-button").addEventListener("click", async () => {
  flushListening({ beacon: true });
  await fetch("/api/logout", { method: "POST" }).catch(() => {});
  currentSession = null;
  window.location.replace("/");
});
document.querySelectorAll("[data-account-view]").forEach((button) => button.addEventListener("click", () => {
  setProfileMenu(false);
  openAccount(button.dataset.accountView);
}));
document.querySelector("#account-close").addEventListener("click", () => accountDialog.close());
accountDialog.addEventListener("click", (event) => { if (event.target === accountDialog) accountDialog.close(); });

function openAccount(view) {
  accountDialog.dataset.view = view;
  accountDialog.querySelectorAll(".account-tabs [data-account-view]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.accountView === view);
    tab.setAttribute("aria-selected", String(tab.dataset.accountView === view));
  });
  document.querySelector("#account-title").textContent = view === "stats" ? "Your listening" : "Favorites";
  if (!accountDialog.open) accountDialog.showModal();
  if (view === "stats") renderStats(); else renderFavorites();
}

function renderFavorites() {
  const body = document.querySelector("#account-body");
  const favorites = stories.filter((story) => saved.has(story.id));
  if (!favorites.length) {
    body.innerHTML = `<p class="account-empty">No favorites yet. Tap ♡ on any story to keep it here.</p>`;
    return;
  }
  body.innerHTML = `<ul class="favorite-list">${favorites.map((story) => `
    <li>
      <div class="favorite-cover"${story.artwork ? ` style="background-image: url('${escapeHtml(story.artwork)}')"` : ""}>${story.artwork ? "" : escapeHtml(story.title.slice(0, 1))}</div>
      <div class="favorite-info"><strong>${escapeHtml(story.title)}</strong><small>${escapeHtml(story.narrator)} · ${escapeHtml(story.duration)}</small></div>
      <button class="favorite-play" type="button" data-fav-play="${escapeHtml(story.id)}" aria-label="Play ${escapeHtml(story.title)}">▶</button>
      <button class="favorite-remove" type="button" data-fav-remove="${escapeHtml(story.id)}">Remove</button>
    </li>`).join("")}</ul>`;
  body.querySelectorAll("[data-fav-play]").forEach((button) => button.addEventListener("click", () => {
    accountDialog.close();
    playStory(button.dataset.favPlay);
  }));
  body.querySelectorAll("[data-fav-remove]").forEach((button) => button.addEventListener("click", () => toggleSaved(button.dataset.favRemove)));
}

function formatListenTime(seconds) {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

async function renderStats() {
  const body = document.querySelector("#account-body");
  body.innerHTML = `<p class="account-empty">Loading your listening…</p>`;
  flushListening();
  let stats;
  try {
    stats = await apiJson(`/api/me/stats?today=${localDay()}`);
  } catch (error) {
    body.innerHTML = `<p class="account-empty">Stats are unavailable: ${escapeHtml(error.message)}</p>`;
    return;
  }
  if (accountDialog.dataset.view !== "stats") return;
  const topGenre = stats.genres[0]?.seconds || 1;
  const genreRows = stats.genres.slice(0, 6).map((genre) => `
    <li><span>${escapeHtml(genre.genre)}</span><div><i style="width: ${Math.max(4, (genre.seconds / topGenre) * 100)}%"></i></div><small>${formatListenTime(genre.seconds)}</small></li>`).join("");
  const recentRows = stats.recent.map((item) => `
    <li><strong>${escapeHtml(item.title)}</strong><small>${item.completed ? "Finished" : `Stopped at ${formatTime(item.position)}`} · ${formatListenTime(item.seconds)} listened</small></li>`).join("");
  body.innerHTML = `
    <div class="stat-tiles">
      <div><b>${formatListenTime(stats.totalSeconds)}</b><span>Total listening</span></div>
      <div><b>${formatListenTime(stats.weekSeconds)}</b><span>Last 7 days</span></div>
      <div><b>${stats.storiesStarted}</b><span>Stories listened</span></div>
      <div><b>${stats.storiesCompleted}</b><span>Finished</span></div>
      <div><b>${stats.streakDays}</b><span>Day streak</span></div>
      <div><b>${stats.favorites}</b><span>Favorites</span></div>
    </div>
    <h3>Genres</h3>
    ${genreRows ? `<ul class="genre-bars">${genreRows}</ul>` : `<p class="account-empty">Listen to a few stories to see your favorite genres.</p>`}
    <h3>Recently played</h3>
    ${recentRows ? `<ul class="recent-list">${recentRows}</ul>` : `<p class="account-empty">Nothing played yet.</p>`}`;
}

renderStories();
loadSession().catch(() => {
  loginError.textContent = "The sign-in service is unavailable. Please try again.";
});

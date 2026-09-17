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
const saved = new Set(JSON.parse(localStorage.getItem("kadachepta-saved") || "[]"));
const grid = document.querySelector("#story-grid");
const emptyState = document.querySelector("#empty-state");
const audio = document.querySelector("#audio");
const loginView = document.querySelector("#login-view");
const loginForm = document.querySelector("#login-form");
const loginError = document.querySelector("#login-error");
const profileButton = document.querySelector("#profile-button");
const profileMenu = document.querySelector("#profile-menu");
let currentSession = null;

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
    audio: `/audio/${encodeURI((item.sourcePath || "").replaceAll("\\", "/").replace(/^audio\//i, ""))}`,
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

    function setProfileMenu(open) {
      profileMenu.hidden = !open;
      profileButton.setAttribute("aria-expanded", String(open));
    }

    profileButton.addEventListener("click", () => {
      setProfileMenu(profileMenu.hidden);
    });

    document.addEventListener("click", (event) => {
      if (!profileMenu.hidden && !profileButton.contains(event.target) && !profileMenu.contains(event.target)) {
        setProfileMenu(false);
      }
    });

    document.querySelector("#logout-button").addEventListener("click", async () => {
      await fetch("/api/logout", { method: "POST" });
      currentSession = null;
      window.location.replace("/");
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to sign in.");
    redirectForRole(result);
    if (result.permissions?.includes("catalog.read")) await loadCatalog();
  } catch (error) {
    loginError.textContent = error.message;
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
      <div class="cover ${story.cover}">${story.title}</div>
      <div class="card-body">
        <h3>${story.title}</h3>
        <p>${story.narrator}</p>
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
function playStory(id) {
  const index = stories.findIndex((story) => story.id === id);
  if (index < 0) return;
  state.currentIndex = index;
  const story = currentStory();
  document.querySelector("#player-title").textContent = story.title;
  document.querySelector("#player-narrator").textContent = `${story.narrator} · ${story.duration}`;
  document.querySelector("#player-cover").textContent = story.title.slice(0, 1);
  if (story.audio) {
    if (audio.src !== new URL(story.audio, window.location.href).href) audio.src = story.audio;
    audio.play().catch(() => showToast("Add the story audio file to begin playback."));
    state.playing = true;
    document.querySelector("#play-button").textContent = "Ⅱ";
  } else {
    state.playing = false;
    document.querySelector("#play-button").textContent = "▶";
    showToast("This story is ready for audio. Add its file in /audio to play it.");
  }
}
function toggleSaved(id) {
  if (saved.has(id)) saved.delete(id); else saved.add(id);
  localStorage.setItem("kadachepta-saved", JSON.stringify([...saved]));
  renderStories();
  loadSession().catch(() => {
    loginError.textContent = "The sign-in service is unavailable. Please try again.";
  });
  showToast(saved.has(id) ? "Saved to your library" : "Removed from your library");
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

renderStories();

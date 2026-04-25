(() => {
  const els = {
    list: document.getElementById("list"),
    empty: document.getElementById("empty"),
    meta: document.getElementById("meta"),
    updated: document.getElementById("updated"),
    q: document.getElementById("q"),
    genre: document.getElementById("genre"),
    type: document.getElementById("type"),
    status: document.getElementById("status"),
    minRating: document.getElementById("minRating"),
    minRatingVal: document.getElementById("minRatingVal"),
    sort: document.getElementById("sort"),
    reset: document.getElementById("reset"),
  };

  const state = { shows: [], updated: "" };

  const STATUS_LABEL = {
    "original": "Netflix Original",
    "exclusive-region": "Regional Exclusive",
    "library": "Library",
  };

  const TYPE_LABEL = {
    "series": "Series",
    "limited-series": "Limited Series",
    "movie": "Movie",
  };

  const imdbSearchUrl = (title, year) =>
    `https://www.imdb.com/find/?s=tt&q=${encodeURIComponent(title + " " + year)}`;

  const fmtVotes = (v) => {
    if (v >= 1_000_000) return (v / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
    if (v >= 1_000) return Math.round(v / 1_000) + "K";
    return String(v);
  };

  function readFilters() {
    return {
      q: els.q.value.trim().toLowerCase(),
      genre: els.genre.value,
      type: els.type.value,
      status: els.status.value,
      minRating: parseFloat(els.minRating.value) || 0,
      sort: els.sort.value,
    };
  }

  function syncQueryString(f) {
    const params = new URLSearchParams();
    if (f.q) params.set("q", f.q);
    if (f.genre) params.set("genre", f.genre);
    if (f.type) params.set("type", f.type);
    if (f.status) params.set("status", f.status);
    if (f.minRating > 0) params.set("min", String(f.minRating));
    if (f.sort && f.sort !== "rating") params.set("sort", f.sort);
    const qs = params.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  function loadFromQueryString() {
    const p = new URLSearchParams(location.search);
    if (p.has("q")) els.q.value = p.get("q");
    if (p.has("genre")) els.genre.value = p.get("genre");
    if (p.has("type")) els.type.value = p.get("type");
    if (p.has("status")) els.status.value = p.get("status");
    if (p.has("min")) {
      els.minRating.value = p.get("min");
      els.minRatingVal.textContent = parseFloat(p.get("min")).toFixed(1);
    }
    if (p.has("sort")) els.sort.value = p.get("sort");
  }

  function populateGenres(shows) {
    const set = new Set();
    shows.forEach((s) => s.genres.forEach((g) => set.add(g)));
    const sorted = [...set].sort((a, b) => a.localeCompare(b));
    for (const g of sorted) {
      const opt = document.createElement("option");
      opt.value = g;
      opt.textContent = g;
      els.genre.appendChild(opt);
    }
  }

  function applyFilters(shows, f) {
    let out = shows.filter((s) => {
      if (f.q && !s.title.toLowerCase().includes(f.q)) return false;
      if (f.genre && !s.genres.includes(f.genre)) return false;
      if (f.type && s.type !== f.type) return false;
      if (f.status && s.netflix_status !== f.status) return false;
      if (s.rating < f.minRating) return false;
      return true;
    });

    const cmp = {
      "rating": (a, b) => b.rating - a.rating || b.votes - a.votes,
      "rating-asc": (a, b) => a.rating - b.rating || a.votes - b.votes,
      "votes": (a, b) => b.votes - a.votes,
      "year-desc": (a, b) => b.year - a.year || b.rating - a.rating,
      "year-asc": (a, b) => a.year - b.year || b.rating - a.rating,
      "title": (a, b) => a.title.localeCompare(b.title),
    }[f.sort] || ((a, b) => b.rating - a.rating);

    return out.sort(cmp);
  }

  function render() {
    const f = readFilters();
    syncQueryString(f);
    const items = applyFilters(state.shows, f);

    els.list.innerHTML = "";
    els.empty.hidden = items.length > 0;
    els.meta.textContent = `Showing ${items.length} of ${state.shows.length} titles`;

    const frag = document.createDocumentFragment();
    items.forEach((s, i) => {
      const li = document.createElement("li");
      li.className = "card" + (i < 3 ? " top" : "");
      li.innerHTML = `
        <div class="rank">${i + 1}</div>
        <div class="title">
          <a href="${imdbSearchUrl(s.title, s.year)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title)}</a>
          <div class="sub">
            <span>${s.year}</span>
            <span>·</span>
            <span>${TYPE_LABEL[s.type] || s.type}</span>
            <span class="tag ${s.netflix_status === "original" ? "original" : ""}">${STATUS_LABEL[s.netflix_status] || s.netflix_status}</span>
            ${s.genres.slice(0, 3).map((g) => `<span class="tag">${escapeHtml(g)}</span>`).join("")}
          </div>
        </div>
        <div class="score" title="${s.votes.toLocaleString()} votes">
          <div class="num">${s.rating.toFixed(1)}</div>
          <div class="label">${fmtVotes(s.votes)} votes</div>
        </div>
      `;
      frag.appendChild(li);
    });
    els.list.appendChild(frag);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
    }[c]));
  }

  function bind() {
    ["input", "change"].forEach((evt) => {
      els.q.addEventListener(evt, render);
      els.minRating.addEventListener(evt, () => {
        els.minRatingVal.textContent = parseFloat(els.minRating.value).toFixed(1);
        render();
      });
    });
    [els.genre, els.type, els.status, els.sort].forEach((el) =>
      el.addEventListener("change", render)
    );
    els.reset.addEventListener("click", () => {
      els.q.value = "";
      els.genre.value = "";
      els.type.value = "";
      els.status.value = "";
      els.minRating.value = "0";
      els.minRatingVal.textContent = "0.0";
      els.sort.value = "rating";
      render();
    });
  }

  async function init() {
    try {
      const res = await fetch("shows.json", { cache: "no-cache" });
      if (!res.ok) throw new Error("Failed to load shows.json: " + res.status);
      const data = await res.json();
      state.shows = data.shows || [];
      state.updated = data.updated || "";
      els.updated.textContent = state.updated || "—";
      populateGenres(state.shows);
      loadFromQueryString();
      bind();
      render();
    } catch (err) {
      els.meta.textContent = "Could not load data. " + err.message;
    }
  }

  init();
})();

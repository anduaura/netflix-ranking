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
    language: document.getElementById("language"),
    region: document.getElementById("region"),
    supportBtn: document.getElementById("supportBtn"),
    supportDialog: document.getElementById("supportDialog"),
    supportLinks: document.getElementById("supportLinks"),
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

  // ISO 639-1 → display name. Extend as the catalog grows.
  const LANGUAGE_LABEL = {
    en: "English", ko: "Korean", ja: "Japanese", es: "Spanish",
    fr: "French", de: "German", it: "Italian", pt: "Portuguese",
    zh: "Chinese", hi: "Hindi", ar: "Arabic", ru: "Russian",
    th: "Thai", tr: "Turkish", id: "Indonesian", nl: "Dutch",
    sv: "Swedish", da: "Danish", no: "Norwegian", pl: "Polish",
    he: "Hebrew", uk: "Ukrainian", vi: "Vietnamese", tl: "Tagalog",
    fi: "Finnish", el: "Greek", cs: "Czech", ro: "Romanian",
    hu: "Hungarian", fa: "Persian",
  };
  const langLabel = (code) => LANGUAGE_LABEL[code] || (code ? code.toUpperCase() : "Unknown");

  // Major Netflix markets, in roughly subscriber-count order. Surfaced
  // first in the "Available on" dropdown.
  const POPULAR_REGIONS = [
    "US", "GB", "CA", "BR", "MX", "DE", "FR", "IN",
    "JP", "KR", "AU", "ES", "IT", "NL",
  ];

  // ISO 3166 country code → 🇺🇸-style flag emoji via regional indicators.
  function flagFor(code) {
    if (!code || code.length !== 2) return "";
    const base = 127397; // 'A' regional indicator offset from ASCII 'A'.
    return String.fromCodePoint(
      ...code.toUpperCase().split("").map((c) => base + c.charCodeAt(0)),
    );
  }

  const regionNamer = (() => {
    try { return new Intl.DisplayNames(["en"], { type: "region" }); }
    catch { return null; }
  })();
  function regionName(code) {
    if (regionNamer) {
      try { return regionNamer.of(code) || code; } catch { return code; }
    }
    return code;
  }
  const regionLabel = (code) => `${flagFor(code)} ${regionName(code)}`.trim();

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
      language: els.language.value,
      region: els.region.value,
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
    if (f.language) params.set("lang", f.language);
    if (f.region) params.set("region", f.region);
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
    if (p.has("lang")) els.language.value = p.get("lang");
    if (p.has("region")) els.region.value = p.get("region");
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

  function populateLanguages(shows) {
    const set = new Set();
    shows.forEach((s) => { if (s.original_language) set.add(s.original_language); });
    const codes = [...set].sort((a, b) => langLabel(a).localeCompare(langLabel(b)));
    for (const code of codes) {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = langLabel(code);
      els.language.appendChild(opt);
    }
  }

  function populateRegions(shows, configuredRegions) {
    // Union of configured regions + anything we've actually seen in
    // the data. Only keep regions that are real candidates.
    const set = new Set(configuredRegions || []);
    shows.forEach((s) => (s.available_in || []).forEach((r) => set.add(r)));
    if (!set.size) {
      els.region.parentElement.hidden = true;
      return;
    }
    const popular = POPULAR_REGIONS.filter((c) => set.has(c));
    const popularSet = new Set(popular);
    const rest = [...set]
      .filter((c) => !popularSet.has(c))
      .sort((a, b) => regionName(a).localeCompare(regionName(b)));

    const opt = (c) => `<option value="${escapeHtml(c)}">${escapeHtml(regionLabel(c))}</option>`;
    let html = '<option value="">Anywhere</option>';
    if (popular.length) {
      html += `<optgroup label="Popular">${popular.map(opt).join("")}</optgroup>`;
    }
    if (rest.length) {
      html += `<optgroup label="All regions">${rest.map(opt).join("")}</optgroup>`;
    }
    els.region.innerHTML = html;
  }

  function applyFilters(shows, f) {
    let out = shows.filter((s) => {
      if (f.q && !s.title.toLowerCase().includes(f.q)) return false;
      if (f.genre && !s.genres.includes(f.genre)) return false;
      if (f.type && s.type !== f.type) return false;
      if (f.status && s.netflix_status !== f.status) return false;
      if (f.language && s.original_language !== f.language) return false;
      if (f.region) {
        const avail = s.available_in || [];
        if (!avail.includes(f.region)) return false;
      }
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
      const langTag = s.original_language && s.original_language !== "en"
        ? `<span class="tag tag-lang">${escapeHtml(langLabel(s.original_language))}</span>`
        : "";
      li.innerHTML = `
        <div class="rank">${i + 1}</div>
        <div class="title">
          <a href="${imdbSearchUrl(s.title, s.year)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title)}</a>
          <div class="sub">
            <span>${s.year}</span>
            <span>·</span>
            <span>${TYPE_LABEL[s.type] || s.type}</span>
            <span class="tag ${s.netflix_status === "original" ? "original" : ""}">${STATUS_LABEL[s.netflix_status] || s.netflix_status}</span>
            ${langTag}
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

  function buildSupportProviders(s) {
    const out = [];
    if (s.github_sponsors) out.push({ id: "github", label: "GitHub Sponsors", url: `https://github.com/sponsors/${encodeURIComponent(s.github_sponsors)}` });
    if (s.buy_me_a_coffee) out.push({ id: "bmc",    label: "Buy Me a Coffee", url: `https://www.buymeacoffee.com/${encodeURIComponent(s.buy_me_a_coffee)}` });
    if (s.kofi)            out.push({ id: "kofi",   label: "Ko-fi",            url: `https://ko-fi.com/${encodeURIComponent(s.kofi)}` });
    if (s.paypal)          out.push({ id: "paypal", label: "PayPal",           url: `https://www.paypal.com/paypalme/${encodeURIComponent(s.paypal)}` });
    if (s.custom && s.custom.url && s.custom.label) {
      out.push({ id: "custom", label: s.custom.label, url: s.custom.url });
    }
    return out;
  }

  function setupSupport() {
    const cfg = (window.SITE_CONFIG && window.SITE_CONFIG.support) || {};
    const providers = buildSupportProviders(cfg);
    if (providers.length === 0) return;

    els.supportBtn.hidden = false;

    els.supportLinks.innerHTML = providers.map((p) => `
      <li>
        <a class="support-link support-${p.id}" href="${p.url}" target="_blank" rel="noopener noreferrer">
          ${escapeHtml(p.label)}
        </a>
      </li>
    `).join("");

    els.supportBtn.addEventListener("click", () => {
      if (typeof els.supportDialog.showModal === "function") {
        els.supportDialog.showModal();
      } else {
        // Fallback for ancient browsers without <dialog>.
        window.open(providers[0].url, "_blank", "noopener");
      }
    });

    els.supportDialog.addEventListener("click", (e) => {
      if (e.target === els.supportDialog) els.supportDialog.close();
    });
  }

  function bind() {
    ["input", "change"].forEach((evt) => {
      els.q.addEventListener(evt, render);
      els.minRating.addEventListener(evt, () => {
        els.minRatingVal.textContent = parseFloat(els.minRating.value).toFixed(1);
        render();
      });
    });
    [els.genre, els.type, els.status, els.language, els.region, els.sort].forEach((el) =>
      el.addEventListener("change", render)
    );
    els.reset.addEventListener("click", () => {
      els.q.value = "";
      els.genre.value = "";
      els.type.value = "";
      els.status.value = "";
      els.language.value = "";
      els.region.value = "";
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
      populateLanguages(state.shows);
      populateRegions(state.shows, data.regions);
      loadFromQueryString();
      bind();
      setupSupport();
      render();
    } catch (err) {
      els.meta.textContent = "Could not load data. " + err.message;
    }
  }

  init();
})();

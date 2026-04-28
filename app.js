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
    aboutBtns: document.querySelectorAll(".js-about"),
    aboutDialog: document.getElementById("aboutDialog"),
    feedbackBtns: document.querySelectorAll(".js-feedback"),
    feedbackDialog: document.getElementById("feedbackDialog"),
    feedbackText: document.getElementById("feedbackText"),
    feedbackGithub: document.getElementById("feedbackGithub"),
    feedbackEmail: document.getElementById("feedbackEmail"),
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
  // first in the "Available on" dropdown — these always appear in the
  // Popular section even when the catalog has no data backing them yet.
  const POPULAR_REGIONS = [
    "US", "GB", "CA", "BR", "MX", "DE", "FR", "IN",
    "JP", "KR", "VN", "AU", "ES", "IT", "NL",
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

  // Netflix's search auto-routes to the viewer's home region/account when
  // they're signed in, so a single URL works globally without us needing
  // per-region deep-link IDs.
  const netflixSearchUrl = (title) =>
    `https://www.netflix.com/search?q=${encodeURIComponent(title)}`;

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
    // Count how many catalog entries actually list each region in
    // available_in. Drives the dropdown contents and the per-region
    // hint when a popular region has no data yet.
    const counts = new Map();
    shows.forEach((s) => (s.available_in || []).forEach((r) => {
      counts.set(r, (counts.get(r) || 0) + 1);
    }));
    (configuredRegions || []).forEach((r) => {
      if (!counts.has(r)) counts.set(r, 0);
    });

    // Popular section: ALWAYS show every popular region, even when no
    // titles back it yet. Picking a zero-count region just returns an
    // empty list — same as any over-narrow filter combination.
    const popularSet = new Set(POPULAR_REGIONS);
    const rest = [...counts.keys()]
      .filter((c) => !popularSet.has(c) && counts.get(c) > 0)
      .sort((a, b) => regionName(a).localeCompare(regionName(b)));

    const opt = (c) => {
      const n = counts.get(c) || 0;
      const suffix = n === 0 ? " (no titles yet)" : "";
      return `<option value="${escapeHtml(c)}">${escapeHtml(regionLabel(c) + suffix)}</option>`;
    };

    let html = '<option value="">Anywhere</option>';
    html += `<optgroup label="Popular">${POPULAR_REGIONS.map(opt).join("")}</optgroup>`;
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
      const langTag = s.original_language && s.original_language !== "en"
        ? `<span class="tag tag-lang">${escapeHtml(langLabel(s.original_language))}</span>`
        : "";
      li.innerHTML = `
        <a class="card${i < 3 ? " top" : ""}" href="${netflixSearchUrl(s.title)}" target="_blank" rel="noopener noreferrer" title="Open on Netflix">
          <div class="rank">${i + 1}</div>
          <div class="title">
            <span class="title-text">${escapeHtml(s.title)}</span>
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
        </a>
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

  function openDialog(dlg) {
    if (!dlg) return;
    if (typeof dlg.showModal === "function") {
      dlg.showModal();
    } else {
      dlg.setAttribute("open", "");
    }
  }

  function bindDialogDismiss(dlg) {
    if (!dlg) return;
    // Click outside the content (i.e., on the backdrop) closes.
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg) dlg.close();
    });
  }

  function setupAbout() {
    if (!els.aboutDialog || !els.aboutBtns.length) return;
    els.aboutBtns.forEach((btn) =>
      btn.addEventListener("click", () => openDialog(els.aboutDialog)),
    );
    bindDialogDismiss(els.aboutDialog);
  }

  function setupFeedback() {
    if (!els.feedbackDialog || !els.feedbackBtns.length) return;
    const cfg = (window.SITE_CONFIG && window.SITE_CONFIG.feedback) || {};
    const email = cfg.email || "";
    const repo = cfg.github_repo || "";

    // Hide any channel that isn't configured.
    if (!email) els.feedbackEmail.hidden = true;
    if (!repo) els.feedbackGithub.hidden = true;

    // If no channel is configured at all, don't surface any feedback
    // entry-points.
    if (!email && !repo) {
      els.feedbackBtns.forEach((b) => (b.hidden = true));
      return;
    }

    const refresh = () => {
      const body = (els.feedbackText.value || "").trim();
      const subject = "Netflix IMDb Ranking — feedback";
      if (repo) {
        const params = new URLSearchParams({ title: subject });
        if (body) params.set("body", body);
        els.feedbackGithub.href = `https://github.com/${repo}/issues/new?${params.toString()}`;
      }
      if (email) {
        const params = new URLSearchParams({ subject });
        if (body) params.set("body", body);
        els.feedbackEmail.href = `mailto:${email}?${params.toString()}`;
      }
    };

    els.feedbackBtns.forEach((btn) =>
      btn.addEventListener("click", () => {
        refresh();
        openDialog(els.feedbackDialog);
        setTimeout(() => els.feedbackText.focus(), 0);
      }),
    );
    els.feedbackText.addEventListener("input", refresh);
    bindDialogDismiss(els.feedbackDialog);
    refresh(); // prime hrefs with empty body
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
    // Wire up dialogs first — these don't depend on data and we want them
    // working even if the catalog fetch fails.
    setupSupport();
    setupAbout();
    setupFeedback();

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
      render();
    } catch (err) {
      els.meta.textContent = "Could not load data. " + err.message;
    }
  }

  init();
})();

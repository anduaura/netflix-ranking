// Lightweight jsdom-based tests for the static site's frontend logic.
//
// What these are designed to catch:
//   * Render pipeline broken end-to-end (the "list disappeared" class
//     of bug)
//   * Setup functions throwing when expected elements are missing —
//     simulates the "cached old HTML + new app.js" deploy mismatch
//     that's bitten us once already.
//   * Filter logic regressions (genre, language, region, min rating).
//
// Run from the tests/ directory:
//     npm install   # one-time, pulls jsdom
//     npm test
//
// Tests are intentionally written without a framework — node + jsdom
// + a tiny assert helper. Adding mocha/jest would mean a heavier dep
// tree for a hobby project.

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const HTML = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const APP = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
const CONFIG = fs.readFileSync(path.join(ROOT, "config.js"), "utf8");

let passed = 0;
let failed = 0;
const failures = [];

function test(name, fn) {
  return Promise.resolve()
    .then(() => fn())
    .then(() => {
      passed++;
      console.log(`  ✓ ${name}`);
    })
    .catch((e) => {
      failed++;
      failures.push({ name, error: e });
      console.log(`  ✗ ${name}`);
      console.log(`      ${e && e.stack ? e.stack.split("\n")[0] : e}`);
    });
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(`${msg || "expected ==="}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}

// Mount the page with a stubbed fetch returning the supplied data.
// Returns once init() has rendered (or failed). Use `htmlOverride` to
// simulate cached-old-HTML scenarios.
async function mount({ data, htmlOverride } = {}) {
  const dom = new JSDOM(htmlOverride || HTML, {
    runScripts: "outside-only",
    url: "http://localhost/",
    pretendToBeVisual: true,
  });

  // Polyfill <dialog> open/close for jsdom (it doesn't implement them).
  const Dialog = dom.window.HTMLDialogElement && dom.window.HTMLDialogElement.prototype;
  if (Dialog && !Dialog.showModal) {
    Dialog.showModal = function () { this.setAttribute("open", ""); };
    Dialog.close = function () { this.removeAttribute("open"); };
  }

  const errors = [];
  dom.window.addEventListener("error", (e) => errors.push(e.message));
  const origErr = dom.window.console.error;
  dom.window.console.error = (...args) => { errors.push(args.join(" ")); origErr.apply(dom.window.console, args); };

  dom.window.fetch = () => Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  });

  dom.window.eval(CONFIG);
  dom.window.eval(APP);

  // Wait for async init() to settle.
  await new Promise((r) => setTimeout(r, 100));

  return { dom, errors };
}

const sample = {
  updated: "2026-04-29",
  regions: ["US", "KR", "JP", "VN"],
  shows: [
    {
      title: "Stranger Things", year: 2016, rating: 8.7, votes: 1450000,
      genres: ["Drama", "Horror"], type: "series", netflix_status: "original",
      original_language: "en", available_in: ["US", "KR"],
    },
    {
      title: "Squid Game", year: 2021, rating: 8.0, votes: 690000,
      genres: ["Action", "Drama"], type: "series", netflix_status: "original",
      original_language: "ko", available_in: ["KR", "JP"],
    },
    {
      title: "Death Note", year: 2006, rating: 9.0, votes: 320000,
      genres: ["Animation", "Crime"], type: "series", netflix_status: "library",
      original_language: "ja", available_in: ["JP"],
    },
    {
      title: "Roma", year: 2018, rating: 7.7, votes: 220000,
      genres: ["Drama"], type: "movie", netflix_status: "original",
      original_language: "es", available_in: ["MX", "US"],
    },
  ],
};

// ---------------------------------------------------------------------------

async function run() {
  console.log("Rendering");

  await test("renders one li per show with the sample data", async () => {
    const { dom, errors } = await mount({ data: sample });
    const list = dom.window.document.getElementById("list");
    assert(list, "list element exists");
    assertEqual(list.children.length, sample.shows.length, "one li per show");
    assert(errors.length === 0, `no console errors: ${errors.join("\n")}`);
  });

  await test("each row links to Netflix search for its title", async () => {
    const { dom } = await mount({ data: sample });
    const firstAnchor = dom.window.document.querySelector("#list .card");
    assert(firstAnchor, "first card exists");
    assert(
      firstAnchor.href.startsWith("https://www.netflix.com/search?q="),
      `expected netflix link, got: ${firstAnchor.href}`,
    );
    assert(firstAnchor.target === "_blank", "opens in new tab");
  });

  await test("empty catalog shows the empty-state message", async () => {
    const { dom } = await mount({ data: { ...sample, shows: [] } });
    const list = dom.window.document.getElementById("list");
    const empty = dom.window.document.getElementById("empty");
    assertEqual(list.children.length, 0, "no rows");
    assertEqual(empty.hidden, false, "empty message visible");
  });

  console.log("\nFilters");

  await test("genre filter narrows results", async () => {
    const { dom } = await mount({ data: sample });
    const genreSelect = dom.window.document.getElementById("genre");
    genreSelect.value = "Animation";
    genreSelect.dispatchEvent(new dom.window.Event("change"));
    const list = dom.window.document.getElementById("list");
    assertEqual(list.children.length, 1, "only Death Note has Animation");
  });

  await test("language filter narrows by original_language", async () => {
    const { dom } = await mount({ data: sample });
    const lang = dom.window.document.getElementById("language");
    lang.value = "ko";
    lang.dispatchEvent(new dom.window.Event("change"));
    const list = dom.window.document.getElementById("list");
    assertEqual(list.children.length, 1, "only Squid Game is Korean");
  });

  await test("region filter narrows by available_in", async () => {
    const { dom } = await mount({ data: sample });
    const region = dom.window.document.getElementById("region");
    region.value = "JP";
    region.dispatchEvent(new dom.window.Event("change"));
    const list = dom.window.document.getElementById("list");
    assertEqual(list.children.length, 2, "Squid Game + Death Note are on JP");
  });

  await test("min-rating slider filters out low ratings", async () => {
    const { dom } = await mount({ data: sample });
    const min = dom.window.document.getElementById("minRating");
    min.value = "8.5";
    min.dispatchEvent(new dom.window.Event("input"));
    const list = dom.window.document.getElementById("list");
    assertEqual(list.children.length, 2, "Stranger Things + Death Note ≥ 8.5");
  });

  console.log("\nDialog wiring");

  await test("Support / About / Feedback buttons all exist and are wired", async () => {
    const { dom } = await mount({ data: sample });
    const aboutBtns = dom.window.document.querySelectorAll(".js-about");
    const feedbackBtns = dom.window.document.querySelectorAll(".js-feedback");
    assert(aboutBtns.length >= 1, "at least one About button");
    assert(feedbackBtns.length >= 1, "at least one Feedback button");
    aboutBtns[0].click();
    const aboutDialog = dom.window.document.getElementById("aboutDialog");
    assert(aboutDialog.hasAttribute("open"), "about dialog opens");
  });

  console.log("\nResilience");

  // Simulate the exact deploy-mismatch bug we just hit: a previously
  // cached HTML that doesn't have the new feedbackSend / feedbackStatus
  // / feedbackHoney IDs, paired with the latest app.js. The page must
  // still render the list — a buggy setup must not take down init().
  await test("missing feedback elements don't break the list render", async () => {
    const stripped = HTML
      .replace(/<dialog id="feedbackDialog"[\s\S]*?<\/dialog>\s*/, "");
    const { dom, errors } = await mount({ data: sample, htmlOverride: stripped });
    const list = dom.window.document.getElementById("list");
    assert(list, "list element exists");
    assertEqual(list.children.length, sample.shows.length, "list still renders");
    // We tolerate console.warn output but not unhandled exceptions.
    const fatals = errors.filter((e) => /TypeError|ReferenceError/i.test(e));
    assert(fatals.length === 0, `no fatal errors: ${fatals.join("\n")}`);
  });

  await test("missing about dialog doesn't break the list render", async () => {
    const stripped = HTML.replace(/<dialog id="aboutDialog"[\s\S]*?<\/dialog>\s*/, "");
    const { dom, errors } = await mount({ data: sample, htmlOverride: stripped });
    const list = dom.window.document.getElementById("list");
    assertEqual(list.children.length, sample.shows.length, "list still renders");
    const fatals = errors.filter((e) => /TypeError|ReferenceError/i.test(e));
    assert(fatals.length === 0, `no fatal errors: ${fatals.join("\n")}`);
  });

  await test("malformed shows.json (no shows key) renders empty state", async () => {
    const { dom } = await mount({ data: { updated: "2026-04-29" } });
    const list = dom.window.document.getElementById("list");
    assertEqual(list.children.length, 0, "no rows when shows is absent");
  });

  // ---------------------------------------------------------------------------
  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) {
    console.log("\nFailures:");
    failures.forEach((f) => {
      console.log(` - ${f.name}`);
      console.log(`   ${f.error.stack || f.error.message || f.error}`);
    });
    process.exit(1);
  }
}

run().catch((e) => {
  console.error("Test runner crashed:", e);
  process.exit(1);
});

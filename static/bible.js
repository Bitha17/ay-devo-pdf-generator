// Tap a verse reference -> show the passage text in a bottom sheet, with a
// reader-chosen version (TB default). Source: sonnylab GraphQL (single ACAO
// header), called from the browser directly so it works on PythonAnywhere free.
//
// getChapter() is the single indirection point: to add a provider for a version
// it doesn't carry (e.g. BIS/TSI via a proxy), route inside getChapter().
(function () {
  "use strict";

  var API = "https://bible.sonnylab.com/";  // GraphQL, single ACAO header (browser-safe)

  // Versions offered in the switcher (value = sonnylab enum, label = chip text).
  var VERSIONS = [
    { v: "tb", label: "TB", full: "Alkitab Terjemahan Baru (TB)" },
    { v: "niv", label: "NIV", full: "New International Version (NIV)" },
    { v: "av", label: "KJV", full: "King James Version (KJV)" }
  ];
  function isVersion(v) { return VERSIONS.some(function (x) { return x.v === v; }); }
  function versionFull() {
    for (var i = 0; i < VERSIONS.length; i++) {
      if (VERSIONS[i].v === curVer) return VERSIONS[i].full;
    }
    return curVer;
  }
  var curVer = "tb";
  try { var s = localStorage.getItem("bibleVersion"); if (isVersion(s)) curVer = s; } catch (e) {}

  // sonnylab accepts full Indonesian names for most books, but numbered and a
  // couple of multi-word books need a SABDA-style token. Only the exceptions are
  // mapped; everything else passes through by name.
  var BOOK_TOKEN = {
    "1 samuel": "1Sam", "2 samuel": "2Sam", "1 raja-raja": "1Raj",
    "2 raja-raja": "2Raj", "1 tawarikh": "1Taw", "2 tawarikh": "2Taw",
    "kidung agung": "Kid", "kisah para rasul": "Kis", "kisah rasul": "Kis",
    "1 korintus": "1Kor", "2 korintus": "2Kor", "1 tesalonika": "1Tes",
    "2 tesalonika": "2Tes", "1 timotius": "1Tim", "2 timotius": "2Tim",
    "1 petrus": "1Ptr", "2 petrus": "2Ptr", "1 yohanes": "1Yoh",
    "2 yohanes": "2Yoh", "3 yohanes": "3Yoh"
  };

  function bookToken(name) {
    var key = name.toLowerCase().replace(/\s+/g, " ").trim();
    return BOOK_TOKEN[key] || name.trim();
  }

  // A verse spec like "21-28", "3,5,7", "1-2,5" -> [21,22,...] / [3,5,7].
  // Partial-verse letters ("14a", "14b") are stripped so we show the FULL verse.
  function parseVerseSpec(spec) {
    var wanted = [];
    spec.split(",").forEach(function (part) {
      part = part.replace(/\s+/g, "");
      var m = part.match(/^(\d+)[a-d]?(?:[-–](\d+)[a-d]?)?$/i);
      if (!m) return;
      var a = parseInt(m[1], 10), b = m[2] ? parseInt(m[2], 10) : a;
      for (var i = a; i <= b; i++) wanted.push(i);
    });
    return wanted;
  }

  // Parse one or many passages from a reference string. Handles separators
  // ";", "&", " dan ", and "," that introduces a new book, plus verse lists
  // and ranges. e.g. "Yunus 1:1-2; Keluaran 3:10-12", "Matius 5:3,5,7".
  function parseRefs(raw) {
    raw = raw.replace(/\s*&\s*/g, ";").replace(/\s+dan\s+/gi, ";");
    var refs = [];
    raw.split(/[;]+/).forEach(function (seg) {
      // Split on commas that start a new reference (comma + a letter),
      // keeping verse-list commas (comma + a digit) intact.
      seg.split(/,(?=\s*[A-Za-z])/).forEach(function (piece) {
        piece = piece.trim();
        if (!piece) return;
        var m = piece.match(/^(.+?)\s+(\d+):([0-9a-dA-D,\s–-]+)$/);
        if (!m) return;
        var wanted = parseVerseSpec(m[3]);
        if (!wanted.length) return;
        refs.push({
          label: piece,
          book: m[1].trim(),
          chapter: parseInt(m[2], 10),
          verses: wanted
        });
      });
    });
    return refs;
  }

  // Cache whole chapters. The Bible text never changes, so a fetched chapter is
  // reused for the rest of the session (in-memory) and across visits
  // (localStorage). Verse ranges within the same chapter share one fetch.
  var mem = {};
  // Cache key includes the version, so each version is cached separately.
  function chapterKey(tok, ch) { return "bible1:" + curVer + ":" + tok + ":" + ch; }

  function getChapter(tok, chapter) {
    var key = chapterKey(tok, chapter);
    if (mem[key]) return Promise.resolve(mem[key]);
    try {
      var stored = localStorage.getItem(key);
      if (stored) { mem[key] = JSON.parse(stored); return Promise.resolve(mem[key]); }
    } catch (e) { /* localStorage unavailable */ }

    var query = '{passages(version: ' + curVer + ', book: "' + tok +
      '", chapter: ' + chapter + "){verses{verse type content}}}";
    return fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query })
    }).then(function (r) {
      if (!r.ok) throw new Error("http " + r.status);
      return r.json();
    }).then(function (d) {
      var verses = (d.data && d.data.passages && d.data.passages.verses) || [];
      // Don't cache a "book not found" response (only a verse-0 copyright row).
      if (!verses.some(function (v) { return v.verse > 0; })) throw new Error("not found");
      mem[key] = verses;
      try { localStorage.setItem(key, JSON.stringify(verses)); } catch (e) { /* quota */ }
      return verses;
    });
  }

  function fetchPassage(ref) {
    var want = {};
    ref.verses.forEach(function (n) { want[n] = true; });
    return getChapter(bookToken(ref.book), ref.chapter).then(function (verses) {
      return verses.filter(function (v) {
        return v.type === "content" && want[v.verse];
      });
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var sheet = document.getElementById("verseSheet");
  if (!sheet) return;
  var titleEl = document.getElementById("verseTitle");
  var bodyEl = document.getElementById("verseBody");
  var versionSel = document.getElementById("verseVersion");
  var currentRaw = null;  // the reference currently shown, for re-render on version change

  if (versionSel) {
    versionSel.innerHTML = VERSIONS.map(function (x) {
      return '<option value="' + x.v + '">' + x.label + "</option>";
    }).join("");
    versionSel.value = curVer;
    versionSel.addEventListener("change", function () {
      if (!isVersion(this.value)) return;
      curVer = this.value;
      try { localStorage.setItem("bibleVersion", curVer); } catch (e) {}
      if (currentRaw) showVerses(currentRaw);  // reload open passages in the new version
    });
  }

  function openSheet() { sheet.hidden = false; document.body.classList.add("sheet-open"); }
  function closeSheet() { sheet.hidden = true; document.body.classList.remove("sheet-open"); }

  function renderSlot(slot, verses) {
    var html = '<p class="verstext">';
    verses.forEach(function (v) {
      // Strip TB's leading "(18-7)" Psalm dual-numbering marker.
      var text = v.content.replace(/^\(\d+-\d+\)\s*/, "");
      html += "<sup>" + v.verse + "</sup> " + esc(text) + " ";
    });
    slot.innerHTML = html + "</p>";
  }

  // Load one passage into its slot, retrying transient failures with backoff.
  var MAX_TRIES = 4;
  function loadSlot(slot, ref, attempt) {
    fetchPassage(ref).then(function (verses) {
      if (!verses.length) throw new Error("empty");
      renderSlot(slot, verses);  // shown as soon as THIS passage is ready
    }).catch(function () {
      if (attempt + 1 < MAX_TRIES) {
        slot.innerHTML =
          '<div class="versloading"><span class="spinner"></span> Mencoba lagi…</div>';
        setTimeout(function () { loadSlot(slot, ref, attempt + 1); }, 600 * (attempt + 1));
      } else {
        slot.innerHTML =
          '<p class="verserr">Tidak dapat memuat ayat ini. ' +
          '<button type="button" class="versretry">Coba lagi</button></p>';
        slot.querySelector(".versretry").addEventListener("click", function () {
          slot.innerHTML =
            '<div class="versloading"><span class="spinner"></span> Memuat ayat…</div>';
          loadSlot(slot, ref, 0);
        });
      }
    });
  }

  function showVerses(rawRef) {
    openSheet();
    currentRaw = rawRef;
    titleEl.textContent = rawRef;
    var refs = parseRefs(rawRef);
    if (!refs.length) {
      bodyEl.innerHTML = '<p class="verserr">Referensi tidak dikenali.</p>';
      return;
    }
    // One independent block per passage; each renders the moment it loads.
    bodyEl.innerHTML = "";
    refs.forEach(function (ref, i) {
      var block = document.createElement("div");
      block.className = "versblock";
      block.innerHTML =
        '<h4 class="versref">' + esc(ref.label) + "</h4>" +
        '<div class="versslot"><div class="versloading">' +
        '<span class="spinner"></span> Memuat ayat…</div></div>';
      bodyEl.appendChild(block);
      var slot = block.querySelector(".versslot");
      // Stagger the initial requests a little to ease load on the API.
      setTimeout(function () { loadSlot(slot, ref, 0); }, i * 150);
    });
    var foot = document.createElement("p");
    foot.className = "versver";
    foot.textContent = versionFull();
    bodyEl.appendChild(foot);
  }

  // Open on tapping any verse reference; close via backdrop / close button / Esc.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".versebtn");
    if (btn) { showVerses(btn.dataset.ref); return; }
    if (e.target.closest("[data-close]")) closeSheet();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !sheet.hidden) closeSheet();
  });

  // Warm the cache for the current day's verses so the first tap is instant.
  setTimeout(function () {
    var active = document.querySelector(".day.active .versebtn") ||
                 document.querySelector(".versebtn");
    if (!active) return;
    parseRefs(active.dataset.ref).forEach(function (ref) {
      getChapter(bookToken(ref.book), ref.chapter).catch(function () {});
    });
  }, 800);
})();

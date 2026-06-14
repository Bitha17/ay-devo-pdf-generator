// Tap a verse reference -> show the Indonesian (TB) text in a bottom sheet.
// Source: Prayer Pulse API (CORS-enabled, no key). Called from the browser
// directly so it works on PythonAnywhere free (no server-side outbound needed).
//
// fetchPassage() is the single indirection point: to switch providers later
// (e.g. a same-origin proxy on a paid host), change only this function.
(function () {
  "use strict";

  var API = "https://bible.sonnylab.com/";  // GraphQL, single ACAO header (browser-safe)

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

  // A verse spec like "21-28", "3,5,7" or "1-2,5" -> [21,22,...] / [3,5,7].
  function parseVerseSpec(spec) {
    var wanted = [];
    spec.split(",").forEach(function (part) {
      part = part.replace(/\s+/g, "");
      var m = part.match(/^(\d+)(?:[-–](\d+))?$/);
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
        var m = piece.match(/^(.+?)\s+(\d+):([\d,\-–\s]+)$/);
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
  function chapterKey(tok, ch) { return "bibletb1:" + tok + ":" + ch; }

  function getChapter(tok, chapter) {
    var key = chapterKey(tok, chapter);
    if (mem[key]) return Promise.resolve(mem[key]);
    try {
      var stored = localStorage.getItem(key);
      if (stored) { mem[key] = JSON.parse(stored); return Promise.resolve(mem[key]); }
    } catch (e) { /* localStorage unavailable */ }

    var query = '{passages(version: tb, book: "' + tok +
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

  function openSheet() { sheet.hidden = false; document.body.classList.add("sheet-open"); }
  function closeSheet() { sheet.hidden = true; document.body.classList.remove("sheet-open"); }

  function showVerses(rawRef) {
    openSheet();
    titleEl.textContent = rawRef;
    bodyEl.innerHTML =
      '<div class="versloading"><span class="spinner"></span> Memuat ayat…</div>';

    var refs = parseRefs(rawRef);
    if (!refs.length) {
      bodyEl.innerHTML = '<p class="verserr">Referensi tidak dikenali.</p>';
      return;
    }
    Promise.all(refs.map(function (ref) {
      return fetchPassage(ref)
        .then(function (vs) { return { ref: ref, verses: vs }; })
        .catch(function () { return { ref: ref, error: true }; });
    })).then(function (results) {
      var html = "";
      results.forEach(function (res) {
        html += '<h4 class="versref">' + esc(res.ref.label) + "</h4>";
        if (res.error || !res.verses.length) {
          html += '<p class="verserr">Tidak dapat memuat ayat ini. ' +
            'Periksa koneksi atau coba lagi.</p>';
        } else {
          html += '<p class="verstext">';
          res.verses.forEach(function (v) {
            // Strip TB's leading "(18-7)" Psalm dual-numbering marker.
            var text = v.content.replace(/^\(\d+-\d+\)\s*/, "");
            html += "<sup>" + v.verse + "</sup> " + esc(text) + " ";
          });
          html += "</p>";
        }
      });
      html += '<p class="versver">Alkitab Terjemahan Baru (TB)</p>';
      bodyEl.innerHTML = html;
    });
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

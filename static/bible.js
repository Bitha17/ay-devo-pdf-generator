// Tap a verse reference -> show the Indonesian (TB) text in a bottom sheet.
// Source: Prayer Pulse API (CORS-enabled, no key). Called from the browser
// directly so it works on PythonAnywhere free (no server-side outbound needed).
//
// fetchPassage() is the single indirection point: to switch providers later
// (e.g. a same-origin proxy on a paid host), change only this function.
(function () {
  "use strict";

  var API = "https://api.prayerpulse.io/bible/get-chapter/TB/";

  // Indonesian book name -> canonical book number (1-66). Prayer Pulse resolves
  // single-word names but not numbered/multi-word ones, so we map to numbers.
  var BOOKS = {
    "kejadian": 1, "keluaran": 2, "imamat": 3, "bilangan": 4, "ulangan": 5,
    "yosua": 6, "hakim-hakim": 7, "hakim hakim": 7, "rut": 8,
    "1 samuel": 9, "2 samuel": 10, "1 raja-raja": 11, "2 raja-raja": 12,
    "1 tawarikh": 13, "2 tawarikh": 14, "ezra": 15, "nehemia": 16, "ester": 17,
    "ayub": 18, "mazmur": 19, "amsal": 20, "pengkhotbah": 21, "kidung agung": 22,
    "yesaya": 23, "yeremia": 24, "ratapan": 25, "yehezkiel": 26, "daniel": 27,
    "hosea": 28, "yoel": 29, "amos": 30, "obaja": 31, "yunus": 32, "mikha": 33,
    "nahum": 34, "habakuk": 35, "zefanya": 36, "hagai": 37, "zakharia": 38,
    "maleakhi": 39, "matius": 40, "markus": 41, "lukas": 42, "yohanes": 43,
    "kisah para rasul": 44, "kisah rasul": 44, "roma": 45, "1 korintus": 46,
    "2 korintus": 47, "galatia": 48, "efesus": 49, "filipi": 50, "kolose": 51,
    "1 tesalonika": 52, "2 tesalonika": 53, "1 timotius": 54, "2 timotius": 55,
    "titus": 56, "filemon": 57, "ibrani": 58, "yakobus": 59, "1 petrus": 60,
    "2 petrus": 61, "1 yohanes": 62, "2 yohanes": 63, "3 yohanes": 64,
    "yudas": 65, "wahyu": 66
  };

  function bookToken(name) {
    var key = name.toLowerCase().replace(/\s+/g, " ").trim();
    return BOOKS[key] || encodeURIComponent(name.trim());  // fall back to the name
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

  function fetchPassage(ref) {
    var url = API + bookToken(ref.book) + "/" + ref.chapter + "/";
    var want = {};
    ref.verses.forEach(function (n) { want[n] = true; });
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("http " + r.status);
      return r.json();
    }).then(function (verses) {
      return verses.filter(function (v) { return want[v.verse]; });
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
            html += "<sup>" + v.verse + "</sup> " + esc(v.text) + " ";
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
})();

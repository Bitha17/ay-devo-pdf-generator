// Writer-facing verse picker: Book -> Chapter -> tick the actual verses (with
// their text shown, fetched live) instead of typing a free-text reference.
// A picker can hold multiple passage rows ("+ Add another passage"), each its
// own book/chapter/verses, so a reference can span multiple chapters and/or
// books (e.g. "Mazmur 96:1-9; Yohanes 3:16"). Each `.versepicker[data-target]`
// fills the hidden input #<target> with the built, semicolon-joined string —
// the same multi-passage format bible.js already reads for the reader view.
(function () {
  "use strict";
  if (!window.BIBLE_BOOKS) return;

  var API = "https://bible.sonnylab.com/";
  var VERSION = "tb";

  var BOOK_TOKEN = {
    "1 samuel": "1Sam", "2 samuel": "2Sam", "1 raja-raja": "1Raj",
    "2 raja-raja": "2Raj", "1 tawarikh": "1Taw", "2 tawarikh": "2Taw",
    "kidung agung": "Kid", "kisah para rasul": "Kis",
    "1 korintus": "1Kor", "2 korintus": "2Kor", "1 tesalonika": "1Tes",
    "2 tesalonika": "2Tes", "1 timotius": "1Tim", "2 timotius": "2Tim",
    "1 petrus": "1Ptr", "2 petrus": "2Ptr", "1 yohanes": "1Yoh",
    "2 yohanes": "2Yoh", "3 yohanes": "3Yoh"
  };
  function bookToken(name) {
    var key = name.toLowerCase().replace(/\s+/g, " ").trim();
    return BOOK_TOKEN[key] || name.trim();
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // "1,2,3,5,7,8,9" (as ints) -> "1-3,5,7-9"
  function compressRanges(nums) {
    nums = nums.slice().sort(function (a, b) { return a - b; });
    var parts = [], start = null, prev = null;
    nums.forEach(function (n) {
      if (start === null) { start = n; prev = n; return; }
      if (n === prev + 1) { prev = n; return; }
      parts.push(start === prev ? "" + start : start + "-" + prev);
      start = n; prev = n;
    });
    if (start !== null) parts.push(start === prev ? "" + start : start + "-" + prev);
    return parts.join(",");
  }

  // Reverse of the above, for prefilling from an existing "1-3,5,7-9" string.
  function expandRanges(spec) {
    var out = [];
    (spec || "").split(",").forEach(function (part) {
      var m = part.trim().match(/^(\d+)(?:-(\d+))?$/);
      if (!m) return;
      var a = parseInt(m[1], 10), b = m[2] ? parseInt(m[2], 10) : a;
      for (var i = a; i <= b; i++) out.push(i);
    });
    return out;
  }

  // "Mazmur 96:1-9" -> {book, chapter, verseSpec} or null.
  function parseRef(raw) {
    var m = String(raw || "").trim().match(/^(.+?)\s+(\d+):([0-9,\s–-]+)$/);
    if (!m) return null;
    return { book: m[1].trim(), chapter: parseInt(m[2], 10), verseSpec: m[3].replace(/–/g, "-") };
  }

  // "Mazmur 96:1-9; Yohanes 3:16" -> [{book,chapter,verseSpec}, ...]
  function parseMultiRef(raw) {
    return String(raw || "").split(/;+/).map(function (seg) { return parseRef(seg); }).filter(Boolean);
  }

  var chapterCache = {};
  function fetchChapter(book, chapter) {
    var key = VERSION + ":" + book + ":" + chapter;
    if (chapterCache[key]) return chapterCache[key];
    var query = '{passages(version: ' + VERSION + ', book: "' + bookToken(book) +
      '", chapter: ' + chapter + "){verses{verse type content}}}";
    chapterCache[key] = fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query }),
    }).then(function (r) { return r.json(); }).then(function (d) {
      return ((d.data && d.data.passages && d.data.passages.verses) || [])
        .filter(function (v) { return v.type === "content"; });
    });
    return chapterCache[key];
  }

  // One book+chapter+verses row. `onChange` fires whenever this row's own
  // passage string might have changed, so the picker can rebuild the target.
  function makePassageRow(onChange, onRemove) {
    var bookSel = document.createElement("select");
    bookSel.className = "vp-book";
    bookSel.innerHTML = '<option value="">Pilih kitab…</option>' +
      window.BIBLE_BOOKS.map(function (b) {
        return '<option value="' + esc(b[0]) + '" data-chapters="' + b[1] + '">' + esc(b[0]) + "</option>";
      }).join("");

    var chapSel = document.createElement("select");
    chapSel.className = "vp-chapter";
    chapSel.disabled = true;
    chapSel.innerHTML = '<option value="">Pasal…</option>';

    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "danger vp-remove-passage";
    removeBtn.textContent = "✕";
    removeBtn.title = "Hapus bagian ayat ini";

    var topRow = document.createElement("div");
    topRow.className = "vp-row";
    topRow.appendChild(bookSel);
    topRow.appendChild(chapSel);
    topRow.appendChild(removeBtn);

    var versesBox = document.createElement("div");
    versesBox.className = "vp-verses";
    versesBox.hidden = true;

    var el = document.createElement("div");
    el.className = "vp-passage";
    el.appendChild(topRow);
    el.appendChild(versesBox);

    function passageString() {
      var checked = Array.prototype.slice.call(versesBox.querySelectorAll("input:checked"))
        .map(function (cb) { return parseInt(cb.value, 10); });
      if (!checked.length || !bookSel.value || !chapSel.value) return null;
      return bookSel.value + " " + chapSel.value + ":" + compressRanges(checked);
    }

    function renderVerseList(verses, checkedSet) {
      versesBox.hidden = false;
      versesBox.innerHTML = "";
      verses.forEach(function (v) {
        var label = document.createElement("label");
        label.className = "vp-verse-item";
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = v.verse;
        if (checkedSet && checkedSet[v.verse]) cb.checked = true;
        cb.addEventListener("change", onChange);
        label.appendChild(cb);
        var span = document.createElement("span");
        span.innerHTML = "<sup>" + v.verse + "</sup> " + esc(v.content.replace(/^\(\d+-\d+\)\s*/, ""));
        label.appendChild(span);
        versesBox.appendChild(label);
      });
    }

    function loadChapter(checkedSet) {
      versesBox.hidden = false;
      versesBox.innerHTML = '<div class="versloading"><span class="spinner"></span> Memuat ayat…</div>';
      fetchChapter(bookSel.value, parseInt(chapSel.value, 10)).then(function (verses) {
        renderVerseList(verses, checkedSet);
        if (checkedSet) onChange();
      }).catch(function () {
        versesBox.innerHTML = '<p class="verserr">Tidak dapat memuat ayat ini.</p>';
      });
    }

    bookSel.addEventListener("change", function () {
      var opt = bookSel.selectedOptions[0];
      var n = opt ? parseInt(opt.dataset.chapters || "0", 10) : 0;
      var opts = ['<option value="">Pasal…</option>'];
      for (var i = 1; i <= n; i++) opts.push('<option value="' + i + '">' + i + "</option>");
      chapSel.innerHTML = opts.join("");
      chapSel.disabled = !n;
      versesBox.hidden = true;
      versesBox.innerHTML = "";
      onChange();
    });

    chapSel.addEventListener("change", function () {
      if (!chapSel.value) { versesBox.hidden = true; versesBox.innerHTML = ""; onChange(); return; }
      loadChapter(null);
    });

    removeBtn.addEventListener("click", function () { onRemove(row); });

    var row = {
      el: el,
      passageString: passageString,
      prefill: function (book, chapter, verseSpec) {
        var bookOpt = Array.prototype.find.call(bookSel.options, function (o) { return o.value === book; });
        if (!bookOpt) return;
        bookSel.value = book;
        bookSel.dispatchEvent(new Event("change"));
        chapSel.value = String(chapter);
        if (chapSel.value !== String(chapter)) return;
        var checkedSet = {};
        expandRanges(verseSpec).forEach(function (n) { checkedSet[n] = true; });
        loadChapter(checkedSet);
      },
    };
    return row;
  }

  function initPicker(root) {
    var targetId = root.dataset.target;
    var target = document.getElementById(targetId);
    if (!target) return;

    var rowsBox = document.createElement("div");
    var addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn vp-add-passage";
    addBtn.textContent = "+ Tambah bagian ayat lain";
    var current = document.createElement("div");
    current.className = "vp-current sub";

    root.appendChild(rowsBox);
    root.appendChild(addBtn);
    root.appendChild(current);

    var rows = [];

    function rebuildTarget() {
      var parts = rows.map(function (r) { return r.passageString(); }).filter(Boolean);
      target.value = parts.join("; ");
      current.textContent = target.value ? "Dipilih: " + target.value : "Belum ada ayat dipilih.";
    }

    function removeRow(row) {
      rows = rows.filter(function (r) { return r !== row; });
      row.el.remove();
      rebuildTarget();
    }

    function addRow(prefill) {
      var row = makePassageRow(rebuildTarget, removeRow);
      rows.push(row);
      rowsBox.appendChild(row.el);
      if (prefill) row.prefill(prefill.book, prefill.chapter, prefill.verseSpec);
      return row;
    }

    addBtn.addEventListener("click", function () { addRow(); });

    // Prefill from an existing (possibly multi-passage) reference.
    var existing = parseMultiRef(target.value);
    if (existing.length) {
      existing.forEach(function (p) { addRow(p); });
    } else {
      addRow();
    }
    rebuildTarget();
  }

  window.initVersePicker = initPicker;

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".versepicker").forEach(initPicker);
  });
})();

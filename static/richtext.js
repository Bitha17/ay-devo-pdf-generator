// Turns a plain <textarea class="richtext"> into one with Bold/Italic
// buttons above it, so writers never have to type <b>/<i> tags by hand.
// The buttons just wrap the current selection with those tags (the same
// convention the `markup` filter and PDF renderer already understand) —
// toggling them off again if the selection is already wrapped.
(function () {
  "use strict";

  function wrapSelection(ta, tag) {
    var start = ta.selectionStart, end = ta.selectionEnd;
    var value = ta.value;
    var selected = value.slice(start, end);
    var openTag = "<" + tag + ">", closeTag = "</" + tag + ">";

    var before = value.slice(0, start), after = value.slice(end);
    var alreadyWrapped = before.endsWith(openTag) && after.startsWith(closeTag);

    var newValue, newStart, newEnd;
    if (alreadyWrapped) {
      newValue = before.slice(0, -openTag.length) + selected + after.slice(closeTag.length);
      newStart = start - openTag.length;
      newEnd = end - openTag.length;
    } else {
      newValue = before + openTag + selected + closeTag + after;
      newStart = start + openTag.length;
      newEnd = end + openTag.length;
    }
    ta.value = newValue;
    ta.focus();
    ta.setSelectionRange(newStart, newEnd);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function attach(ta) {
    if (ta.dataset.richtextReady) return;
    ta.dataset.richtextReady = "1";

    var bar = document.createElement("div");
    bar.className = "richtoolbar";

    [["B", "b", "Bold"], ["I", "i", "Italic"]].forEach(function (spec) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "richbtn richbtn-" + spec[1];
      btn.textContent = spec[0];
      btn.title = spec[2] + " — select text first";
      btn.addEventListener("click", function () { wrapSelection(ta, spec[1]); });
      bar.appendChild(btn);
    });

    ta.parentNode.insertBefore(bar, ta);
  }

  window.attachRichText = attach;

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("textarea.richtext").forEach(attach);
  });
})();

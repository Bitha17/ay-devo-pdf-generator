// Clear "in progress" cue for admin actions. When a form is submitted we show a
// blocking overlay (so the admin knows it started and can't double-submit). The
// "completed" cue is the flash message rendered on the page we redirect to.
(function () {
  var overlay = document.createElement("div");
  overlay.className = "busy-overlay";
  overlay.hidden = true;
  overlay.innerHTML =
    '<div class="busy-box"><span class="spinner"></span>' +
    '<span class="busy-msg">Memproses…</span></div>';
  document.body.appendChild(overlay);

  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (e.defaultPrevented) return;  // a cancelled confirm() etc.
      var btn = e.submitter;
      if (btn && btn.dataset.busy) {
        overlay.querySelector(".busy-msg").textContent = btn.dataset.busy;
      }
      overlay.hidden = false;
    });
  });
})();

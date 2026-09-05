// Client-side file preview for the admin forms.
// Any <input type="file" data-preview="targetId" data-preview-type="image|text">
// renders into the element with that id when a file is chosen.
(function () {
  function wire(input) {
    var target = document.getElementById(input.dataset.preview);
    if (!target) return;
    var isImage = input.dataset.previewType === "image";
    input.addEventListener("change", function () {
      var file = this.files[0];
      if (!file) {
        target.style.display = "none";
        return;
      }
      if (isImage) {
        target.src = URL.createObjectURL(file);
        target.style.display = "block";
      } else if (/\.docx$/i.test(file.name)) {
        target.style.display = "none";  // binary — nothing useful to preview as text
      } else {
        var reader = new FileReader();
        reader.onload = function (e) {
          target.textContent = e.target.result;
          target.style.display = "block";
        };
        reader.readAsText(file);
      }
    });
  }
  document.querySelectorAll('input[type="file"][data-preview]').forEach(wire);
})();

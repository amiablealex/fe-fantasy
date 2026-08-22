/* Modal dialogs and the delegated handlers that open them.

   Lifted out of the styleguide's meeting page, which was the only screen that
   needed it until the friend profile arrived. A second inline copy is how two
   implementations of the same three lines start disagreeing, so it lives in
   one file that both load.

   Handlers are delegated from the document rather than bound per element, so
   markup swapped in by HTMX behaves like markup that was there at load
   (SPEC.md §11). */
(function () {
  // A <dialog> with the `open` attribute renders inline: no backdrop, no focus
  // trap, no escape-to-close. showModal() is what makes it a modal.
  function openAll(root) {
    (root || document).querySelectorAll('dialog[data-modal]').forEach(function (d) {
      if (!d.open) d.showModal();
    });
  }
  openAll(document);

  document.body.addEventListener('htmx:afterSwap', function (event) {
    openAll(event.target);
  });

  document.addEventListener('click', function (event) {
    var slot = event.target.closest('.slot[data-opens]');
    if (slot) {
      var panel = document.getElementById(slot.dataset.opens);
      if (panel && !panel.open) panel.showModal();
      return;
    }

    var closer = event.target.closest('[data-closes]');
    if (closer) {
      var dialog = closer.closest('dialog');
      if (dialog) {
        // Only intercept when the dialog is a live modal; otherwise let the
        // link navigate, which is the no-JavaScript path.
        event.preventDefault();
        dialog.close();
        var host = document.getElementById('profile-host');
        if (host && host.contains(dialog)) host.innerHTML = '';
      }
      return;
    }

    if (event.target.tagName === 'DIALOG') {
      event.target.close();
      var h = document.getElementById('profile-host');
      if (h && h.contains(event.target)) h.innerHTML = '';
    }
  });
})();

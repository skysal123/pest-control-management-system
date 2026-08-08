// OneStep MultiServices - small interactive helpers
document.addEventListener('DOMContentLoaded', function () {
  // Auto-dismiss alerts after 5s
  setTimeout(() => {
    document.querySelectorAll('.alert-dismissible.fade.show').forEach(el => {
      try { bootstrap.Alert.getOrCreateInstance(el).close(); } catch (e) {}
    });
  }, 5000);

  // Confirm dangerous actions
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => {
      if (!confirm(el.dataset.confirm)) e.preventDefault();
    });
  });
});

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

  // Scroll reveal - cards slide in from the sides as they enter the viewport
  try {
    initScrollReveal();
  } catch (e) {
    document.documentElement.classList.remove('js');
  }
});

function initScrollReveal() {
  const items = document.querySelectorAll('[data-reveal]');
  if (!items.length) return;

  const revealAll = () => items.forEach(el => el.classList.add('is-visible'));
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (reduced || !('IntersectionObserver' in window)) {
    revealAll();
    return;
  }

  const io = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('is-visible');
      io.unobserve(entry.target);
    });
  }, { threshold: 0.2, rootMargin: '0px 0px -8% 0px' });

  items.forEach(el => io.observe(el));
}

// SmartPark — shared JS helpers (loaded on every page)
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.dismiss');
  if (btn) btn.closest('.flash')?.remove();
});

// Elapsed timer — used on pages that don't load parking3d.js
(function () {
  function updateElapsed() {
    document.querySelectorAll('[data-entry]').forEach((el) => {
      const entered = new Date(el.dataset.entry);
      if (isNaN(entered.getTime())) return;
      const mins = Math.max(0, Math.floor((Date.now() - entered.getTime()) / 60000));
      const h = Math.floor(mins / 60), m = mins % 60;
      el.textContent = `Elapsed ${h}h ${m}m`;
    });
  }
  updateElapsed();
  setInterval(updateElapsed, 30000);
})();

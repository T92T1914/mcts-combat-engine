/* This runs before styles paint. HTML supplies the no-script Obscur default. */
(function () {
  'use strict';
  const key = 'mcts-combat-engine.appearance.v1';
  const root = document.documentElement;
  let preference = ['auto', 'clair', 'obscur'].includes(root.dataset.appearance)
    ? root.dataset.appearance : 'obscur';
  try {
    const saved = localStorage.getItem(key);
    if (['auto', 'clair', 'obscur'].includes(saved)) preference = saved;
  } catch (_) { /* A blocked store leaves a working in-memory preference. */ }
  root.dataset.appearance = preference;
  document.addEventListener('DOMContentLoaded', () => {
    const control = document.getElementById('appearance');
    if (!control) return;
    control.value = preference;
    control.disabled = false;
    control.addEventListener('change', () => {
      preference = ['clair', 'obscur'].includes(control.value) ? control.value : 'auto';
      root.dataset.appearance = preference;
      try {
        localStorage.setItem(key, preference);
      } catch (_) { /* Switching remains usable when persistence is unavailable. */ }
    });
  });
})();

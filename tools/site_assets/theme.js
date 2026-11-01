(() => {
  'use strict';
  try {
    const theme = localStorage.getItem('spec-kitty-theme');
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  } catch (_) { /* Storage can be disabled; CSS still follows the system theme. */ }
  window.notifyThemeChange = () => document.dispatchEvent(new Event('themechange'));
})();

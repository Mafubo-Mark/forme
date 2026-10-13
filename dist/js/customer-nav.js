(() => {
  'use strict';
  const link = document.querySelector('.site-header .nav-action');
  if (!link) return;
  fetch('/api/customer/session', { credentials: 'same-origin', cache: 'no-store' })
    .then(async response => {
      if (!response.ok) return;
      const { user } = await response.json();
      if (!user?.username) return;
      const name = document.createElement('span');
      name.className = 'nav-user-name';
      name.dataset.i18nSkip = 'true';
      name.textContent = user.username;
      const arrow = document.createElement('span');
      arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = '↗';
      link.replaceChildren(name, arrow);
      link.href = 'account.html';
      link.title = user.username;
    })
    .catch(() => { /* Keep the sign-in link when the service is unavailable. */ });
})();

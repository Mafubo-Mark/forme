(() => {
  'use strict';
  const page = document.body.dataset.page;
  const $ = selector => document.querySelector(selector);
  const t = (en, zh) => window.FormeI18n?.locale === 'zh-Hant' ? zh : en;
  const api = async (path, options = {}) => {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail?.code || `HTTP ${response.status}`);
    return data;
  };
  $('.menu-toggle')?.addEventListener('click', event => {
    const open = $('.nav-links').classList.toggle('open');
    event.currentTarget.setAttribute('aria-expanded', String(open));
  });
  if (page === 'login') {
    $('#login-form').addEventListener('submit', async event => {
      event.preventDefault();
      const error = $('#login-error');
      error.hidden = true;
      try {
        await api('/api/customer/login', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_key: $('#access-key').value.trim() })
        });
        const next = new URLSearchParams(location.search).get('next');
        location.assign(next && /^[a-z-]+\.html$/.test(next) ? next : 'create.html');
      } catch (failure) {
        error.textContent = failure.message === 'INVALID_ACCESS_KEY'
          ? t('The access key is incorrect.', '密鑰不正確。')
          : t('Sign in is unavailable. Please try again later.', '目前無法登入，請稍後再試。');
        error.hidden = false;
      }
    });
  }
  if (page === 'account') {
    const host = $('#account-content');
    api('/api/customer/session').then(async () => {
      const submissions = await api('/api/customer/submissions');
      host.replaceChildren();
      const card = document.createElement('div');
      card.className = 'account-card';
      const title = document.createElement('h2');
      title.textContent = t('Your Forme access', '你的 Forme 帳戶');
      const count = document.createElement('p');
      count.textContent = t(`${submissions.items.length} submitted designs`, `已提交 ${submissions.items.length} 個設計`);
      const link = document.createElement('a');
      link.href = 'prosthetic.html';
      link.textContent = t('View your submissions', '查看已提交設計');
      const signOut = document.createElement('button');
      signOut.type = 'button';
      signOut.textContent = t('Sign out', '登出');
      signOut.addEventListener('click', async () => { await api('/api/customer/logout', { method: 'POST' }); location.assign('index.html'); });
      card.append(title, count, link, signOut);
      host.append(card);
    }).catch(() => {
      host.innerHTML = `<div class="empty-state"><h2>${t('Sign in to continue', '請先登入')}</h2><a class="button button-dark" href="login.html?next=account.html">${t('Sign in', '登入')}</a></div>`;
    });
  }
  if (page === 'order' || page === 'delivery') {
    const host = page === 'order' ? $('#order-list') : $('#delivery-list');
    host.innerHTML = `<div class="empty-state"><h2>${t('Coming soon', '即將推出')}</h2><p>${t('Orders and delivery tracking will appear here once those services are available.', '訂單和配送追蹤服務開通後會顯示在這裡。')}</p><a class="button button-dark" href="prosthetic.html">${t('View your submissions', '查看已提交設計')}</a></div>`;
  }
  if (page === 'checkout') {
    $('.checkout-grid').innerHTML = `<div class="empty-state"><h2>${t('Ordering is not available yet', '目前尚未開放下單')}</h2><p>${t('We will notify you when your cover has been reviewed and ordering opens.', '保護套完成審核並開放下單後，我們會通知你。')}</p><a class="button button-dark" href="prosthetic.html">${t('View your submissions', '查看已提交設計')}</a></div>`;
  }
})();

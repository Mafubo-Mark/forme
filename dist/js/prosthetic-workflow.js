(() => {
  'use strict';
  const host = document.querySelector('#design-list');
  const t = (en, zh) => window.FormeI18n?.locale === 'zh-Hant' ? zh : en;
  const styles = { '01': ['Auspicious Cloud', '祥云'], '02': ['Honeycomb', '蜂巢'], '03': ['Streamline', '流线'],
    '04': ['Bamboo Shadow', '竹影'], '05': ['Scale Feather', '鳞羽'], '06': ['Ventilated', '通风'],
    '05-magnetic': ['Scale Feather Magnetic', '鳞羽内嵌磁吸'] };
  const labels = {
    uploaded: ['Received', '已收到'], validating: ['Checking video', '正在檢查影片'],
    needs_capture_review: ['Video review', '影片審核中'], accepted: ['Video approved', '影片已通過'],
    needs_recapture: ['New video needed', '需要重新拍攝'], rejected: ['Video not accepted', '影片未通過'],
    validation_failed: ['Processing issue', '處理異常']
  };
  const modelStages = {
    queued: ['Model queued', '模型排隊中'], extracting_frames: ['Selecting frames', '擷取畫格中'],
    features: ['Finding features', '提取特徵中'], matching: ['Matching views', '配對視角中'],
    sparse_reconstruction: ['Reconstructing cameras', '重建相機中'], dense_reconstruction: ['Building point cloud', '建立點雲中'],
    scale_review: ['Scale review', '比例審核中'], stopped: ['Modeling paused', '建模暫停']
  };
  const label = pair => pair ? t(pair[0], pair[1]) : '';
  async function request(path) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) { location.assign('login.html?next=prosthetic.html'); return null; }
    if (!response.ok) throw new Error(data.detail?.code || `HTTP ${response.status}`);
    return data;
  }
  function empty(message) {
    host.replaceChildren();
    const box = document.createElement('div');
    box.className = 'empty-state';
    const title = document.createElement('h2');
    title.textContent = message;
    const link = document.createElement('a');
    link.className = 'button button-dark';
    link.href = 'create.html';
    link.textContent = t('Create a cover', '設計保護套');
    box.append(title, link);
    host.append(box);
  }
  function makeCard(item) {
    const card = document.createElement('article');
    card.className = 'design-card';
    const image = document.createElement('div');
    image.className = 'design-image';
    const picture = document.createElement('img');
    picture.src = `assets/templates/${styles[item.template_id] ? item.template_id : '01'}.png`;
    picture.alt = t('Selected cover style preview', '所選保護套樣式預覽');
    image.append(picture);
    const info = document.createElement('div');
    info.className = 'design-info';
    const title = document.createElement('h2');
    title.textContent = `${t('Design', '設計')} ${item.id.slice(0, 8)}`;
    const description = document.createElement('p');
    description.textContent = `${label(styles[item.template_id])} · ${item.color} · ${item.material}`;
    const status = document.createElement('span');
    status.className = 'status-pill';
    status.textContent = label(labels[item.status]) || item.status;
    const model = document.createElement('p');
    model.className = 'workflow-note';
    model.textContent = item.model
      ? `${t('Model', '模型')}：${label(modelStages[item.model.stage]) || item.model.stage}`
      : t('Modeling starts after video review.', '影片審核後開始建模。');
    const note = document.createElement('p');
    note.className = 'workflow-note';
    note.textContent = t('The image shows your chosen style. Your custom model is still being prepared.', '圖片顯示所選樣式；你的專屬模型仍在準備中。');
    info.append(title, description, status, model, note);
    card.append(image, info);
    return card;
  }
  document.querySelector('.menu-toggle').addEventListener('click', event => {
    const open = document.querySelector('.nav-links').classList.toggle('open');
    event.currentTarget.setAttribute('aria-expanded', String(open));
  });
  (async () => {
    try {
      const result = await request('/api/customer/submissions');
      if (!result) return;
      if (!result.items.length) return empty(t('No designs yet', '尚未提交設計'));
      host.replaceChildren(...result.items.map(makeCard));
      if (new URLSearchParams(location.search).has('submitted')) {
        const notice = document.createElement('div');
        notice.className = 'lab-submitted-notice';
        notice.textContent = t('Your video and design choices have been submitted.', '影片和設計選項已提交。');
        host.before(notice);
      }
    } catch {
      empty(t('Cannot load your designs right now', '目前無法載入設計'));
    }
  })();
})();

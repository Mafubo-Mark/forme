(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const t = (en, zh) => window.FormeI18n?.locale === 'zh-Hant' ? zh : en;
  const draft = { uploadId: null, submissionId: null, templateId: '01', color: 'Satin Silver', material: 'Lightweight Polymer' };
  const styles = {
    '01': ['祥云', 'Auspicious Cloud'], '02': ['蜂巢', 'Honeycomb'], '03': ['流线', 'Streamline'],
    '04': ['竹影', 'Bamboo Shadow'], '05': ['鳞羽', 'Scale Feather'], '06': ['通风', 'Ventilated'],
    '05-magnetic': ['鳞羽内嵌磁吸', 'Scale Feather Magnetic']
  };
  const colors = { 'Satin Silver': '#bdc9c3', 'Deep Charcoal': '#303b38', 'Soft Sand': '#c8b99f', 'Ocean Blue': '#4a728b' };
  let step = 0;
  let busy = false;
  let templatesReady = false;

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && data.detail?.code === 'CUSTOMER_SESSION_REQUIRED') {
      location.assign('login.html?next=create.html');
      throw new Error('CUSTOMER_SESSION_REQUIRED');
    }
    if (!response.ok) throw new Error(data.detail?.code || `HTTP ${response.status}`);
    return data;
  }
  function error(message) { $('#wizard-error').textContent = message; $('#wizard-error').hidden = false; }
  function clearError() { $('#wizard-error').hidden = true; $('#wizard-error').textContent = ''; }
  function show(index) {
    step = index;
    $$('.wizard-step').forEach((element, i) => element.classList.toggle('active', i === index));
    $$('.wizard-progress span').forEach((element, i) => {
      element.classList.toggle('active', i === index);
      element.classList.toggle('done', i < index);
    });
    $('#step-count').textContent = `STEP 0${index + 1} / 04`;
    $('#prev-step').hidden = index === 0;
    $('#next-step').textContent = index === 3 ? t('Submit design ↗', '提交設計 ↗') : t('Continue →', '繼續 →');
    clearError();
    scrollTo({ top: 0, behavior: 'smooth' });
  }
  function selectedColor() { return colors[draft.color] || draft.color; }
  function paintModel() {
    for (const material of $('#cover-preview-3d').model?.materials || []) {
      material.pbrMetallicRoughness.setBaseColorFactor(selectedColor());
    }
  }
  function updatePreview() {
    $('#preview-color').textContent = draft.color.startsWith('#') ? draft.color : t(draft.color, {
      'Satin Silver': '緞面銀', 'Deep Charcoal': '深炭灰', 'Soft Sand': '柔沙色', 'Ocean Blue': '海洋藍'
    }[draft.color]);
    $('#preview-material').textContent = draft.material;
    $('#preview-style').textContent = t(styles[draft.templateId][1], styles[draft.templateId][0]);
    const viewer = $('#cover-preview-3d');
    const modelUrl = `assets/templates/${draft.templateId}.glb`;
    if (viewer.getAttribute('src') !== modelUrl) viewer.src = modelUrl;
    viewer.poster = `assets/templates/${draft.templateId}.png`;
    viewer.style.setProperty('--preview-tint', selectedColor());
    const poster = $('#cover-preview-poster');
    poster.src = `assets/templates/${draft.templateId}.png`;
    poster.style.filter = draft.color === 'Satin Silver' ? 'none' : `drop-shadow(0 0 1px ${selectedColor()})`;
    paintModel();
  }
  function renderStyles(items) {
    const container = $('#style-options');
    container.replaceChildren();
    for (const item of items) {
      if (!styles[item.id]) continue;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `style-choice${item.id === draft.templateId ? ' selected' : ''}`;
      button.dataset.templateId = item.id;
      button.setAttribute('aria-pressed', String(item.id === draft.templateId));
      const image = document.createElement('img');
      image.src = `assets/templates/${item.id}.png`;
      image.alt = t(`${styles[item.id][1]} style`, `${styles[item.id][0]}樣式`);
      const name = document.createElement('strong');
      name.textContent = t(styles[item.id][1], styles[item.id][0]);
      button.append(image, name);
      button.addEventListener('click', () => {
        draft.templateId = item.id;
        $$('.style-choice').forEach(other => {
          const selected = other === button;
          other.classList.toggle('selected', selected);
          other.setAttribute('aria-pressed', String(selected));
        });
        updatePreview();
      });
      container.append(button);
    }
    templatesReady = container.childElementCount > 0;
    updatePreview();
  }
  function mediaType(file) {
    return file.type || ({ mov: 'video/quicktime', mp4: 'video/mp4', webm: 'video/webm' })[file.name.split('.').pop().toLowerCase()];
  }
  function uploadContent(url, file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', url);
      xhr.withCredentials = true;
      xhr.upload.onprogress = event => {
        if (event.lengthComputable) onProgress(Math.round(100 * event.loaded / event.total));
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch {}
        if (xhr.status === 401) { location.assign('login.html?next=create.html'); return; }
        xhr.status >= 200 && xhr.status < 300 ? resolve(data) : reject(new Error(data.detail?.code || `HTTP ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error(t('Upload connection lost. Please retry.', '上傳連線中斷，請重試。')));
      xhr.send(file);
    });
  }
  async function submitVideo() {
    if (draft.uploadId) return;
    const file = $('#video-input').files[0];
    if (!file) throw new Error(t('Choose a video first.', '請先選擇影片。'));
    if (!['video/mp4', 'video/quicktime', 'video/webm'].includes(mediaType(file))) throw new Error(t('Use MP4, MOV or WebM.', '請使用 MP4、MOV 或 WebM。'));
    if (file.size > 512 * 1024 * 1024) throw new Error(t('The video exceeds 512 MB.', '影片超過 512 MB。'));
    $('#video-feedback').textContent = t('Preparing upload…', '正在準備上傳…');
    const created = await api('/api/uploads/init', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: file.name, content_type: mediaType(file), byte_size: file.size })
    });
    await uploadContent(created.uploadUrl, file, percent => {
      $('#video-feedback').textContent = t(`Uploading ${file.name} · ${percent}%`, `正在上傳 ${file.name} · ${percent}%`);
    });
    await api(`/api/uploads/${created.uploadId}/complete`, { method: 'POST' });
    draft.uploadId = created.uploadId;
    $('#video-feedback').textContent = t(`Uploaded: ${file.name}`, `已上傳：${file.name}`);
    $('#model-status-title').textContent = t('Video received', '已收到影片');
    $('#model-status-copy').textContent = t('Your video will be checked before modeling begins.', '建模前會先檢查影片品質。');
  }
  async function submitDesign() {
    if (!draft.uploadId) throw new Error(t('The video has not finished uploading.', '影片尚未完成上傳。'));
    if (!templatesReady) throw new Error(t('Styles are unavailable. Try reloading the page.', '目前無法取得樣式，請重新載入頁面。'));
    if (!draft.submissionId) {
      const created = await api('/api/customer/submissions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: draft.uploadId, template_id: draft.templateId, color: draft.color,
          material: draft.material, inspiration: $('#inspiration-text').value.trim() })
      });
      draft.submissionId = created.submissionId;
    }
    const image = $('#inspiration-image').files[0];
    if (image) {
      const type = image.type || ({ jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp' })[image.name.split('.').pop().toLowerCase()];
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(type) || image.size > 10 * 1024 * 1024) throw new Error(t('Use a JPG, PNG or WebP image under 10 MB.', '靈感圖片須為 10 MB 以內的 JPG、PNG 或 WebP。'));
      await api(`/api/customer/submissions/${draft.submissionId}/inspiration-image`, {
        method: 'PUT', headers: { 'Content-Type': type, 'X-File-Name': image.name }, body: image
      });
    }
    location.assign(`prosthetic.html?submitted=${encodeURIComponent(draft.submissionId)}`);
  }
  $('.menu-toggle').addEventListener('click', event => {
    const open = $('.nav-links').classList.toggle('open');
    event.currentTarget.setAttribute('aria-expanded', String(open));
  });
  $('#video-input').addEventListener('change', () => {
    draft.uploadId = null;
    const file = $('#video-input').files[0];
    $('#video-feedback').textContent = file ? t(`Selected: ${file.name}`, `已選擇：${file.name}`) : '';
  });
  $('#inspiration-image').addEventListener('change', () => {
    const file = $('#inspiration-image').files[0];
    $('#inspiration-feedback').textContent = file ? t(`Selected: ${file.name}`, `已選擇：${file.name}`) : '';
  });
  function choose(selector, key, attribute) {
    $$(selector).forEach(button => button.addEventListener('click', () => {
      draft[key] = button.dataset[attribute];
      $$(selector).forEach(item => {
        const selected = item === button;
        item.classList.toggle('selected', selected);
        item.setAttribute('aria-pressed', String(selected));
      });
      updatePreview();
    }));
  }
  choose('.color-choice', 'color', 'color');
  choose('.material-choice', 'material', 'material');
  $('#cover-preview-3d').addEventListener('load', paintModel);
  $('#custom-color').addEventListener('input', event => {
    draft.color = event.target.value;
    $$('.color-choice').forEach(item => { item.classList.remove('selected'); item.setAttribute('aria-pressed', 'false'); });
    updatePreview();
  });
  $('#prev-step').addEventListener('click', () => { if (!busy) show(Math.max(0, step - 1)); });
  $('#next-step').addEventListener('click', async () => {
    if (busy) return;
    busy = true;
    $('#next-step').disabled = true;
    clearError();
    try {
      if (step === 0) await submitVideo();
      if (step === 3) await submitDesign();
      else show(step + 1);
    } catch (failure) {
      if (failure.message !== 'CUSTOMER_SESSION_REQUIRED') error(failure.message || t('Please retry.', '請重試。'));
    } finally {
      busy = false;
      $('#next-step').disabled = false;
    }
  });
  updatePreview();
  api('/api/customer/session').then(() => api('/api/customer/templates')).then(result => renderStyles(result.items))
    .catch(failure => { if (failure.message !== 'CUSTOMER_SESSION_REQUIRED') error(t('Cannot reach the design service.', '無法連線至設計服務。')); });
})();

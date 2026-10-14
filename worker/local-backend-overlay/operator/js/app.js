(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const cloudHosted = location.pathname.startsWith('/api/admin/operator/');
  const state = { uploadId: null, submissionId: null, modelNextAction: null, poll: null, pollActive: false, viewActive: false, frameKey: null, frameUrls: [], rulerMarks: new Map(), rulerClicks: [], rulerSuggestion: null };
  const viewSlots = { front: '正面', back: '背面', left: '左侧', right: '右侧', top: '上口俯视', bolt: '螺栓侧' };
  const labels = {
    initiated: '等待上传', uploading: '上传中', uploaded: '已上传，等待质检',
    validating: '正在检查视频', needs_capture_review: '等待人工复核',
    accepted: '拍摄复核通过', needs_recapture: '需要补拍',
    rejected: '视频未通过基础检查', validation_failed: '媒体处理服务失败'
  };
  const modelStages = {
    queued: '等待建模工作器', extracting_frames: '抽取建模帧', features: '提取图像特征',
    matching: '匹配相邻画面', sparse_reconstruction: '恢复相机与稀疏点云',
    dense_reconstruction: '重建稠密点云', scale_review: '标尺定尺度审查',
    capture_review: '等待拍摄复核', stopped: '建模阶段停止'
  };

  function log(title, payload) {
    const current = $('#response-log').textContent;
    const stamp = new Date().toLocaleTimeString('zh-HK');
    $('#response-log').textContent = `[${stamp}] ${title}\n${JSON.stringify(payload, null, 2)}\n\n${current === '暂无请求。' ? '' : current}`.slice(0, 12000);
  }

  function token() {
    const value = $('#dev-token').value.trim();
    if (!value) throw new Error('请先输入开发 Bearer token。');
    return value;
  }

  const images = new OperatorMediaLoader({ headers: () => cloudHosted ? {} : { Authorization: `Bearer ${token()}` } });
  function setImage(image, path) {
    image.setAttribute('aria-busy', 'true');
    image.dataset.imageState = 'loading';
    const hint = makeText('p', '图片加载中…', 'lab-muted');
    const load = () => {
      hint.textContent = '图片加载中…';
      images.get(path).then(url => {
        if (!image.isConnected) return;
        image.src = url;
        image.dataset.imageState = 'ready';
        image.setAttribute('aria-busy', 'false');
        hint.remove();
      }).catch(error => {
        if (!image.isConnected || error.message === 'STALE_IMAGE') return;
        image.dataset.imageState = 'error';
        image.setAttribute('aria-busy', 'false');
        const expired = error.status === 401;
        hint.textContent = expired
          ? (cloudHosted ? '管理员登录已过期，请重新登录后再试。' : '本机连接已失效，请重新连接。')
          : `图片读取失败（${error.name === 'AbortError' ? '连接超时' : error.message}）。`;
        const retry = makeText('button', '重试此图');
        retry.type = 'button';
        retry.addEventListener('click', load);
        hint.append(' ', retry);
        if (expired && cloudHosted) {
          const login = makeText('a', '打开管理员登录');
          login.href = '/admin.html';
          login.target = '_blank';
          login.rel = 'noopener';
          hint.append(' ', login);
        }
      });
    };
    queueMicrotask(() => { if (image.isConnected) { image.after(hint); load(); } });
  }

  async function api(path, options = {}) {
    const { quiet = false, ...requestOptions } = options;
    const headers = { ...(cloudHosted ? {} : { Authorization: `Bearer ${token()}` }), ...(requestOptions.headers || {}) };
    const response = await fetch(path, { ...requestOptions, headers, cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      log(`${requestOptions.method || 'GET'} ${path} · ${response.status}`, data);
      const detail = data.detail || {};
      const error = new Error(detail.message || detail.code || `请求失败：HTTP ${response.status}`);
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    if (!quiet) log(`${requestOptions.method || 'GET'} ${path} · ${response.status}`, data);
    return data;
  }

  async function downloadCloudModelInParts(path, button, status) {
    button.disabled = true;
    const chunks = [];
    const chunkSize = 1024 * 1024;
    let offset = 0;
    let total = null;
    let filename = 'forme-model.stl';
    try {
      while (total === null || offset < total) {
        const end = offset + chunkSize - 1;
        let received;
        for (let attempt = 0; attempt < 3; attempt++) {
          const controller = new AbortController();
          const timeout = setTimeout(() => controller.abort(), 20000);
          try {
            const response = await fetch(path, { headers: { Range: `bytes=${offset}-${end}` }, cache: 'no-store', credentials: 'same-origin', signal: controller.signal });
            const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get('Content-Range') || '');
            if (response.status !== 206 || !range || Number(range[1]) !== offset) throw new Error(`云端分段响应无效：HTTP ${response.status}`);
            const size = Number(range[3]);
            if (!Number.isSafeInteger(size) || size <= 0 || size > 100 * 1024 * 1024 || (total !== null && total !== size)) throw new Error('云端文件大小无效。');
            const chunk = await response.arrayBuffer();
            if (chunk.byteLength !== Number(range[2]) - offset + 1) throw new Error('云端文件片段不完整。');
            received = { response, chunk, size };
            break;
          } catch (error) {
            if (attempt === 2) throw error;
            status.textContent = `第 ${Math.floor(offset / chunkSize) + 1} 段连接中断，重试 ${attempt + 1}/2…`;
          } finally {
            clearTimeout(timeout);
          }
        }
        total = received.size;
        if (offset === 0) {
          const disposition = received.response.headers.get('Content-Disposition') || '';
          const match = /filename="?([^";]+)"?/i.exec(disposition);
          if (match) filename = match[1];
        }
        chunks.push(received.chunk);
        offset += received.chunk.byteLength;
        status.textContent = `已接收 ${(offset / 1048576).toFixed(1)} / ${(total / 1048576).toFixed(1)} MB`;
      }
      if (!filename.toLowerCase().endsWith('.stl')) throw new Error('云端归档尚未同步为 STL。');
      const blob = new Blob(chunks, { type: 'model/stl' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      status.textContent = `下载完成：${filename}（${(total / 1048576).toFixed(1)} MB）`;
    } catch (error) {
      status.textContent = error.message || '分段下载失败。';
    } finally {
      button.disabled = false;
    }
  }

  function showError(error) {
    if (error.status === 401) {
      $('#connection-state').textContent = '令牌无效';
      $('#connection-state').className = 'lab-state is-error';
    }
    $('#upload-hint').textContent = error.message || '操作失败，请检查接口记录。';
    $('#view-hint').textContent = error.message || '操作失败，请检查接口记录。';
  }

  function setConnected() {
    $('#connection-state').textContent = '已连接';
    $('#connection-state').className = 'lab-state is-ok';
    $('#upload-button').disabled = !$('#video-file').files.length;
  }

  async function refreshWorkerStatus() {
    const status = await api('/api/internal/worker-status', {quiet:true});
    $('#worker-state').textContent = `工作器：视频 ${status.media ? '运行中' : '未运行'} · COLMAP ${status.colmap ? '运行中' : '未运行'} · 混元 ${status.hunyuan ? '运行中' : status.hunyuanConfigured ? '未运行' : '未配置密钥'} · 几何 ${status.geometryConfigured ? '可用' : '未配置'}`;
  }

  async function refreshList() {
    const data = await api('/api/uploads');
    const host = $('#upload-list');
    host.replaceChildren();
    if (!data.items.length) {
      const empty = document.createElement('p');
      empty.className = 'lab-muted';
      empty.textContent = '还没有上传记录。';
      host.append(empty);
      return;
    }
    for (const item of data.items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'lab-upload-item' + (item.id === state.uploadId ? ' is-selected' : '');
      const details = document.createElement('span');
      const name = document.createElement('strong');
      name.textContent = item.filename;
      const date = document.createElement('small');
      date.textContent = `${new Date(item.created_at).toLocaleString('zh-HK')} · ${item.id.slice(0, 8)}`;
      const status = document.createElement('em');
      status.textContent = labels[item.status] || item.status;
      details.append(name, date);
      button.append(details, status);
      button.addEventListener('click', () => selectUpload(item.id));
      host.append(button);
    }
  }

  function makeText(tag, value, className) {
    const element = document.createElement(tag);
    element.textContent = value;
    if (className) element.className = className;
    return element;
  }

  async function refreshSubmissions() {
    const data = await api('/api/internal/submissions');
    const host = $('#submission-list');
    host.replaceChildren();
    if (!data.items.length) {
      host.append(makeText('p', '还没有从前端提交的任务。', 'lab-muted'));
      return;
    }
    for (const item of data.items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'lab-upload-item' + (item.id === state.submissionId ? ' is-selected' : '');
      const details = document.createElement('span');
      details.append(makeText('strong', item.filename), makeText('small', `${new Date(item.created_at).toLocaleString('zh-HK')} · ${item.id.slice(0, 8)}`));
      button.append(details, makeText('em', labels[item.status] || item.status));
      button.addEventListener('click', () => showSubmission(item.id).catch(showError));
      host.append(button);
    }
  }

  async function refreshTemplates() {
    const data = await api('/api/internal/templates', { quiet: true });
    const host = $('#template-list');
    host.replaceChildren();
    const select = $('#cover-template');
    const selected = select.value;
    select.replaceChildren();
    for (const item of data.items) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = `${item.id} · ${item.name}`;
      select.append(option);
      const row = document.createElement('div');
      row.className = 'lab-upload-item';
      const detail = document.createElement('span');
      detail.append(makeText('strong', `${item.id} · ${item.name}`),
        makeText('small', `${item.fixing} · ${item.hasEditableBlend ? '有可编辑 Blender 源文件' : 'STL 网格'}`));
      row.append(detail, makeText('em', '待适配复核'));
      host.append(row);
    }
    if (data.unidentifiedCount) host.append(makeText('p', `${data.unidentifiedCount} 份独立 STL 来源待确认，暂不自动选用。`, 'lab-muted'));
    if (!data.items.length) host.append(makeText('p', '尚未登记模板。', 'lab-muted'));
    if (selected && [...select.options].some(option => option.value === selected)) select.value = selected;
    $('#prepare-cover-task').disabled = !state.submissionId || !data.items.length;
  }

  function meta(label, value) {
    const box = document.createElement('div');
    box.append(makeText('span', label), makeText('strong', value || '未填写'));
    return box;
  }

  function renderSubmission(data) {
    state.modelNextAction = data.hunyuanJob?.rulerOnlyAssessment
      ? '200 mm 标定尺已形成候选毫米尺度；下一步复核局部形状与模板坐标注册。'
      : data.modelJob?.next_action || null;
    const host = $('#submission-detail');
    host.replaceChildren();
    $('#submission-id-short').textContent = data.submissionId.slice(0, 8);
    const choices = document.createElement('div');
    choices.className = 'lab-detail-meta';
    choices.append(meta('样式模板', data.choices.templateId || '01'), meta('颜色', data.choices.color), meta('材料', data.choices.material), meta('提交时间', new Date(data.createdAt).toLocaleString('zh-HK')));
    host.append(choices);
    if (data.choices.inspiration) {
      const inspiration = document.createElement('div');
      inspiration.className = 'lab-resource';
      inspiration.append(makeText('h3', '灵感说明'), makeText('p', data.choices.inspiration));
      host.append(inspiration);
    }
    const videoBox = document.createElement('div');
    videoBox.className = 'lab-resource';
    videoBox.append(makeText('h3', '用户提交的视频'), makeText('p', `${data.resources.video.filename} · ${(data.resources.video.byteSize / 1024 / 1024).toFixed(1)} MB`));
    if (data.resources.video.previewUrl) {
      const video = document.createElement('video');
      video.controls = true;
      video.preload = 'metadata';
      video.src = data.resources.video.previewUrl;
      videoBox.append(video);
      videoBox.append(makeText('p', '下方为浏览器兼容预览；原视频完整保留。', 'lab-muted'));
    } else {
      videoBox.append(makeText('p', '浏览器预览尚未就绪，请打开原视频查看。', 'lab-muted'));
    }
    const videoLink = document.createElement('a');
    videoLink.href = data.resources.video.url;
    videoLink.target = '_blank';
    videoLink.rel = 'noopener';
    videoLink.textContent = '在新标签打开原视频';
    videoBox.append(videoLink);
    host.append(videoBox);
    if (data.resources.inspirationImage) {
      const imageBox = document.createElement('div');
      imageBox.className = 'lab-resource';
      imageBox.append(makeText('h3', '灵感图片'), makeText('p', data.resources.inspirationImage.filename));
      const image = document.createElement('img');
      setImage(image, data.resources.inspirationImage.url);
      image.alt = `用户上传的灵感图片：${data.resources.inspirationImage.filename}`;
      imageBox.append(image);
      host.append(imageBox);
    }
    const timeline = document.createElement('div');
    timeline.className = 'lab-timeline';
    timeline.append(makeText('h3', '工作流处理记录'));
    const list = document.createElement('ol');
    for (const event of data.events) {
      const item = document.createElement('li');
      item.append(makeText('strong', labels[event.status] || event.status), makeText('small', new Date(event.created_at).toLocaleString('zh-HK')));
      if (event.note || event.reason_code) item.append(makeText('p', event.note || event.reason_code));
      list.append(item);
    }
    timeline.append(list);
    timeline.append(makeText('div', `当前：${labels[data.capture.status] || data.capture.status}。下一阶段：${data.productionFlow?.stages.find(step => step.id === data.productionFlow.nextStage)?.label || '待复核'}。`, 'lab-pending'));
    if (data.capture.nextAction && !data.modelJob) timeline.append(makeText('p', data.capture.nextAction, 'lab-warning'));
    host.append(timeline);
    const modelBox = document.createElement('div');
    modelBox.className = 'lab-timeline';
    modelBox.append(makeText('h3', '参考模型任务'));
    if (!data.modelJob) {
      modelBox.append(makeText('p', '尚未启动。拍摄人工复核通过后可启动本机 COLMAP 重建。', 'lab-muted'));
    } else {
      const job = data.modelJob;
      modelBox.append(makeText('p', `当前：${modelStages[job.stage] || job.stage} · ${job.status}`, 'lab-pending'));
      if (state.modelNextAction) modelBox.append(makeText('p', state.modelNextAction, 'lab-warning'));
      if (job.metrics) modelBox.append(makeText('p', `已抽取 ${job.metrics.frameCount} 帧；原始点云 ${job.metrics.pointCount} 点；${data.hunyuanJob?.rulerOnlyAssessment ? '已有标尺推算候选尺度，局部几何未核准。' : '毫米尺度尚未核验。'}`, 'lab-muted'));
      if (job.cloudUrl) {
        const link = document.createElement('a');
        link.href = job.cloudUrl;
        link.textContent = '下载未定尺度 COLMAP 点云';
        modelBox.append(link);
      }
      const jobEvents = document.createElement('ol');
      for (const event of job.events) {
        const item = document.createElement('li');
        item.append(makeText('strong', modelStages[event.stage] || event.stage), makeText('small', new Date(event.created_at).toLocaleString('zh-HK')));
        if (event.note || event.reason_code) item.append(makeText('p', event.note || event.reason_code));
        jobEvents.append(item);
      }
      modelBox.append(jobEvents);
    }
    host.append(modelBox);
    const hunyuanBox = document.createElement('div');
    hunyuanBox.className = 'lab-resource';
    hunyuanBox.append(makeText('h3', '混元 3D 生成候选'));
    const hunyuan = data.hunyuanJob;
    if (!hunyuan) {
      hunyuanBox.append(makeText('p', '此任务尚无混元 3D 生成记录。', 'lab-muted'));
    } else {
      hunyuanBox.append(makeText('p', `腾讯云国际版 · 模型 ${hunyuan.model} · ${hunyuan.status} · ${hunyuan.jobId}`, 'lab-muted'));
      if (hunyuan.workerError) hunyuanBox.append(makeText('p', `自动查询/归档遇到问题：${hunyuan.workerError}`, 'lab-warning'));
      hunyuanBox.append(makeText('p', '提交了正面、左侧、右侧、背面；上口和螺栓图留作结果核对。生成模型尚未确认毫米尺度、局部形状与保护套贴合。', 'lab-warning'));
      if (hunyuan.previewUrl) {
        const preview = document.createElement('img');
        setImage(preview, hunyuan.previewUrl);
        preview.alt = '混元 3D 白模生成预览';
        hunyuanBox.append(preview);
      }
      if (hunyuan.modelUrl) {
        const link = document.createElement('a');
        link.href = hunyuan.modelUrl;
        link.textContent = '下载混元 3D 原始 GLB 候选';
        hunyuanBox.append(link);
      }
      if (hunyuan.alignment) {
        const alignment = hunyuan.alignment;
        hunyuanBox.append(makeText('p', `新混元模型与标定点云做了探索性对齐：白筒区域点云到模型的中位距离 ${alignment.whiteMedianMm.toFixed(1)} mm，上部黑壳 ${alignment.blackMedianMm.toFixed(1)} mm。这些数值反映模型差异，不是保护套间隙。`, 'lab-warning'));
        for (const [url, label] of [[alignment.frontOverlayUrl, '正面点云与模型叠图'], [alignment.sideOverlayUrl, '侧面点云与模型叠图']]) {
          const image = document.createElement('img');
          setImage(image, url);
          image.alt = label;
          hunyuanBox.append(image);
        }
      }
      if (hunyuan.rulerOnlyAssessment) {
        const ruler = hunyuan.rulerOnlyAssessment;
        hunyuanBox.append(makeText('p', `仅按视频中的 ${ruler.knownTargetLengthMm.toFixed(0)} mm 标定尺推算：${ruler.primaryMmPerColmapUnit.toFixed(3)} mm／COLMAP 单位；两套同视频重建比例相差 ${ruler.reconstructionScaleSpreadPercent.toFixed(3)}%。候选可见轴向跨度约 ${ruler.visibleAxialSpanMm.toFixed(1)} mm。比例差不是整体尺寸误差范围；点云局部形状和模板配准尚未验收。`, 'lab-warning'));
        hunyuanBox.append(makeText('p', '旧的“模板上口还差约 10.3 mm”比较使用了未对齐的截面，现已撤回。下一步按相同高度和方向比较点云候选与模板内腔。', 'lab-warning'));
      } else if (hunyuan.templatePreflight?.status?.startsWith('SUPERSEDED')) {
        hunyuanBox.append(makeText('p', '旧模板缺口比较因截面未对齐已撤回。已改用视频中的 200 mm 标定尺推算候选毫米尺度；详情见交接包，待服务重启后显示完整标定报告。', 'lab-warning'));
      } else if (hunyuan.templatePreflight?.conditionalUpperWidthDeficitMm != null) {
        hunyuanBox.append(makeText('p', `模板条件筛查：若 120 mm 实测位置对应模板上口，在每侧 1.5 mm 净空、受限形变 ±3 mm 后，内宽仍差约 ${hunyuan.templatePreflight.conditionalUpperWidthDeficitMm.toFixed(1)} mm。需核对截面并重设上口。`, 'lab-warning'));
      }
      if (hunyuan.pointcloudQa) {
        const qa = hunyuan.pointcloudQa;
        const coverage = qa.totalSections
          ? `${qa.totalSections} 个轴向采样截面中 ${qa.fullyOccupiedSections} 个覆盖全部 24 个角度分箱；下部 ${qa.sparseLowerSections.join('、') || '未列出'} mm、上部 ${qa.sparseUpperSections.join('、') || '未列出'} mm 需复核。`
          : '主体裁剪和角度覆盖尚未复核。';
        hunyuanBox.append(makeText('p', `点云检查：视频与点云来源${qa.provenanceVerified ? '已核对' : '未核对通过'}；${coverage}表面贴合精度未验证。`, 'lab-warning'));
        if (qa.imageConsistency) {
          const check = qa.imageConsistency;
          hunyuanBox.append(makeText('p', `原视频影像复核：已检查 ${check.frameCount} 个视角；其中 ${check.uprightFrameCount} 个直立视角的深色外壳近似轮廓重合度中位数为 ${check.uprightMedianSilhouetteIoU.toFixed(2)}。可见外轮廓基本一致；俯视内腔中心和两端点云不完整，不能用于判断保护套贴合间隙。`, 'lab-warning'));
          const image = document.createElement('img');
          setImage(image, check.contactSheetUrl);
          image.alt = '原视频与点云投影对照：绿色为重合，橙色为画面独有，青色为点云独有';
          hunyuanBox.append(image);
        }
      }
      if (hunyuan.workbuddyHybrid) {
        const hybrid = hunyuan.workbuddyHybrid;
        hunyuanBox.append(makeText('h3', `WorkBuddy · 祥云保护套 V${hybrid.version}`));
        hunyuanBox.append(makeText('p', hybrid.version === 2
          ? `已修正上口扭曲：上口整体保留模板的低开口形状，让接收器高翻边露出；245–285 mm 平滑接回点云驱动的筒身。90–280 mm 点云段正视轮廓重合度约 ${hybrid.trustedBandSilhouetteIoU.toFixed(2)}。上口净空、内腔间隙和实物贴合仍未验证；混元几何未融入外壳。`
          : `WorkBuddy 已生成前后双片审查模型。以标尺点云的可见外轮廓定形，并用混元模型核对上口；因两者在上口冲突，混元几何没有融入外壳。90–280 mm 点云段的正视轮廓重合度约 ${hybrid.trustedBandSilhouetteIoU.toFixed(2)}；这是同源数据的轮廓检查，不代表内腔间隙或实物贴合。`, 'lab-warning'));
        for (const [url, label] of [[hybrid.frontPreviewUrl, 'WorkBuddy 正面预览'], [hybrid.sidePreviewUrl, 'WorkBuddy 侧面预览'], [hybrid.topPreviewUrl, 'WorkBuddy 上口预览'], [hybrid.overlayUrl, 'WorkBuddy 点云叠图']]) {
          const preview = document.createElement('img');
          setImage(preview, url);
          preview.alt = label;
          hunyuanBox.append(preview);
        }
        const link = document.createElement('a');
        link.href = hybrid.previewModelUrl;
        link.textContent = `下载祥云 V${hybrid.version} 预览 GLB（非打印件）`;
        hunyuanBox.append(link);
      }
      if (hunyuan.printPrototype) {
        const prototype = hunyuan.printPrototype;
        hunyuanBox.append(makeText('h3', '祥云 V2 · 打印试样'));
        hunyuanBox.append(makeText('p', `已整理前后双片切片输入文件（毫米，100%）。模型高度 ${prototype.requiredBuildHeightMm.toFixed(0)} mm；请先核对打印机成型高度和切片预览。侧孔附近存在局部薄尖边，固定扣与实物贴合仍未验证；这版只用于尺寸、外形及局部装配试验。`, 'lab-warning'));
        for (const [url, label] of [[prototype.packageUrl, '下载双片 3MF（毫米）'], [prototype.frontUrl, '下载前片 STL'], [prototype.rearUrl, '下载后片 STL']]) {
          const link = document.createElement('a');
          link.href = url;
          link.textContent = label;
          hunyuanBox.append(link);
        }
      }
      if (hunyuan.visualConcept) {
        const concept = hunyuan.visualConcept;
        hunyuanBox.append(makeText('h3', '祥云 · 标尺推算造型候选'));
        hunyuanBox.append(makeText('p', `已生成双片审查模型；外轮廓相对点云目标的最大剩余缺口约 ${concept.maxExteriorEnvelopeShortfallMm.toFixed(1)} mm。前后方向、固定件和内腔贴合尚未验证；仅用于看造型。`, 'lab-warning'));
        for (const [url, label] of [[concept.frontPreviewUrl, '正面造型预览'], [concept.threeQuarterPreviewUrl, '斜侧造型预览']]) {
          if (!url) continue;
          const preview = document.createElement('img');
          setImage(preview, url);
          preview.alt = label;
          hunyuanBox.append(preview);
        }
        const link = document.createElement('a');
        link.href = concept.modelUrl;
        link.textContent = '下载祥云审查 GLB（不可作为打印成品）';
        hunyuanBox.append(link);
      }
    }
    host.append(hunyuanBox);
    $('#model-button').disabled = data.capture.status !== 'accepted' || !!data.modelJob;
    const cover = data.coverTask;
    const flowHost = $('#production-flow-state');
    flowHost.replaceChildren();
    const flowList = document.createElement('ol');
    for (const step of data.productionFlow?.stages || []) {
      const stateLabel = {done: '已完成', waiting: '待处理', review: '待复核', blocked: '待实物试装'}[step.state] || step.state;
      flowList.append(makeText('li', `${step.label}：${stateLabel}（${step.detail}）`));
    }
    flowHost.append(flowList);
    if (data.productionFlow?.trialCandidate) {
      const trial = data.productionFlow.trialCandidate;
      flowHost.append(makeText('p', `已登记 ${trial.candidateId} 数字试样；所需成型高度约 ${trial.requiredBuildHeightMm} mm。仍须在目标打印机切片软件中核对。`, 'lab-warning'));
      for (const [url, label] of [
        [trial.stlUrl, '下载双片组合 STL（毫米，需在切片软件中分件和摆放）'],
        [trial.frontStlUrl, '下载前片 STL（毫米）'],
        [trial.rearStlUrl, '下载后片 STL（毫米）'],
        [trial.packageUrl, '下载辅助 3MF（毫米，待切片验证）']
      ]) {
        if (!url) continue;
        const link = document.createElement('a');
        link.href = url;
        link.textContent = label;
        flowHost.append(link);
      }
      if (cloudHosted) {
        const cloudLink = document.createElement('a');
        cloudLink.href = `/api/admin/submissions/${encodeURIComponent(state.submissionId)}/files/model`;
        cloudLink.textContent = '下载云端归档模型（同步后为 STL）';
        flowHost.append(cloudLink);
        const chunkButton = document.createElement('button');
        chunkButton.type = 'button';
        chunkButton.textContent = '分段下载云端 STL（大文件）';
        const chunkStatus = makeText('p', '', 'lab-warning');
        chunkButton.addEventListener('click', () => downloadCloudModelInParts(cloudLink.href, chunkButton, chunkStatus));
        flowHost.append(chunkButton, chunkStatus);
      }
    }
    const flowStages = Object.fromEntries((data.productionFlow?.stages || []).map(step => [step.id, step]));
    $('#prepare-hunyuan').disabled = flowStages.views?.state !== 'done' || flowStages.hunyuan_input?.state === 'done' || !!data.hunyuanJob;
    $('#submit-hunyuan').disabled = flowStages.hunyuan_input?.state !== 'done' || !!data.hunyuanJob || !!data.productionFlow?.hunyuanSubmissionAttempt || !data.hunyuanConfigured;
    $('#poll-hunyuan').disabled = !data.hunyuanJob || ['DONE', 'FAIL'].includes(data.hunyuanJob.status) || !data.hunyuanConfigured;
    $('#archive-hunyuan').disabled = data.hunyuanJob?.status !== 'DONE' || flowStages.hunyuan_result?.state === 'done';
    $('#prepare-print-candidate').disabled = flowStages.candidate_review?.state !== 'review' || !!data.productionFlow?.trialCandidate || !data.geometryConfigured;
    $('#load-ruler-frames').disabled = flowStages.colmap?.state !== 'done';
    $('#calibrate-ruler').disabled = state.rulerMarks.size < 3 || !data.geometryConfigured;
    if (data.productionFlow?.rulerCalibration) {
      const scale = data.productionFlow.rulerCalibration;
      flowHost.append(makeText('p', `本单标尺候选尺度：${scale.mmPerColmapUnit.toFixed(3)} mm／COLMAP 单位；两个端点共同有效的相机 ${scale.commonImages} 张。局部形状与贴合仍需复核。`, 'lab-warning'));
    }
    $('#cover-task-state').textContent = cover?.manifestPath
      ? `交接包已准备：${cover.templateId} 模板。${cover.conceptBuildAllowed ? '概念配准已登记，可提交受限形变提案；生成后仍须检查网格与切片。' : `待完成：${(cover.blockers || []).join('、')}。`}`
      : '尚未准备交接包。选定模板后可将前端任务、素材路径和处理状态交给 WorkBuddy。';
    const review = cover?.candidateReview;
    const policy = cover?.generationPolicy;
    const reviewBlockerLabels = {
      UPPER_EDGE_CLEARANCE_UNVERIFIED: '上口净空未验证',
      SIDE_OPENING_THIN_EDGE: '侧孔存在薄边',
      LOCAL_THICKNESS_AND_SELF_INTERSECTION_REVIEW_REQUIRED: '局部壁厚与自交待检查',
      SLICER_PROFILE_CHECK_REQUIRED: '打印机切片参数待检查',
      FASTENER_AND_PHYSICAL_FIT_UNVERIFIED: '固定件和实物试装未验证',
    };
    const reviewText = review
      ? review.status === 'STALE_REVIEW' || review.status === 'INVALID_REVIEW'
        ? `生成审查记录需要重新生成（${review.status}）；不能用于放行。`
        : `${review.candidateId || '候选'}：${review.summary || '概念候选待复核'} 最大修形 ${review.maxVertexMoveMm ?? '未知'} mm；未完成项：${(review.blockers || []).map(code => reviewBlockerLabels[code] || code).join('、')}。不能判定为可生产或可佩戴。`
      : '当前任务尚无候选生成审查记录。';
    $('#cover-generation-review').textContent = `${policy?.id || '生成规则'}：低开口保留高翻边。${reviewText}`;
    $('#prepare-cover-task').disabled = !$('#cover-template').options.length;
    state.modelActive = !!data.modelJob && ['queued', 'running'].includes(data.modelJob.status);
    renderViews(data.viewReview, data.capture.status, data.visionConfigured, data.visionProvider);
    if (flowStages.hunyuan_input?.state === 'done') {
      $('#prepare-views').disabled = true;
      $('#classify-views').disabled = true;
      $('#save-views').disabled = true;
      $('#view-hint').textContent = '六视角已锁定到混元输入包。需要更改时须先处理该任务包与远端任务的版本关系。';
    }
  }

  function renderViews(review, captureStatus, visionConfigured, visionProvider) {
    const status = review?.status || 'not_started';
    const data = review?.data || {};
    const frames = data.frames || [];
    const ready = ['ready', 'classified', 'reviewed', 'incomplete', 'partial', 'failed'].includes(status) && frames.length > 0;
    state.viewActive = ['preparing', 'classifying'].includes(status);
    $('#view-state').textContent = ({not_started:'尚未准备', preparing:'正在抽帧', ready:'等待判断', classifying:'API 判断中', classified:'AI 建议已生成', reviewed:'已确认六个方向', incomplete:'部分方向待补拍', partial:'部分 API 判断失败', failed:'处理失败'})[status] || status;
    $('#prepare-views').disabled = !state.submissionId || !['needs_capture_review','accepted'].includes(captureStatus) || state.viewActive;
    $('#classify-views').disabled = !ready || !visionConfigured;
    $('#save-views').disabled = !ready;
    $('#view-hint').textContent = data.error || data.apiErrors?.[0]?.message || (status === 'classifying' ? `${visionProvider} 视觉 API 正在逐帧检查，请等待。` :
      status === 'preparing' ? '正在从原视频抽取候选帧。' :
      status === 'not_started' ? '抽帧后可标定正面并运行 AI 判断。' :
      `共 ${frames.length} 张候选；${visionConfigured ? `${visionProvider} 视觉 API 已配置，AI 建议仅供参考。` : `${visionProvider} 视觉 API 尚未配置密钥，可先人工选图。`}${data.missing?.length ? `AI 未识别：${data.missing.map(x => viewSlots[x]).join('、')}。` : ''}`);
    const grid = $('#view-frames');
    grid.replaceChildren();
    for (const frame of frames) {
      const figure = document.createElement('figure');
      const img = document.createElement('img');
      setImage(img, `/api/internal/submissions/${state.submissionId}/views/frames/${frame.name}`);
      img.alt = `${frame.name} 候选帧`;
      const caption = makeText('figcaption', `${frame.name} · ${frame.timestampSeconds}s · ${viewSlots[frame.label] || '未判断'}${frame.confidence == null ? '' : ` (${Math.round(frame.confidence * 100)}%)`} · 画质参考 ${frame.quality?.score == null ? '未计算' : Math.round(frame.quality.score * 100)}`);
      figure.append(img, caption, makeText('p', frame.reason || '', 'lab-view-reason'));
      grid.append(figure);
    }
    const selectors = $('#view-selectors');
    selectors.replaceChildren();
    for (const [slot, title] of Object.entries(viewSlots)) {
      const label = document.createElement('label');
      label.className = 'lab-field';
      label.append(makeText('span', title));
      const select = document.createElement('select');
      select.dataset.slot = slot;
      const blank = document.createElement('option');
      blank.value = '';
      blank.textContent = '未找到，请补拍或手动选择';
      select.append(blank);
      for (const frame of frames) {
        const option = document.createElement('option');
        option.value = frame.name;
        option.textContent = `${frame.name} · ${frame.timestampSeconds}s${frame.label === slot ? ' · AI 建议' : ''}`;
        select.append(option);
      }
      select.value = data.selections?.[slot] || data.suggestions?.[slot]?.[0] || '';
      label.append(select);
      selectors.append(label);
    }
    $('#view-notes').value = data.notes || '';
  }

  async function showSubmission(submissionId) {
    if (state.submissionId !== submissionId) {
      state.rulerMarks.clear();
      state.rulerClicks = [];
      state.rulerSuggestion = null;
      $('#ruler-frame').replaceChildren();
      $('#ruler-frame-image').hidden = true;
      $('#ruler-mark-list').replaceChildren();
    }
    const data = await api(`/api/internal/submissions/${submissionId}`);
    images.clear();
    state.frameKey = null;
    state.submissionId = submissionId;
    renderSubmission(data);
    await selectUpload(data.uploadId, true);
    await refreshSubmissions();
  }

  function setFacts(metadata) {
    const facts = $('#media-facts');
    facts.replaceChildren();
    facts.hidden = !metadata;
    if (!metadata) return;
    const values = [
      ['时长', `${metadata.duration_seconds.toFixed(1)} 秒`],
      ['分辨率', `${metadata.width} × ${metadata.height}`],
      ['编码', metadata.codec || '未知'],
      ['复核帧', `${(metadata.review_frames || []).length} 张`]
    ];
    for (const [label, value] of values) {
      const pair = document.createElement('div');
      const dt = document.createElement('dt');
      const dd = document.createElement('dd');
      dt.textContent = label;
      dd.textContent = value;
      pair.append(dt, dd);
      facts.append(pair);
    }
  }

  function clearFrames() {
    for (const url of state.frameUrls) URL.revokeObjectURL(url);
    state.frameUrls = [];
    state.frameKey = null;
    $('#review-frames').replaceChildren();
  }

  async function loadFrames(upload) {
    const names = upload.quality?.review_frames || [];
    const key = `${upload.uploadId}:${names.join(',')}`;
    if (state.frameKey === key) return;
    clearFrames();
    if (!names.length) {
      const empty = document.createElement('p');
      empty.className = 'lab-muted';
      empty.textContent = '视频质检完成后在这里显示复核帧。';
      $('#review-frames').append(empty);
      return;
    }
    const host = $('#review-frames');
    for (const [index, name] of names.entries()) {
      const figure = document.createElement('figure');
      const img = document.createElement('img');
      setImage(img, `/api/uploads/${upload.uploadId}/review-frames/${name}`);
      img.alt = `视频复核帧 ${index + 1}`;
      const caption = document.createElement('figcaption');
      caption.textContent = `帧 ${String(index + 1).padStart(2, '0')}`;
      figure.append(img, caption);
      host.append(figure);
    }
    state.frameKey = key;
  }

  function renderStatus(upload) {
    const status = upload.status;
    state.pollActive = status === 'validating' || status === 'uploading';
    const panel = $('#current-status');
    panel.classList.toggle('is-error', ['rejected', 'needs_recapture', 'validation_failed'].includes(status));
    panel.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = labels[status] || status;
    const copy = document.createElement('p');
    copy.textContent = (status === 'accepted' && state.modelNextAction) || upload.nextAction || (status === 'uploaded' ? '运行视频质检，生成供人工复核的抽样帧。' : '等待下一步操作。');
    panel.append(title, copy);
    $('#upload-id-short').textContent = upload.uploadId.slice(0, 8);
    $('#validate-button').disabled = status !== 'uploaded';
    $('#approve-button').disabled = status !== 'needs_capture_review';
    $('#recapture-button').disabled = status !== 'needs_capture_review';
    $('#model-button').disabled = status !== 'accepted' || !state.submissionId;
    if (upload.reviewNotes) $('#review-notes').value = upload.reviewNotes;
    const steps = [...document.querySelectorAll('.lab-steps span')];
    const active = ['initiated', 'uploading'].includes(status) ? -1 :
      status === 'uploaded' || status === 'validating' ? 1 :
      ['needs_capture_review', 'accepted', 'needs_recapture'].includes(status) ? 2 : 1;
    steps.forEach((step, index) => step.classList.toggle('is-active', index <= active));
    setFacts(upload.quality);
  }

  async function pollCurrent() {
    if (!state.uploadId) return;
    const upload = await api(`/api/uploads/${state.uploadId}`, { quiet: true });
    renderStatus(upload);
    await loadFrames(upload);
    if (state.submissionId) {
      const detail = await api(`/api/internal/submissions/${state.submissionId}`, { quiet: true });
      if (detail.uploadId === upload.uploadId) renderSubmission(detail);
    }
    return upload;
  }

  async function selectUpload(uploadId, keepSubmission = false) {
    if (!keepSubmission) {
      images.clear();
      state.submissionId = null;
      state.modelNextAction = null;
      state.modelActive = false;
      $('#submission-id-short').textContent = '尚未选择';
      $('#submission-detail').replaceChildren(makeText('p', '从左侧选择一条前端任务。', 'lab-muted'));
      $('#cover-task-state').textContent = '选择任务后可准备本地交接包。';
      $('#prepare-cover-task').disabled = true;
    }
    state.uploadId = uploadId;
    clearFrames();
    await pollCurrent();
    await refreshList();
  }

  function uploadContent(uploadId, file) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', `/api/uploads/${uploadId}/content`);
      xhr.setRequestHeader('Authorization', `Bearer ${token()}`);
      xhr.upload.onprogress = event => {
        if (event.lengthComputable) $('#upload-progress').value = Math.round(100 * event.loaded / event.total);
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch {}
        log(`PUT /api/uploads/${uploadId}/content · ${xhr.status}`, data);
        xhr.status >= 200 && xhr.status < 300 ? resolve(data) : reject(new Error(data.detail?.code || `上传失败：HTTP ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error('上传连接中断。'));
      xhr.send(file);
    });
  }

  async function uploadFile() {
    const file = $('#video-file').files[0];
    if (!file) throw new Error('请选择一个视频。');
    const contentType = file.type || ({ mov: 'video/quicktime', mp4: 'video/mp4', webm: 'video/webm' })[file.name.split('.').pop().toLowerCase()];
    if (!contentType) throw new Error('请选择 MP4、MOV 或 WebM 视频。');
    $('#upload-button').disabled = true;
    $('#upload-progress').hidden = false;
    $('#upload-progress').value = 0;
    $('#upload-hint').textContent = '正在上传，请保持页面打开…';
    try {
      const created = await api('/api/uploads/init', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, content_type: contentType, byte_size: file.size })
      });
      await uploadContent(created.uploadId, file);
      await api(`/api/uploads/${created.uploadId}/complete`, { method: 'POST' });
      $('#upload-hint').textContent = '上传完成。现在可运行视频质检。';
      await selectUpload(created.uploadId);
    } finally {
      $('#upload-button').disabled = false;
    }
  }

  async function runValidation() {
    if (!state.uploadId) return;
    await api(`/api/internal/uploads/${state.uploadId}/validate`, { method: 'POST' });
    await pollCurrent();
    await refreshList();
  }

  async function submitDecision(approved) {
    if (!state.uploadId) return;
    const notes = $('#review-notes').value.trim();
    if (notes.length < 5) {
      $('#review-hint').textContent = '请先写至少 5 个字符的复核记录。';
      return;
    }
    $('#review-hint').textContent = '';
    await api(`/api/internal/uploads/${state.uploadId}/decision`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved, notes })
    });
    await pollCurrent();
    await refreshList();
    if (state.submissionId) await refreshSubmissions();
  }

  function onClick(selector, task) {
    $(selector).addEventListener('click', async () => {
      try { await task(); } catch (error) { showError(error); }
    });
  }

  $('#video-file').addEventListener('change', () => {
    const file = $('#video-file').files[0];
    $('#file-label').textContent = file ? file.name : '选择测试视频';
    $('#upload-button').disabled = !file || $('#connection-state').textContent !== '已连接';
  });
  onClick('#connect-button', async () => {
    await api('/api/internal/connect', { method: 'POST' });
    await Promise.all([refreshList(), refreshSubmissions(), refreshTemplates(), refreshWorkerStatus()]);
    setConnected();
    await pollCurrent();
  });
  onClick('#refresh-submissions', refreshSubmissions);
  onClick('#refresh-templates', refreshTemplates);
  onClick('#refresh-button', refreshList);
  onClick('#upload-button', uploadFile);
  onClick('#validate-button', runValidation);
  onClick('#approve-button', () => submitDecision(true));
  onClick('#recapture-button', () => submitDecision(false));
  onClick('#model-button', async () => {
    if (!state.submissionId) throw new Error('请先选择一条前端提交的任务。');
    await api(`/api/internal/submissions/${state.submissionId}/model-jobs`, { method: 'POST' });
    await pollCurrent();
  });
  onClick('#prepare-cover-task', async () => {
    if (!state.submissionId) throw new Error('请先选择前端任务。');
    const template_id = $('#cover-template').value;
    await api(`/api/internal/submissions/${state.submissionId}/cover-task`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({template_id})
    });
    await showSubmission(state.submissionId);
  });
  for (const [button, action] of [
    ['#prepare-hunyuan', 'prepare'], ['#submit-hunyuan', 'submit'],
    ['#poll-hunyuan', 'poll'], ['#archive-hunyuan', 'archive']
  ]) onClick(button, async () => {
    if (!state.submissionId) throw new Error('请先选择前端任务。');
    await api(`/api/internal/submissions/${state.submissionId}/hunyuan/${action}`, {method:'POST'});
    await showSubmission(state.submissionId);
  });
  onClick('#prepare-print-candidate', async () => {
    if (!state.submissionId) throw new Error('请先选择前端任务。');
    await api(`/api/internal/submissions/${state.submissionId}/print-candidate/prepare`, {method:'POST'});
    await showSubmission(state.submissionId);
  });
  onClick('#approve-cover-registration', async () => {
    if (!state.submissionId) throw new Error('请先选择前端任务。');
    const payload = JSON.parse($('#cover-registration-json').value);
    await api(`/api/internal/submissions/${state.submissionId}/cover/registration`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
    });
    await showSubmission(state.submissionId);
  });
  onClick('#build-cover-concept', async () => {
    if (!state.submissionId) throw new Error('请先选择前端任务。');
    const proposal = JSON.parse($('#cover-proposal-json').value);
    await api(`/api/internal/submissions/${state.submissionId}/cover/concept/build`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({candidate_id:$('#cover-candidate-id').value.trim(), proposal})
    });
    await showSubmission(state.submissionId);
  });
  onClick('#load-ruler-frames', async () => {
    const frames = await api(`/api/internal/submissions/${state.submissionId}/ruler/frames`);
    const select = $('#ruler-frame');
    select.replaceChildren();
    for (const frame of frames.items) {
      const option = document.createElement('option');
      option.value = frame.name;
      option.textContent = frame.name;
      select.append(option);
    }
    select.dispatchEvent(new Event('change'));
    $('#ruler-click-state').textContent = `已加载 ${frames.items.length} 张。选取视角差异明显且标尺端点清晰的图片。`;
  });
  $('#ruler-frame').addEventListener('change', () => {
    const name = $('#ruler-frame').value;
    state.rulerClicks = [];
    state.rulerSuggestion = null;
    $('#accept-ruler-marks').disabled = true;
    $('#ruler-marker-a').style.display = 'none';
    $('#ruler-marker-b').style.display = 'none';
    const image = $('#ruler-frame-image');
    image.hidden = !name;
    if (name) setImage(image, `/api/internal/submissions/${state.submissionId}/ruler/frames/${name}`);
    $('#ruler-click-state').textContent = state.rulerMarks.has(name) ? `${name} 已标注，重新点击可覆盖。` : `${name}：请先点击 A，再点击 B。`;
  });
  onClick('#suggest-ruler-marks', async () => {
    const name = $('#ruler-frame').value;
    if (!state.submissionId || !name) throw new Error('请先加载建模帧。');
    const result = await api(`/api/internal/submissions/${state.submissionId}/ruler/suggestions/${name}`);
    state.rulerSuggestion = result.suggestedPair?.length === 2 ? {name, A:result.suggestedPair[0].point, B:result.suggestedPair[1].point} : null;
    $('#accept-ruler-marks').disabled = !state.rulerSuggestion;
    for (const marker of ['A', 'B']) {
      const dot = $(`#ruler-marker-${marker.toLowerCase()}`);
      dot.style.display = state.rulerSuggestion ? 'block' : 'none';
      if (state.rulerSuggestion) {
        dot.style.left = `${state.rulerSuggestion[marker][0] / result.imageSize[0] * 100}%`;
        dot.style.top = `${state.rulerSuggestion[marker][1] / result.imageSize[1] * 100}%`;
      }
    }
    $('#ruler-click-state').textContent = state.rulerSuggestion
      ? `候选 A（红）${state.rulerSuggestion.A.join(', ')} / B（蓝）${state.rulerSuggestion.B.join(', ')}。请检查红蓝始终对应同一枚物理标靶，再确认；不准确时手动点击覆盖。`
      : '本帧未可靠找到两枚标靶，请手动点击或换帧。';
  });
  const renderRulerMarks = () => {
    const list = $('#ruler-mark-list');
    list.replaceChildren();
    for (const row of state.rulerMarks.values()) list.append(makeText('li', `${row.name}: A ${row.A.join(', ')} / B ${row.B.join(', ')}`));
    $('#calibrate-ruler').disabled = state.rulerMarks.size < 3;
  };
  onClick('#accept-ruler-marks', async () => {
    if (!state.rulerSuggestion || state.rulerSuggestion.name !== $('#ruler-frame').value) throw new Error('当前帧没有可确认标点。');
    const row = state.rulerSuggestion;
    state.rulerMarks.set(row.name, row);
    $('#ruler-click-state').textContent = `${row.name} 已确认；请继续其他相机位置。`;
    renderRulerMarks();
  });
  $('#ruler-frame-image').addEventListener('click', event => {
    const image = event.currentTarget;
    if (!image.naturalWidth || !image.naturalHeight) return;
    const rect = image.getBoundingClientRect();
    const point = [+(event.offsetX * image.naturalWidth / rect.width).toFixed(2),
                   +(event.offsetY * image.naturalHeight / rect.height).toFixed(2)];
    state.rulerClicks.push(point);
    const name = $('#ruler-frame').value;
    if (state.rulerClicks.length === 1) {
      $('#ruler-click-state').textContent = `${name}：A = ${point.join(', ')}；现在点击 B。`;
      return;
    }
    state.rulerMarks.set(name, {name, A: state.rulerClicks[0], B: state.rulerClicks[1]});
    state.rulerClicks = [];
    state.rulerSuggestion = null;
    $('#accept-ruler-marks').disabled = true;
    $('#ruler-marker-a').style.display = 'none';
    $('#ruler-marker-b').style.display = 'none';
    $('#ruler-click-state').textContent = `${name} 已标注 A/B；可换一张图继续。`;
    renderRulerMarks();
  });
  onClick('#calibrate-ruler', async () => {
    await api(`/api/internal/submissions/${state.submissionId}/ruler/calibrate`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({images:[...state.rulerMarks.values()]})
    });
    await showSubmission(state.submissionId);
  });
  onClick('#prepare-views', async () => {
    await api(`/api/internal/submissions/${state.submissionId}/views/prepare`, {method:'POST'});
    await showSubmission(state.submissionId);
  });
  onClick('#classify-views', async () => {
    const front = $('[data-slot="front"]')?.value || null;
    await api(`/api/internal/submissions/${state.submissionId}/views/classify`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({front_anchor:front})
    });
    await showSubmission(state.submissionId);
  });
  onClick('#save-views', async () => {
    const selections = {};
    for (const select of document.querySelectorAll('#view-selectors select')) if (select.value) selections[select.dataset.slot] = select.value;
    await api(`/api/internal/submissions/${state.submissionId}/views/selection`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({selections, notes:$('#view-notes').value.trim()})
    });
    await showSubmission(state.submissionId);
  });
  state.poll = setInterval(() => {
    if (state.uploadId && (state.pollActive || state.modelActive || state.viewActive) && (cloudHosted || $('#dev-token').value.trim())) pollCurrent().catch(() => {});
  }, 3000);
  if (cloudHosted) {
    $('#connect-button').closest('.lab-card').hidden = true;
    $('#video-file').closest('.lab-card').hidden = true;
    $('.lab-badge').textContent = 'CLOUD ADMIN';
    const home = document.createElement('a');
    home.href = '/admin.html';
    home.textContent = '返回管理平台';
    $('.site-header').append(home);
    Promise.all([refreshList(), refreshSubmissions(), refreshTemplates(), refreshWorkerStatus()])
      .then(() => { setConnected(); pollCurrent().catch(() => {}); })
      .catch(showError);
  }
  window.addEventListener('beforeunload', () => { clearFrames(); images.clear(); });
})();

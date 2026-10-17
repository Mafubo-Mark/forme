const { test } = require('node:test');
const assert = require('node:assert/strict');
const Loader = require('../operator/js/media-loader.js');
const urls = () => ({ createObjectURL: () => 'blob:test-image', revokeObjectURL: () => {} });
const jpeg = () => new Response(new Uint8Array([255, 216, 255, 217]), { headers: { 'Content-Type': 'image/jpeg' } });

test('failed image does not prevent other frames; retries are possible', async () => {
  let badAttempts = 0;
  const loader = new Loader({ objectUrls: urls(), fetchImage: async path => {
    if (path === '/bad' && badAttempts++ === 0) return new Response('{}', { status: 503 });
    return jpeg();
  } });
  const results = await Promise.allSettled([loader.get('/bad'), loader.get('/good')]);
  assert.equal(results[0].status, 'rejected');
  assert.equal(results[1].status, 'fulfilled');
  assert.equal(await loader.get('/bad'), 'blob:test-image');
});

test('sends authentication and limits concurrent image transfers', async () => {
  let active = 0, peak = 0, calls = 0;
  const loader = new Loader({ objectUrls: urls(), concurrency: 3,
    headers: () => ({ Authorization: 'Bearer test-only' }),
    fetchImage: async (_path, options) => {
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.headers.Authorization, 'Bearer test-only');
      calls++; peak = Math.max(peak, ++active);
      await new Promise(resolve => setTimeout(resolve, 2));
      active--; return jpeg();
    }
  });
  await Promise.all(Array.from({ length: 18 }, (_, i) => loader.get('/frame/' + i)));
  assert.equal(peak, 3);
  await loader.get('/frame/0');
  assert.equal(calls, 18, 'rerender reuses the already loaded image');
});

test('an expired admin session is reported explicitly instead of treating JSON as an image', async () => {
  const loader = new Loader({ objectUrls: urls(), fetchImage: async () => new Response('{}', { status: 401 }) });
  await assert.rejects(loader.get('/frame'), error => error.status === 401 && error.message === 'SESSION_REQUIRED');
});

test('a stalled body times out and releases the queue', async () => {
  const loader = new Loader({ objectUrls: urls(), concurrency: 1, timeout: 15,
    fetchImage: async (path, options) => path === '/slow' ? {
      ok: true, headers: new Headers({ 'Content-Type': 'image/jpeg' }),
      blob: () => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Timeout', 'AbortError'))))
    } : jpeg()
  });
  const result = await Promise.allSettled([loader.get('/slow'), loader.get('/next')]);
  assert.equal(result[0].reason.name, 'AbortError');
  assert.equal(result[1].status, 'fulfilled');
});

test('switching tasks discards pending images and revokes loaded URLs', async () => {
  const revoked = [];
  const loader = new Loader({ objectUrls: { createObjectURL: () => 'blob:old', revokeObjectURL: url => revoked.push(url) },
    fetchImage: async () => jpeg()
  });
  await loader.get('/frame');
  loader.clear();
  assert.deepEqual(revoked, ['blob:old']);
  assert.equal(loader.entries.size, 0);
});

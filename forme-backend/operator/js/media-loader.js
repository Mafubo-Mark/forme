/* Authenticated, bounded image requests. A failed frame never blocks the gallery. */
(() => {
  'use strict';
  class OperatorMediaLoader {
    constructor({ headers = () => ({}), concurrency = 3, timeout = 20000,
      fetchImage = (...args) => fetch(...args), objectUrls = URL } = {}) {
      this.headers = headers;
      this.concurrency = concurrency;
      this.timeout = timeout;
      this.fetchImage = fetchImage;
      this.objectUrls = objectUrls;
      this.pending = [];
      this.running = 0;
      this.entries = new Map();
      this.urls = new Set();
      this.controllers = new Set();
      this.generation = 0;
    }
    get(path) {
      if (this.entries.has(path)) return this.entries.get(path);
      const generation = this.generation;
      const promise = new Promise((resolve, reject) => {
        this.pending.push({ path, generation, resolve, reject });
      });
      this.entries.set(path, promise);
      // Rejected promises may be retried. Successful images stay in page memory.
      promise.catch(() => { if (this.entries.get(path) === promise) this.entries.delete(path); });
      this.pump();
      return promise;
    }
    pump() {
      while (this.running < this.concurrency && this.pending.length) {
        const task = this.pending.shift();
        this.running++;
        this.run(task).then(task.resolve, task.reject).finally(() => {
          this.running--;
          this.pump();
        });
      }
    }
    async run(task) {
      const controller = new AbortController();
      this.controllers.add(controller);
      const timeout = setTimeout(() => controller.abort(), this.timeout);
      try {
        const response = await this.fetchImage(task.path, {
          credentials: 'same-origin', headers: this.headers(), cache: 'no-store', signal: controller.signal
        });
        if (!response.ok) {
          const error = new Error(response.status === 401 ? 'SESSION_REQUIRED' : `HTTP ${response.status}`);
          error.status = response.status;
          throw error;
        }
        if (!/^image\//i.test(response.headers.get('Content-Type') || '')) throw new Error('INVALID_IMAGE_RESPONSE');
        const blob = await response.blob();
        if (!blob.size) throw new Error('EMPTY_IMAGE');
        if (task.generation !== this.generation) throw new Error('STALE_IMAGE');
        const url = this.objectUrls.createObjectURL(blob);
        this.urls.add(url);
        return url;
      } finally {
        clearTimeout(timeout);
        this.controllers.delete(controller);
      }
    }
    clear() {
      this.generation++;
      for (const controller of this.controllers) controller.abort();
      for (const task of this.pending.splice(0)) task.reject(new Error('STALE_IMAGE'));
      for (const url of this.urls) this.objectUrls.revokeObjectURL(url);
      this.urls.clear();
      this.entries.clear();
    }
  }
  if (typeof module !== 'undefined') module.exports = OperatorMediaLoader;
  else window.OperatorMediaLoader = OperatorMediaLoader;
})();

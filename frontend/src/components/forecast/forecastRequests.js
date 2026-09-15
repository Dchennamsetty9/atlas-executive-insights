const METADATA_PATHS = new Set(['/api/forecast/v2/models', '/api/forecast/v2/freshness']);

export function createForecastRequests(get, { now = Date.now, metadataTtl = 300_000 } = {}) {
  const metadata = new Map();
  let current = null;

  return {
    start({ force = false } = {}) {
      current?.abort();
      const controller = new AbortController();
      current = controller;
      const pending = new Map();
      if (force) metadata.clear();

      return {
        isCurrent: () => current === controller && !controller.signal.aborted,
        cancel: () => controller.abort(),
        get(url, config = {}) {
          const params = Object.entries(config.params ?? {}).sort(([left], [right]) => left.localeCompare(right));
          const key = JSON.stringify([url, params]);
          const cached = metadata.get(key);
          if (cached && now() - cached.time < metadataTtl) return Promise.resolve(cached.value);
          if (pending.has(key)) return pending.get(key);

          const request = Promise.resolve().then(() => {
            controller.signal.throwIfAborted();
            return get(url, { ...config, signal: controller.signal });
          }).then(value => {
            controller.signal.throwIfAborted();
            if (METADATA_PATHS.has(url) && value?.source !== 'demo' && !value?.error) {
              metadata.set(key, { time: now(), value });
            }
            return value;
          });
          pending.set(key, request);
          return request;
        },
      };
    },
  };
}
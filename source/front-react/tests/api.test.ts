import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { makeApi } from '@/services/api';
import { loaderStore } from '@/lib/loaderStore';
import { alertStore } from '@/lib/alertStore';

const originalFetch = globalThis.fetch;

function setupFetch(response: { status: number; ok: boolean; body?: string }) {
  globalThis.fetch = (async () =>
    ({
      status: response.status,
      statusText: response.status === 200 ? 'OK' : 'Error',
      ok: response.ok,
      headers: {},
      text: async () => response.body ?? '',
    } as Response)) as typeof fetch;
}

test('makeApi sends requests with CSRF header and toggles loader', async () => {
  const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return {
      status: 200,
      statusText: 'OK',
      ok: true,
      headers: {},
      text: async () => JSON.stringify({ ok: true }),
    } as Response;
  }) as typeof fetch;

  const loaderEvents: string[] = [];
  const originalStart = loaderStore.start;
  const originalStop = loaderStore.stop;
  loaderStore.start = () => loaderEvents.push('start');
  loaderStore.stop = () => loaderEvents.push('stop');

  document.cookie = 'csrftoken=test-token';

  const api = makeApi('/api');
  const result = await api('/example/', {
    method: 'POST',
    body: JSON.stringify({ foo: 'bar' }),
  });

  assert.deepEqual(result, { ok: true });
  assert.equal(calls.length, 1);
  const { url, init } = calls[0];
  assert.equal(url, '/api/example/');
  const headers = init?.headers as Record<string, string>;
  assert.equal(headers['Content-Type'], 'application/json');
  assert.equal(headers['X-CSRFToken'], 'test-token');
  assert.deepEqual(loaderEvents, ['start', 'stop']);

  loaderStore.start = originalStart;
  loaderStore.stop = originalStop;
  globalThis.fetch = originalFetch;
});

test('makeApi handles 401 redirect suppression with alert', async () => {
  setupFetch({ status: 401, ok: false, body: 'unauthorized' });

  const events: Array<{ type: string; detail?: unknown }> = [];
  const originalDispatch = window.dispatchEvent;
  window.dispatchEvent = (event) => {
    const custom = event as CustomEvent;
    events.push({ type: custom.type, detail: custom.detail });
    return true;
  };

  const api = makeApi('/api');
  let error: unknown;
  try {
    await api('/session/', {
      noAuthRedirect: true,
      noLoader: true,
    });
  } catch (err) {
    error = err;
  }

  assert.ok(error instanceof Error);
  assert.equal((error as Error & { status?: number }).status, 401);
  assert.deepEqual(events[0], { type: 'auth:unauthorized', detail: { status: 401 } });

  window.dispatchEvent = originalDispatch;
  globalThis.fetch = originalFetch;
});

test('makeApi redirects to login when unauthorized without suppression', async () => {
  setupFetch({ status: 401, ok: false });
  const originalHref = window.location.href;

  const api = makeApi('/api');
  let error: unknown;
  try {
    await api('/needs-login/');
  } catch (err) {
    error = err;
  }

  assert.ok(error instanceof Error);
  assert.equal(window.location.href, '/');

  window.location.href = originalHref;
  globalThis.fetch = originalFetch;
});

test('makeApi surfaces non-JSON responses in raw field', async () => {
  setupFetch({ status: 200, ok: true, body: 'plain text' });
  document.cookie = 'csrftoken=token';

  const api = makeApi('/api');
  const result = await api('/text/', { noLoader: true });

  assert.deepEqual(result, { raw: 'plain text' });
  globalThis.fetch = originalFetch;
});

test('makeApi notifies alert store on non-ok responses', async () => {
  setupFetch({ status: 500, ok: false, body: 'Server exploded' });
  const alerts: string[] = [];
  const originalPush = alertStore.push;
  alertStore.push = (message) => {
    alerts.push(message.message);
    return 'id';
  };

  const api = makeApi('/api');
  let error: unknown;
  try {
    await api('/boom/', { noLoader: true });
  } catch (err) {
    error = err;
  }

  assert.ok(error instanceof Error);
  assert.equal(alerts[0], 'Server exploded');

  alertStore.push = originalPush;
  globalThis.fetch = originalFetch;
});

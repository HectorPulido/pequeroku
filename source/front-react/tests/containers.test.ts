import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import {
  listContainers,
  createContainer,
  deleteContainer,
  powerOnContainer,
  powerOffContainer,
  fetchContainerStatistics,
} from '@/services/containers';
import { loaderStore } from '@/lib/loaderStore';

type FetchInvocation = {
  url: string;
  init?: RequestInit;
};

function captureFetch(response: unknown, opts: { status?: number } = {}) {
  const calls: FetchInvocation[] = [];
  const { status = 200 } = opts;
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return {
      status,
      statusText: status === 200 || status === 201 ? 'OK' : 'Error',
      ok: status >= 200 && status < 300,
      headers: {},
      text: async () => JSON.stringify(response),
    } as Response;
  }) as typeof fetch;
  return calls;
}

function withLoaderSpy() {
  const originalStart = loaderStore.start;
  const originalStop = loaderStore.stop;
  const counters = { start: 0, stop: 0 };
  loaderStore.start = () => {
    counters.start += 1;
  };
  loaderStore.stop = () => {
    counters.stop += 1;
  };
  return {
    counters,
    restore() {
      loaderStore.start = originalStart;
      loaderStore.stop = originalStop;
    },
  };
}

test('listContainers skips loader when suppressLoader is true', async () => {
  const mockResponse = [
    {
      id: 1,
      name: 'vm',
      created_at: '2024-01-01T00:00:00Z',
      status: 'running',
      username: 'demo',
      container_type_name: 'default',
    },
  ];
  const fetchCalls = captureFetch(mockResponse);
  const loaderSpy = withLoaderSpy();

  const result = await listContainers();

  loaderSpy.restore();

  assert.deepEqual(result, mockResponse);
  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0]?.url, '/api/containers/');
  assert.equal(loaderSpy.counters.start, 0);
  assert.equal(loaderSpy.counters.stop, 0);
});

test('listContainers triggers loader when suppressLoader is false', async () => {
  captureFetch([]);
  const loaderSpy = withLoaderSpy();

  await listContainers({ suppressLoader: false });

  loaderSpy.restore();
  assert.equal(loaderSpy.counters.start, 1);
  assert.equal(loaderSpy.counters.stop, 1);
});

test('container mutation helpers call the expected endpoints', async () => {
  const fetchCalls = captureFetch({}, { status: 201 });

  await createContainer({ container_type: 1, container_name: 'new-vm' });
  await powerOnContainer(5);
  await powerOffContainer(5, { force: true });
  await deleteContainer(5);

  const urls = fetchCalls.map((call) => call.url);

  assert.deepEqual(urls, [
    '/api/containers/',
    '/api/containers/5/power_on/',
    '/api/containers/5/power_off/',
    '/api/containers/5/',
  ]);

  const createCall = fetchCalls[0];
  assert.equal(createCall?.init?.method, 'POST');
  assert.equal(createCall?.init?.body, JSON.stringify({ container_type: 1, container_name: 'new-vm' }));

  const powerOffCall = fetchCalls[2];
  assert.equal(powerOffCall?.init?.body, JSON.stringify({ force: true }));
});

test('fetchContainerStatistics normalizes API payload', async () => {
  const unixTs = 1_700_000_000;
  const payload = {
    cpu_percent: 27.5,
    rss_bytes: 104_857_600,
    num_threads: 12,
    ts: unixTs,
  };
  const fetchCalls = captureFetch(payload);

  const result = await fetchContainerStatistics(42);

  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0]?.url, '/api/containers/42/statistics/');
  assert.equal(result.cpu, 27.5);
  assert.equal(result.memory, 100);
  assert.equal(result.threads, 12);
  assert.equal(new Date(result.timestamp).getTime(), unixTs * 1000);
});

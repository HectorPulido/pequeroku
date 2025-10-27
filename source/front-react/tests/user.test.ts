import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { fetchCurrentUser } from '@/services/user';
import { loaderStore } from '@/lib/loaderStore';

type FetchCall = { url: string; init: RequestInit | undefined };

function withPatchedLoader<T>(fn: () => Promise<T> | T) {
  const originalStart = loaderStore.start;
  const originalStop = loaderStore.stop;
  const counts = { start: 0, stop: 0 };
  loaderStore.start = () => {
    counts.start += 1;
  };
  loaderStore.stop = () => {
    counts.stop += 1;
  };
  const finalize = () => {
    loaderStore.start = originalStart;
    loaderStore.stop = originalStop;
  };
  return {
    counts,
    run: async () => {
      try {
        return await fn();
      } finally {
        finalize();
      }
    },
  };
}

test('fetchCurrentUser resolves with parsed user payload', async () => {
  const fakeUser = {
    username: 'hector',
    is_superuser: false,
    active_containers: 2,
    has_quota: true,
    quota: {
      credits: 10,
      credits_left: 5,
      ai_use_per_day: 3,
      ai_uses_left_today: 2,
      active: true,
      allowed_types: [],
    },
  };

  const calls: FetchCall[] = [];
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return {
      status: 200,
      statusText: 'OK',
      ok: true,
      headers: {},
      text: async () => JSON.stringify(fakeUser),
    } as Response;
  }) as typeof fetch;

  const runner = withPatchedLoader(async () => fetchCurrentUser());
  const result = await runner.run();

  assert.deepEqual(result, fakeUser);
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.url, '/api/user/me/');
  assert.equal(runner.counts.start, 0);
  assert.equal(runner.counts.stop, 0);
});

test('fetchCurrentUser rejects when the payload is not a valid user', async () => {
  globalThis.fetch = (async () =>
    ({
      status: 200,
      statusText: 'OK',
      ok: true,
      headers: {},
      text: async () => '<html>login</html>',
    }) as Response) as typeof fetch;

  const runner = withPatchedLoader(async () => fetchCurrentUser());
  let error: unknown;
  try {
    await runner.run();
  } catch (err) {
    error = err;
  }

  assert.ok(error instanceof Error, 'Expected an error to be thrown');
  assert.equal((error as Error & { status?: number }).status, 401);
  assert.equal(runner.counts.start, 0);
  assert.equal(runner.counts.stop, 0);
});

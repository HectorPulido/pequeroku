import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { fetchCurrentUser } from '@/services/user';
import { loaderStore } from '@/lib/loaderStore';
import { mockFetchCurrentUser } from '@/mocks/dashboard';

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

test('fetchCurrentUser resolves with mocked user payload without toggling loader', async () => {
  const expected = await mockFetchCurrentUser();

  const runner = withPatchedLoader(async () => fetchCurrentUser());
  const result = await runner.run();

  assert.deepEqual(result, expected);
  assert.notStrictEqual(result, expected);
  assert.notStrictEqual(result.quota, expected.quota);
  assert.equal(runner.counts.start, 0);
  assert.equal(runner.counts.stop, 0);
});

test('fetchCurrentUser returns fresh clones across invocations', async () => {
  const firstRun = withPatchedLoader(async () => fetchCurrentUser());
  const first = await firstRun.run();

  first.quota.allowed_types[0]!.credits_cost = 999;
  first.quota.credits = -1;

  const second = await fetchCurrentUser();

  assert.equal(firstRun.counts.start, 0);
  assert.equal(firstRun.counts.stop, 0);
  assert.equal(second.quota.credits >= 0, true);
  assert.notStrictEqual(first, second);
  assert.notStrictEqual(first.quota, second.quota);
  assert.notStrictEqual(first.quota.allowed_types, second.quota.allowed_types);
  assert.notEqual(second.quota.allowed_types[0]?.credits_cost, 999);
});

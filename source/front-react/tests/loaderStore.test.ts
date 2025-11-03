import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { loaderStore } from '@/lib/loaderStore';

test('loaderStore increments and decrements active counter', () => {
  const events: number[] = [];
  const unsubscribe = loaderStore.subscribe((event) => events.push(event.active));

  loaderStore.start();
  loaderStore.start();
  loaderStore.stop();
  loaderStore.stop();
  loaderStore.stop(); // cannot go below zero

  unsubscribe();

  assert.deepEqual(events, [1, 2, 1, 0, 0]);
});

import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { FSWS, METRICS } from '@/constants';

test('constants expose filesystem websocket defaults', () => {
  assert.equal(typeof FSWS.waitOpenIntervalMs, 'number');
  assert.equal(typeof FSWS.openTimeoutMs, 'number');
  assert.equal(typeof FSWS.callTimeoutMs, 'number');
});

test('constants expose metrics polling configuration', () => {
  assert.equal(typeof METRICS.pollMs, 'number');
  assert.equal(typeof METRICS.maxPoints, 'number');
  assert.ok(METRICS.pollMs > 0);
  assert.ok(METRICS.maxPoints > 0);
});

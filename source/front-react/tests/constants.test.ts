import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { FSWS } from '@/constants';

test('constants expose filesystem websocket defaults', () => {
  assert.equal(typeof FSWS.waitOpenIntervalMs, 'number');
  assert.equal(typeof FSWS.openTimeoutMs, 'number');
  assert.equal(typeof FSWS.callTimeoutMs, 'number');
});

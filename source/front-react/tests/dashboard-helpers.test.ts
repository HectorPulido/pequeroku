import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { formatDate, statusTone } from '@/pages/Dashboard.helpers';

test('statusTone maps statuses to tone classes', () => {
  assert.equal(statusTone('running'), 'text-emerald-300');
  assert.equal(statusTone('STOPPED'), 'text-amber-300');
  assert.equal(statusTone('error'), 'text-rose-300');
  assert.equal(statusTone('pending'), 'text-sky-300');
});

test('formatDate handles invalid input gracefully', () => {
  const formatted = formatDate('2024-05-01T10:00:00Z');
  assert.ok(formatted.includes('2024'));
  assert.equal(formatDate('not-a-date'), 'Invalid Date');
});

import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { alertStore } from '@/lib/alertStore';

test('alertStore emits alerts with generated ids', () => {
  const events: unknown[] = [];
  const unsubscribe = alertStore.subscribe((event) => events.push(event));

  const id = alertStore.push({ message: 'Hello', variant: 'info' });

  assert.equal(events.length, 1);
  const event = events[0] as { id: string; message: string; variant: string };
  assert.equal(event.message, 'Hello');
  assert.equal(event.variant, 'info');
  assert.equal(typeof event.id, 'string');
  assert.equal(event.id, id);

  unsubscribe();
});

test('alertStore dismiss propagates dismiss events', () => {
  const events: unknown[] = [];
  const unsubscribe = alertStore.subscribe((event) => events.push(event));

  const id = alertStore.push({ message: 'Will dismiss', variant: 'warning' });
  alertStore.dismiss(id);

  const dismissEvent = events.find((item) => 'dismiss' in (item as Record<string, unknown>));
  assert.ok(dismissEvent);
  assert.deepEqual(dismissEvent, { id, dismiss: true });

  unsubscribe();
});

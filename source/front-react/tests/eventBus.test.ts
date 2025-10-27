import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { EventBus } from '@/lib/eventBus';

test('EventBus notifies subscribers in order and allows unsubscribe', () => {
  const bus = new EventBus<number>();
  const received: number[] = [];
  const unsub = bus.subscribe((value) => received.push(value));
  const other: number[] = [];
  bus.subscribe((value) => other.push(value));

  bus.emit(1);
  unsub();
  bus.emit(2);

  assert.deepEqual(received, [1]);
  assert.deepEqual(other, [1, 2]);
});

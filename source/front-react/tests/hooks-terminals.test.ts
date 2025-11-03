import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { generateTerminalId } from '@/hooks/useTerminals';

test('generateTerminalId produces sequential session ids', () => {
  assert.equal(generateTerminalId(0), 's1');
  assert.equal(generateTerminalId(5), 's6');
});

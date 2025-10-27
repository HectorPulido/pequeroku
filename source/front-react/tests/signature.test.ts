import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { signatureFrom } from '@/lib/signature';

test('signatureFrom serializes simple objects deterministically', () => {
  const value = { a: 1, b: { c: 2 } };
  const signature = signatureFrom(value);
  assert.equal(signature, '{"a":1,"b":{"c":2}}');
});

test('signatureFrom falls back when value is not serializable', () => {
  const circular: Record<string, unknown> = {};
  circular.self = circular;

  const signatureA = signatureFrom(circular);
  const signatureB = signatureFrom(circular);

  assert.notEqual(signatureA, '{"self":{}}');
  assert.equal(signatureA.length, signatureB.length);
});

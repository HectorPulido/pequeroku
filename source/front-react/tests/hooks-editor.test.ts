import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { getOrCreateTab } from '@/hooks/useEditor';

test('getOrCreateTab reuses existing tab when path matches', () => {
  const prev = [
    { id: '1', title: 'foo.ts', path: '/app/foo.ts' },
    { id: '2', title: 'bar.ts', path: '/app/bar.ts' },
  ];

  const result = getOrCreateTab(prev, '/app/bar.ts', 999);

  assert.deepEqual(result, {
    tabs: prev,
    activeId: '2',
    reused: true,
  });
});

test('getOrCreateTab creates new tab with generated id and title', () => {
  const prev = [{ id: '1', title: 'foo.ts', path: '/app/foo.ts' }];
  const result = getOrCreateTab(prev, '/app/src/new.ts', 123456789);

  assert.equal(result.reused, false);
  assert.equal(result.activeId, '123456789');
  assert.deepEqual(result.tabs, [
    prev[0],
    { id: '123456789', title: 'new.ts', path: '/app/src/new.ts', isDirty: false },
  ]);
});

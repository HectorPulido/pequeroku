import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { buildFileTreeFromEntries, performFileAction } from '@/hooks/useFileTree';
import type { FileNode } from '@/types/ide';

test('buildFileTreeFromEntries nests folders and files correctly', () => {
  const tree = buildFileTreeFromEntries([
    { name: 'src', path: '/app/src', path_type: 'folder' },
    { name: 'index.ts', path: '/app/src/index.ts', path_type: 'file' },
    { name: 'README.md', path: '/app/README.md', path_type: 'file' },
  ]);

  assert.equal(tree.length, 1);
  const root = tree[0];
  assert.equal(root.name, 'app');
  assert.equal(root.children?.length, 2);
  const srcFolder = root.children?.find((node: FileNode) => node.name === 'src');
  assert.ok(srcFolder);
  assert.equal(srcFolder?.children?.[0].name, 'index.ts');
});

test('performFileAction executes delete action when confirmed', async () => {
  const calls: Array<{ action: string; payload: Record<string, unknown> }> = [];
  const fs = { call: async (action: string, payload: Record<string, unknown>) => calls.push({ action, payload }) };
  let refreshed = 0;

  await performFileAction('delete', '/app/foo.txt', 'file', fs, () => {
    refreshed += 1;
  }, {
    confirm: () => true,
    prompt: () => null,
  });

  assert.deepEqual(calls, [{ action: 'delete_path', payload: { path: '/app/foo.txt' } }]);
  assert.equal(refreshed, 1);
});

test('performFileAction skips delete when cancelled', async () => {
  const fs = { call: async () => { throw new Error('should not call'); } };

  await performFileAction('delete', '/app/foo.txt', 'file', fs, () => {}, {
    confirm: () => false,
    prompt: () => null,
  });
});

test('performFileAction handles rename and new entries with proper destinations', async () => {
  const calls: Array<{ action: string; payload: Record<string, unknown> }> = [];
  const fs = { call: async (action: string, payload: Record<string, unknown>) => calls.push({ action, payload }) };

  await performFileAction('rename', '/app/foo.txt', 'file', fs, () => {}, {
    confirm: () => true,
    prompt: () => 'bar.txt',
  });

  await performFileAction('new-file', '/app/src', 'folder', fs, () => {}, {
    confirm: () => true,
    prompt: () => 'new.ts',
  });

  await performFileAction('new-folder', '/app/src/index.ts', 'file', fs, () => {}, {
    confirm: () => true,
    prompt: () => 'components',
  });

  assert.deepEqual(calls, [
    { action: 'move_path', payload: { src: '/app/foo.txt', dst: '/app/bar.txt' } },
    { action: 'write', payload: { path: '/app/src/new.ts', content: '' } },
    { action: 'create_dir', payload: { path: '/app/src/components' } },
  ]);
});

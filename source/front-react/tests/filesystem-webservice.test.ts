import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import FileSystemWebService from '@/services/ide/FileSystemWebService';

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test('FileSystemWebService call provides mock filesystem operations', async () => {
  const service = new FileSystemWebService('fs-1');

  const listing = await service.call<{
    entries: Array<{ name: string; path: string; path_type: string }>;
  }>('list_dirs', { path: '/app' });

  const names = listing.entries.map((entry) => entry.name).sort();
  assert.ok(names.includes('src'));
  assert.ok(names.includes('readme.txt'));

  await service.call('write', { path: '/app/tmp.txt', content: 'hello mock fs' });
  const readBack = await service.call<{ content: string }>('read', { path: '/app/tmp.txt' });
  assert.equal(readBack.content, 'hello mock fs');

  await service.call('delete_path', { path: '/app/tmp.txt' });
  const afterDelete = await service.call<{ content: string }>('read', { path: '/app/tmp.txt' });
  assert.equal(afterDelete.content, '');
});

test('FileSystemWebService broadcasts mock events and supports unsubscribe', async () => {
  const service = new FileSystemWebService('fs-2');
  const received: Array<Record<string, unknown>> = [];

  const unsubscribe = service.onBroadcast((event) => {
    received.push(event);
  });

  await delay(0);
  await service.call('create_dir', { path: '/app/new-folder' });
  assert.ok(received.some((event) => event.event === 'connected'));
  assert.ok(received.some((event) => event.event === 'path_created'));

  unsubscribe();
  const countAfterUnsubscribe = received.length;
  await service.call('delete_path', { path: '/app/new-folder' });
  await delay(0);
  assert.equal(received.length, countAfterUnsubscribe);
});

test('FileSystemWebService search returns matches from the mock filesystem', async () => {
  const service = new FileSystemWebService('fs-3');
  await service.call('write', {
    path: '/app/search-demo.txt',
    content: 'Search me\nThis line mentions loader\nAnother line',
  });

  const results = await service.search({ pattern: 'loader' });
  const match = results.find((item) => item.path.endsWith('search-demo.txt'));

  assert.ok(match);
  assert.equal(match?.matches.length, 1);
  assert.equal(match?.matches[0]?.preview.includes('loader'), true);

  await service.call('delete_path', { path: '/app/search-demo.txt' });
});

import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import FileSystemWebService from '@/services/ide/FileSystemWebService';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  emitOk(reqId: number, data: unknown) {
    this.onmessage?.({ data: JSON.stringify({ event: 'ok', req_id: reqId, data }) });
  }

  emitError(reqId: number, message: string) {
    this.onmessage?.({ data: JSON.stringify({ event: 'error', req_id: reqId, error: message }) });
  }

  emitBroadcast(payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
  }
}

test('FileSystemWebService call resolves when ok event is received', async (t) => {
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  const originalLocation = globalThis.location;
  globalThis.location = { protocol: 'https:', host: 'example.test' } as unknown as Location;
  t.after(() => {
    MockWebSocket.instances.length = 0;
    globalThis.WebSocket = originalWebSocket;
    globalThis.location = originalLocation;
  });

  const service = new FileSystemWebService('123');
  const socket = MockWebSocket.instances.at(-1)!;
  socket.open();

  const promise = service.call('list_dirs', { path: '/app' });

  assert.equal(socket.sent.length, 1);
  const message = JSON.parse(socket.sent[0]);
  assert.equal(message.action, 'list_dirs');
  assert.equal(message.path, '/app');

  socket.emitOk(message.req_id, { entries: [{ name: 'file.txt' }] });

  const response = await promise;
  assert.deepEqual(response, { entries: [{ name: 'file.txt' }] });
});

test('FileSystemWebService call rejects when error event is received', async (t) => {
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  const originalLocation = globalThis.location;
  globalThis.location = { protocol: 'https:', host: 'example.test' } as unknown as Location;
  t.after(() => {
    MockWebSocket.instances.length = 0;
    globalThis.WebSocket = originalWebSocket;
    globalThis.location = originalLocation;
  });

  const service = new FileSystemWebService('234');
  const socket = MockWebSocket.instances.at(-1)!;
  socket.open();

  const promise = service.call('read', { path: '/missing' });
  const message = JSON.parse(socket.sent[0]);

  socket.emitError(message.req_id, 'not found');

	await assert.rejects(promise, /not found/);
});

test('FileSystemWebService notifies broadcast listeners', async (t) => {
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  const originalLocation = globalThis.location;
  globalThis.location = { protocol: 'http:', host: 'example.test' } as unknown as Location;
  t.after(() => {
    MockWebSocket.instances.length = 0;
    globalThis.WebSocket = originalWebSocket;
    globalThis.location = originalLocation;
  });

  const service = new FileSystemWebService('345');
  const socket = MockWebSocket.instances.at(-1)!;
  socket.open();

  const received: Record<string, unknown>[] = [];
  const unsubscribe = service.onBroadcast((message) => {
    received.push(message);
  });

  socket.emitBroadcast({ event: 'path_created', path: '/app/demo.txt' });
  assert.equal(received.length, 1);
  assert.equal(received[0].event, 'path_created');

  unsubscribe();
  socket.emitBroadcast({ event: 'path_deleted', path: '/app/demo.txt' });
  assert.equal(received.length, 1);
});

test('FileSystemWebService search normalizes results payloads', async (t) => {
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  const originalLocation = globalThis.location;
  globalThis.location = { protocol: 'https:', host: 'search.test' } as unknown as Location;
  t.after(() => {
    MockWebSocket.instances.length = 0;
    globalThis.WebSocket = originalWebSocket;
    globalThis.location = originalLocation;
  });

  const service = new FileSystemWebService('789');
  const socket = MockWebSocket.instances.at(-1)!;
  socket.open();

  const promise = service.search({
    pattern: 'useFileTree',
    includeGlobs: 'src/**/*.ts',
    excludeDirs: '.git,.venv',
    caseSensitive: true,
  });

  assert.equal(socket.sent.length, 1);
  const outbound = JSON.parse(socket.sent[0]);
  assert.equal(outbound.action, 'search');
  assert.equal(outbound.pattern, 'useFileTree');
  assert.equal(outbound.include_globs, 'src/**/*.ts');
  assert.equal(outbound.exclude_dirs, '.git,.venv');
  assert.equal(outbound.case, 'false');

  socket.emitOk(outbound.req_id, {
    results: [
      {
        path: '/app/src/hooks/useFileTree.ts',
        matches: ['L10: import { useCallback }', 'L42: return { fileTree };'],
      },
    ],
  });

  const results = await promise;
  assert.equal(results.length, 1);
  assert.equal(results[0]?.path, '/app/src/hooks/useFileTree.ts');
  assert.deepEqual(results[0]?.matches?.[0], { line: 10, preview: 'import { useCallback }' });
});

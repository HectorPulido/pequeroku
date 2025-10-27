import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import TerminalWebService from '@/services/ide/TerminalWebService';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static OPEN = 1;
  readyState = MockWebSocket.OPEN;
  url: string;
  binaryType: string | undefined;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onopen: (() => void) | null = null;
  sent: Array<string | ArrayBuffer> = [];
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    this.onopen?.();
  }

  send(payload: string | ArrayBuffer) {
    this.sent.push(payload);
  }

  close() {
    this.closed = true;
  }

  emitMessage(data: string | ArrayBuffer) {
    this.onmessage?.({ data } as MessageEvent);
  }
}

test('TerminalWebService send respects readyState and forwards payloads', () => {
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  MockWebSocket.instances.length = 0;
  const originalLocation = globalThis.location;
  globalThis.location = { protocol: 'https:', host: 'example.test' } as unknown as Location;

  const service = new TerminalWebService('999', 'sid-1');
  const socket = MockWebSocket.instances.at(-1)!;

  service.send('hello');
  assert.deepEqual(socket.sent, ['hello']);

  socket.readyState = 0; // not open
  service.send('ignored');
  assert.deepEqual(socket.sent, ['hello']);

  service.close();
  assert.equal(socket.closed, true);

  globalThis.WebSocket = originalWebSocket;
  globalThis.location = originalLocation;
});

test('TerminalWebService onMessage registers handler', () => {
  const originalWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  MockWebSocket.instances.length = 0;
  const originalLocation = globalThis.location;
  globalThis.location = { protocol: 'https:', host: 'example.test' } as unknown as Location;

  const service = new TerminalWebService('1000', 'sid-2');
  const socket = MockWebSocket.instances.at(-1)!;

  let payload: unknown;
  service.onMessage((event) => {
    payload = event.data;
  });

  socket.emitMessage('data');
  assert.equal(payload, 'data');

  globalThis.WebSocket = originalWebSocket;
  globalThis.location = originalLocation;
});

import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import TerminalWebService from '@/services/ide/TerminalWebService';

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test('TerminalWebService mock reports readiness and echoes text input', async () => {
  const service = new TerminalWebService('999', 'sid-1');
  const messages: Array<unknown> = [];

  service.onMessage((event) => {
    messages.push(event.data);
  });

  await delay(25);
  assert.equal(service.isConnected(), true);
  assert.ok(
    messages.some(
      (message) => typeof message === 'string' && message.toString().includes('Terminal session ready'),
    ),
  );

  service.send('help\n');
  await delay(80);
  assert.ok(
    messages.some(
      (message) => typeof message === 'string' && message.toString().includes('you typed: help'),
    ),
  );

  service.close();
  assert.equal(service.hasConnection(), false);
});

test('TerminalWebService mock handles binary payloads and disconnects cleanly', async () => {
  const service = new TerminalWebService('1000', 'sid-2');
  const received: Array<unknown> = [];

  service.onMessage((event) => {
    received.push(event.data);
  });

  await delay(25);
  const buffer = new Uint8Array([1, 2, 3]).buffer;
  service.send(buffer);
  await delay(80);

  assert.ok(
    received.some(
      (message) =>
        typeof message === 'string' &&
        message.toString().includes('[mock terminal received binary data]'),
    ),
  );

  service.close();
  assert.equal(service.isConnected(), false);
});

import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import {
  listContainers,
  createContainer,
  deleteContainer,
  powerOnContainer,
  powerOffContainer,
  fetchContainerStatistics,
} from '@/services/containers';
import { loaderStore } from '@/lib/loaderStore';

function withLoaderSpy() {
  const originalStart = loaderStore.start;
  const originalStop = loaderStore.stop;
  const counters = { start: 0, stop: 0 };
  loaderStore.start = () => {
    counters.start += 1;
  };
  loaderStore.stop = () => {
    counters.stop += 1;
  };
  return {
    counters,
    restore() {
      loaderStore.start = originalStart;
      loaderStore.stop = originalStop;
    },
  };
}

test('listContainers returns mock data without toggling the loader', async () => {
  const loaderSpy = withLoaderSpy();
  try {
    const containers = await listContainers();
    const names = containers.map((container) => container.name).sort();

    assert.deepEqual(names, ['dev-shell', 'playground', 'shared-tools']);
    assert.equal(loaderSpy.counters.start, 0);
    assert.equal(loaderSpy.counters.stop, 0);

    await listContainers({ suppressLoader: false });
    assert.equal(loaderSpy.counters.start, 0);
    assert.equal(loaderSpy.counters.stop, 0);
  } finally {
    loaderSpy.restore();
  }
});

test('container mutation helpers update mock state and keep loader idle', async () => {
  const baseline = await listContainers();
  const baselineCount = baseline.length;

  const loaderSpy = withLoaderSpy();
  try {
    await createContainer({ container_type: 1, container_name: 'new-vm' });
    const afterCreate = await listContainers();
    assert.equal(afterCreate.length, baselineCount + 1);

    const created = afterCreate.find((item) => item.name === 'new-vm');
    assert.ok(created);

    await powerOnContainer(created!.id);
    const afterPowerOn = await listContainers();
    const powered = afterPowerOn.find((item) => item.id === created!.id);
    assert.equal(powered?.status, 'running');

    await powerOffContainer(created!.id, { force: true });
    const afterPowerOff = await listContainers();
    const stopped = afterPowerOff.find((item) => item.id === created!.id);
    assert.equal(stopped?.status, 'stopped');

    await deleteContainer(created!.id);
    const finalContainers = await listContainers();
    assert.equal(finalContainers.length, baselineCount);
  } finally {
    loaderSpy.restore();
  }
});

test('fetchContainerStatistics returns plausible metrics in mock mode', async () => {
  const [container] = await listContainers();
  assert.ok(container);

  const loaderSpy = withLoaderSpy();
  try {
    const metrics = await fetchContainerStatistics(container!.id);
    const parsedTimestamp = Date.parse(metrics.timestamp);

    assert.equal(typeof metrics.cpu, 'number');
    assert.equal(typeof metrics.memory, 'number');
    assert.equal(typeof metrics.threads, 'number');
    assert.ok(metrics.cpu >= 0 && metrics.cpu <= 100);
    assert.ok(metrics.memory >= 0);
    assert.ok(metrics.threads >= 0);
    assert.ok(Number.isFinite(parsedTimestamp));
    assert.equal(loaderSpy.counters.start, 0);
    assert.equal(loaderSpy.counters.stop, 0);
  } finally {
    loaderSpy.restore();
  }
});

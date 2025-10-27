import { test } from 'node:test';
import { strict as assert } from 'node:assert';

const STORAGE_KEY = 'pequeroku:theme';

async function loadThemeModule() {
  // Ensure fresh dataset and storage
  window.localStorage.clear();
  Object.keys(document.documentElement.dataset).forEach((key) => {
    delete document.documentElement.dataset[key as keyof DOMStringMap];
  });
  return import('@/lib/theme');
}

test('themeManager.set persists theme and dispatches event', async () => {
  const { themeManager } = await loadThemeModule();
  const dispatched: string[] = [];
  const originalDispatch = window.dispatchEvent;
  window.dispatchEvent = (event) => {
    dispatched.push(event.type);
    return true;
  };

  themeManager.set('light');

  assert.equal(themeManager.get(), 'light');
  assert.equal(window.localStorage.getItem(STORAGE_KEY), 'light');
  assert.equal(document.documentElement.dataset.theme, 'light');
  assert.ok(dispatched.includes('themechange'));

  window.dispatchEvent = originalDispatch;
});

test('themeManager.toggle cycles values and notifies subscribers', async () => {
  const { themeManager } = await loadThemeModule();
  const received: string[] = [];
  const unsubscribe = themeManager.subscribe((value) => received.push(value));

  themeManager.set('dark');
  themeManager.toggle();
  themeManager.toggle();

  unsubscribe();

  assert.deepEqual(received.slice(-2), ['light', 'dark']);
});

import { webcrypto } from 'node:crypto';

if (typeof globalThis.crypto === 'undefined') {
  globalThis.crypto = webcrypto;
}

if (typeof globalThis.window === 'undefined') {
  globalThis.window = {
    location: { href: '' },
    dispatchEvent() {},
    addEventListener() {},
    removeEventListener() {},
  };
}

const localStorageStore = new Map();
globalThis.window.localStorage = {
  getItem(key) {
    return localStorageStore.has(key) ? localStorageStore.get(key) : null;
  },
  setItem(key, value) {
    localStorageStore.set(key, String(value));
  },
  removeItem(key) {
    localStorageStore.delete(key);
  },
  clear() {
    localStorageStore.clear();
  },
};

globalThis.window.matchMedia = (query) => ({
  matches: false,
  media: query,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  onchange: null,
});

if (!globalThis.window.dispatchEvent) {
  globalThis.window.dispatchEvent = () => true;
}

if (typeof globalThis.CustomEvent === 'undefined') {
  globalThis.CustomEvent = class CustomEvent {
    constructor(type, init = {}) {
      this.type = type;
      this.detail = init.detail;
    }
  };
}

if (typeof globalThis.document === 'undefined') {
  globalThis.document = {
    cookie: '',
    documentElement: { dataset: {} },
  };
} else {
  globalThis.document.documentElement = globalThis.document.documentElement || { dataset: {} };
}

if (!globalThis.document.dispatchEvent) {
  globalThis.document.dispatchEvent = () => true;
}

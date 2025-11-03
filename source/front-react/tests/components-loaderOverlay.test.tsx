import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { renderToStaticMarkup } from 'react-dom/server';

import { LoaderOverlayView } from '@/components/LoaderOverlay';

test('LoaderOverlayView renders spinner when active', () => {
  const markup = renderToStaticMarkup(<LoaderOverlayView activeCount={2} />);
  assert.match(markup, /animate-spin/);
});

test('LoaderOverlayView returns null when no active requests', () => {
  const markup = renderToStaticMarkup(<LoaderOverlayView activeCount={0} />);
  assert.equal(markup, '');
});

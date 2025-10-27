import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { renderToStaticMarkup } from 'react-dom/server';

import Button from '@/components/Button';

test('Button renders with variant and icon', () => {
  const markup = renderToStaticMarkup(
    <Button variant="primary" icon={<span>!</span>}>
      Submit
    </Button>,
  );

  assert.match(markup, /Submit/);
  assert.match(markup, /bg-indigo-600/);
  assert.match(markup, /!/);
});

test('Button respects disabled state', () => {
  const markup = renderToStaticMarkup(
    <Button variant="secondary" disabled>
      Disabled
    </Button>,
  );

  assert.match(markup, /disabled/);
  assert.match(markup, /bg-gray-700/);
});

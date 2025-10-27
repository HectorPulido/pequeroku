import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { renderToStaticMarkup } from 'react-dom/server';

import AlertStackView from '@/components/AlertStackView';
import { variantClasses } from '@/components/AlertStack.constants';

test('AlertStackView renders alerts with variant classes and dismiss button', () => {
  const markup = renderToStaticMarkup(
    <AlertStackView
      alerts={[
        { id: '1', message: 'Hello', variant: 'info', dismissible: true },
        { id: '2', message: 'Error', variant: 'error', dismissible: false },
      ]}
      onDismiss={() => {}}
    />,
  );

  assert.match(markup, /Hello/);
  assert.match(markup, new RegExp(variantClasses.info));
  assert.match(markup, new RegExp(variantClasses.error));
  assert.match(markup, /Close/);
});

test('AlertStackView returns null when there are no alerts', () => {
  const markup = renderToStaticMarkup(<AlertStackView alerts={[]} onDismiss={() => {}} />);
  assert.equal(markup, '');
});

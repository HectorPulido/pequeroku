import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const projectRoot = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..');
const buildRoot = path.resolve(projectRoot, 'build-tests');
const buildRootUrl = pathToFileURL(buildRoot + path.sep);
const JS_EXTENSIONS = new Set(['.js', '.json', '.node', '.mjs']);

function resolveAlias(specifier) {
  const relativePath = specifier.slice(2); // remove '@/'
  const withExtension = relativePath.endsWith('.js') ? relativePath : `${relativePath}.js`;
  return new URL(`src/${withExtension}`, buildRootUrl).href;
}

export async function resolve(specifier, context, defaultResolve) {
  if (specifier.startsWith('@/')) {
    return { url: resolveAlias(specifier), shortCircuit: true };
  }
  if ((specifier.startsWith('./') || specifier.startsWith('../')) && !JS_EXTENSIONS.has(path.extname(specifier))) {
    const resolvedUrl = new URL(`${specifier}.js`, context.parentURL);
    return { url: resolvedUrl.href, shortCircuit: true };
  }
  return defaultResolve(specifier, context, defaultResolve);
}

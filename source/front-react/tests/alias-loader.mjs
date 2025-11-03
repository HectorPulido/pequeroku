import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const projectRoot = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..');
const buildRoot = path.resolve(projectRoot, 'build-tests');
const buildRootUrl = pathToFileURL(buildRoot + path.sep);

const JS_EXTENSIONS = new Set(['.js', '.mjs', '.cjs', '.json', '.node']);
const PASSTHROUGH_EXTENSIONS = new Set(['.css']);

function shouldAppendJs(extension) {
  if (!extension) return true;
  if (PASSTHROUGH_EXTENSIONS.has(extension)) return false;
  return !JS_EXTENSIONS.has(extension);
}

function resolveAlias(specifier) {
  const relativePath = specifier.slice(2); // remove '@/'
  const extension = path.extname(relativePath);
  if (extension === '.css') {
    return 'data:text/javascript,export default {};';
  }
  const targetPath = shouldAppendJs(extension) ? `${relativePath}.js` : relativePath;
  return new URL(`src/${targetPath}`, buildRootUrl).href;
}

function resolveRelative(specifier, parentURL) {
  const extension = path.extname(specifier);
  if (extension === '.css') {
    return 'data:text/javascript,export default {};';
  }
  if (shouldAppendJs(extension)) {
    return new URL(`${specifier}.js`, parentURL).href;
  }
  return new URL(specifier, parentURL).href;
}

export async function resolve(specifier, context, defaultResolve) {
  if (specifier.endsWith('.css')) {
    return { url: 'data:text/javascript,export default {};', shortCircuit: true };
  }
  if (specifier.startsWith('@/')) {
    return { url: resolveAlias(specifier), shortCircuit: true };
  }
  if (specifier.startsWith('./') || specifier.startsWith('../')) {
    return { url: resolveRelative(specifier, context.parentURL), shortCircuit: true };
  }
  return defaultResolve(specifier, context, defaultResolve);
}

export async function load(url, context, defaultLoad) {
  if (url === 'data:text/javascript,export default {};') {
    return {
      format: 'module',
      source: 'export default {};',
      shortCircuit: true,
    };
  }
  return defaultLoad(url, context, defaultLoad);
}

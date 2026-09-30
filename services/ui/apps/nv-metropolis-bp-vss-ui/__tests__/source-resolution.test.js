// SPDX-License-Identifier: MIT
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ts = require('typescript');

const app = path.resolve(__dirname, '..');

function loadConfig(name, mode = 'development') {
  const module = { exports: {} };
  vm.runInNewContext(fs.readFileSync(path.join(app, name), 'utf8'), {
    module,
    __dirname: app,
    process: { env: { NODE_ENV: mode } },
    require: name => {
      if (name === 'next-runtime-env/build/configure') return { configureRuntimeEnv: () => ({}) };
      if (name === './next-i18next.config') return { i18n: {} };
      return require(name);
    },
  });
  return module.exports;
}

function compilerOptions(configName) {
  const configPath = path.join(app, configName);
  const config = ts.readConfigFile(configPath, ts.sys.readFile);
  if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, '\n'));
  return ts.parseJsonConfigFileContent(config.config, ts.sys, app).options;
}

function resolve(name, options) {
  return ts.resolveModuleName(name, path.join(app, 'pages/index.tsx'), options, ts.sys).resolvedModule;
}

test('Turbopack aliases resolve actual source files without built workspace exports', () => {
  const aliases = loadConfig('next.config.js').turbopack.resolveAlias;
  expect(aliases['@nemo-agent-toolkit/ui/server']).toMatch(/dev-server\.ts$/);
  for (const target of Object.values(aliases)) {
    if (target.includes('*')) {
      expect(fs.statSync(path.resolve(app, target.split('*')[0])).isDirectory()).toBe(true);
    } else {
      expect(fs.statSync(path.resolve(app, target)).isFile()).toBe(true);
      expect(target).toContain('/lib-src/');
    }
  }
});

test('app typecheck preserves strictness and consumes source plus the existing Nemo contracts', () => {
  const options = compilerOptions('tsconfig.json');
  expect(options.strict).toBe(true);
  expect(resolve('@aiqtoolkit-ui/common', options).resolvedFileName).toMatch(/lib-src\/index\.ts$/);
  expect(resolve('@nv-metropolis-bp-vss-ui/all/server', options).resolvedFileName).toMatch(/lib-src\/server\.ts$/);
  expect(resolve('@nemo-agent-toolkit/ui', options).resolvedFileName).toMatch(/lib-src\/index\.d\.ts$/);
  expect(resolve('@nemo-agent-toolkit/ui/server', options).resolvedFileName).toMatch(/lib-src\/server\.d\.ts$/);
  expect(resolve('@/components/Chat/ChatInteractionMessage', options).resolvedFileName).toMatch(/components\/Chat\/ChatInteractionMessage\.tsx$/);
  expect(resolve('@/utils/data/throttle', options).resolvedFileName).toMatch(/utils\/data\/throttle\.ts$/);
  expect(resolve('@/contexts/RuntimeConfigContext', options).resolvedFileName).toMatch(/lib-src\/contexts\/RuntimeConfigContext\.tsx$/);
  expect(resolve('@nonexistent/workspace', options)).toBeUndefined();
});

test('the separate implementation check resolves Nemo development source entries', () => {
  const options = compilerOptions('tsconfig.source.json');
  expect(options.strict).toBe(true);
  expect(resolve('@nemo-agent-toolkit/ui', options).resolvedFileName).toMatch(/lib-src\/dev-index\.ts$/);
  expect(resolve('@nemo-agent-toolkit/ui/server', options).resolvedFileName).toMatch(/lib-src\/dev-server\.ts$/);
});

test('development Nemo exports target existing source files before any package build', () => {
  const folder = path.resolve(app, '../../packages/nemo-agent-toolkit-ui/lib-src');
  for (const entry of ['dev-index.ts', 'dev-server.ts']) {
    const source = ts.createSourceFile(entry, fs.readFileSync(path.join(folder, entry), 'utf8'), ts.ScriptTarget.Latest);
    for (const statement of source.statements) {
      const target = statement.moduleSpecifier?.text;
      if (!target?.startsWith('.')) continue;
      const absolute = path.resolve(folder, target);
      expect(['', '.ts', '.tsx', '.js'].some(extension => fs.existsSync(absolute + extension))).toBe(true);
    }
  }
});

test('development locales exist and production retains its packaged path', () => {
  const dev = loadConfig('next-i18next.config.js');
  expect(fs.statSync(path.join(dev.localePath, 'en/common.json')).isFile()).toBe(true);
  const prod = loadConfig('next-i18next.config.js', 'production');
  expect(prod.localePath).toMatch(/node_modules\/@nemo-agent-toolkit\/ui\/lib\/public\/locales$/);
});

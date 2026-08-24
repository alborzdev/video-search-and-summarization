// SPDX-License-Identifier: MIT
const typescriptParser = require('@typescript-eslint/parser');
const nextPlugin = require('@next/eslint-plugin-next');
const reactHooks = require('eslint-plugin-react-hooks');

module.exports = [
  {
    ignores: ['.next/**', 'node_modules/**'],
  },
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      parser: typescriptParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    plugins: {
      '@next/next': nextPlugin,
      'react-hooks': reactHooks,
    },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs['core-web-vitals'].rules,
      // Evidence frames and posters are transient blob/local-gateway URLs;
      // routing them through Next's image optimizer would add a second media
      // path and break the appliance's offline origin contract.
      '@next/next/no-img-element': 'off',
      // Kaizen is a versioned, local vendor stylesheet loaded in _document so
      // its primitives exist before either embedded workspace hydrates.
      '@next/next/no-css-tags': 'off',
      'no-debugger': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react-hooks/rules-of-hooks': 'error',
    },
  },
];

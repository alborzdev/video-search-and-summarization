// SPDX-License-Identifier: MIT
const { configureRuntimeEnv } = require('next-runtime-env/build/configure');
const { i18n } = require('./next-i18next.config');
const path = require('path');

const nextConfig = {
  env: {
    ...configureRuntimeEnv(),
  },
  i18n,
  allowedDevOrigins: [
    'localhost',
    // The offline desktop launcher opens the gateway on IPv4 loopback.
    // Without this origin Next rejects HMR and its reconnect loop reloads
    // the entire page, discarding in-progress questions and rule drafts.
    '127.0.0.1',
    '[::1]',
    ...[process.env.NEXT_PUBLIC_VST_API_URL]
      .filter(Boolean)
      .map(url => new URL(url).hostname),
  ],
  devIndicators: false,
  turbopack: {
    resolveAlias: {
      '@/contexts/*': '../../packages/nemo-agent-toolkit-ui/lib-src/contexts/*',
      '@/*': '../../packages/nemo-agent-toolkit-ui/*',
      '@nemo-agent-toolkit/ui': '../../packages/nemo-agent-toolkit-ui/lib-src/dev-index.ts',
      '@nemo-agent-toolkit/ui/server': '../../packages/nemo-agent-toolkit-ui/lib-src/dev-server.ts',
      ...Object.fromEntries([
        ['@aiqtoolkit-ui/common', 'common'],
        ...['all', 'alerts', 'search', 'dashboard', 'map', 'video-management'].map(name => [`@nv-metropolis-bp-vss-ui/${name}`, `nv-metropolis-bp-vss-ui/${name}`]),
      ].flatMap(([name, folder]) => {
        const source = path.resolve(__dirname, '../../packages', folder, 'lib-src');
        return [
          [name, `../../packages/${folder}/lib-src/index.ts`],
          ...(require('fs').existsSync(path.join(source, 'server.ts')) ? [[`${name}/server`, `../../packages/${folder}/lib-src/server.ts`]] : []),
        ];
      })),
    },
  },
  output: 'standalone',
  // Transpile packages from source for hot reload during development
  transpilePackages: [
    '@aiqtoolkit-ui/common',
    '@nv-metropolis-bp-vss-ui/all',
    '@nv-metropolis-bp-vss-ui/alerts',
    '@nv-metropolis-bp-vss-ui/search',
    '@nv-metropolis-bp-vss-ui/dashboard',
    '@nv-metropolis-bp-vss-ui/map',
    '@nv-metropolis-bp-vss-ui/video-management',
    '@nemo-agent-toolkit/ui',
  ],
  experimental: {
    serverActions: {
      bodySizeLimit: '5mb',
    },
  },
  webpack(config, { isServer, dev }) {
    config.experiments = {
      asyncWebAssembly: true,
      layers: true,
    };

    // In development, resolve packages to their source code for hot reload
    if (dev) {
      const path = require('path');
      const packagesPath = path.resolve(__dirname, '../../packages');

      config.resolve.alias = {
        ...config.resolve.alias,
        '@/contexts': path.join(packagesPath, 'nemo-agent-toolkit-ui/lib-src/contexts'),
        '@': path.join(packagesPath, 'nemo-agent-toolkit-ui'),
        '@nemo-agent-toolkit/ui$': path.join(packagesPath, 'nemo-agent-toolkit-ui/lib-src/dev-index.ts'),
        '@nemo-agent-toolkit/ui/server$': path.join(packagesPath, 'nemo-agent-toolkit-ui/lib-src/dev-server.ts'),
        '@aiqtoolkit-ui/common': path.join(packagesPath, 'common/lib-src'),
        '@nv-metropolis-bp-vss-ui/alerts': path.join(packagesPath, 'nv-metropolis-bp-vss-ui/alerts/lib-src'),
        '@nv-metropolis-bp-vss-ui/search': path.join(packagesPath, 'nv-metropolis-bp-vss-ui/search/lib-src'),
        '@nv-metropolis-bp-vss-ui/dashboard': path.join(packagesPath, 'nv-metropolis-bp-vss-ui/dashboard/lib-src'),
        '@nv-metropolis-bp-vss-ui/map': path.join(packagesPath, 'nv-metropolis-bp-vss-ui/map/lib-src'),
        '@nv-metropolis-bp-vss-ui/video-management': path.join(packagesPath, 'nv-metropolis-bp-vss-ui/video-management/lib-src'),
        '@nv-metropolis-bp-vss-ui/all': path.join(packagesPath, 'nv-metropolis-bp-vss-ui/all/lib-src'),
      };
    }

    return config;
  },
  async redirects() {
    return [];
  },
};

module.exports = nextConfig;

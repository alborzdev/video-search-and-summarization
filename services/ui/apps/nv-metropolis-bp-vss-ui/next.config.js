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
    ...[process.env.NEXT_PUBLIC_VST_API_URL]
      .filter(Boolean)
      .map(url => new URL(url).hostname),
  ],
  devIndicators: false,
  turbopack: {
    resolveAlias: Object.fromEntries([
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

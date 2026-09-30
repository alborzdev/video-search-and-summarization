// SPDX-License-Identifier: MIT
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  moduleNameMapper: {
    '^@nemo-agent-toolkit/ui$': '<rootDir>/../../packages/nemo-agent-toolkit-ui/lib-src/dev-index.ts',
    '^@nemo-agent-toolkit/ui/server$': '<rootDir>/../../packages/nemo-agent-toolkit-ui/lib-src/dev-server.ts',
    '^@nv-metropolis-bp-vss-ui/(all|alerts|search|dashboard|map|video-management)$': '<rootDir>/../../packages/nv-metropolis-bp-vss-ui/$1/lib-src/index.ts',
    '^@nv-metropolis-bp-vss-ui/(all|alerts|search|dashboard|map|video-management)/server$': '<rootDir>/../../packages/nv-metropolis-bp-vss-ui/$1/lib-src/server.ts',
    '^@aiqtoolkit-ui/common$': '<rootDir>/../../packages/common/lib-src/index.ts',
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
    '^next/router$': '<rootDir>/__mocks__/next-router.js',
    '^next-runtime-env$': '<rootDir>/__mocks__/next-runtime-env.js',
  },
  testMatch: [
    '**/__tests__/**/*.(ts|tsx|js)',
    '**/*.(test|spec).(ts|tsx|js)',
  ],
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx'],
  transform: {
    '^.+\\.(ts|tsx)$': ['ts-jest', {
      tsconfig: {
        jsx: 'react',
      },
    }],
  },
  collectCoverageFrom: [
    'utils/**/*.{ts,tsx}',
    'hooks/**/*.{ts,tsx}',
    'components/**/*.{ts,tsx}',
    '!**/*.d.ts',
    '!**/node_modules/**',
  ],
  clearMocks: true,
  restoreMocks: true,
};

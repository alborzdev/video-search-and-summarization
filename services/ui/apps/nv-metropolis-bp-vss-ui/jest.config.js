// SPDX-License-Identifier: MIT
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  moduleNameMapper: {
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

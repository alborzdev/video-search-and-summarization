// SPDX-License-Identifier: MIT

const router = {
  asPath: '/',
  back: jest.fn(),
  basePath: '',
  beforePopState: jest.fn(),
  events: {
    emit: jest.fn(),
    off: jest.fn(),
    on: jest.fn(),
  },
  isFallback: false,
  isLocaleDomain: false,
  isPreview: false,
  isReady: true,
  pathname: '/',
  prefetch: jest.fn().mockResolvedValue(undefined),
  push: jest.fn().mockResolvedValue(true),
  query: {},
  reload: jest.fn(),
  replace: jest.fn().mockResolvedValue(true),
  route: '/',
};

const useRouter = jest.fn(() => router);

function resetMockRouter() {
  router.asPath = '/';
  router.pathname = '/';
  router.query = {};
}

module.exports = { resetMockRouter, router, useRouter };

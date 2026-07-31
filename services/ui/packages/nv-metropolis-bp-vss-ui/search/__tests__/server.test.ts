// SPDX-License-Identifier: MIT

jest.mock('next-runtime-env', () => ({
  env: (name: string) => process.env[name],
}));

describe('search server data', () => {
  const originalFlag = process.env.NEXT_PUBLIC_SEARCH_TAB_MEDIA_WITH_OBJECTS_BBOX;

  afterEach(() => {
    if (originalFlag === undefined) {
      delete process.env.NEXT_PUBLIC_SEARCH_TAB_MEDIA_WITH_OBJECTS_BBOX;
    } else {
      process.env.NEXT_PUBLIC_SEARCH_TAB_MEDIA_WITH_OBJECTS_BBOX = originalFlag;
    }
    jest.resetModules();
  });

  it.each([
    ['true', true],
    ['false', false],
    ['TRUE', false],
    ['', false],
  ])('parses the Search by Image flag %p as %p', async (rawValue, expected) => {
    process.env.NEXT_PUBLIC_SEARCH_TAB_MEDIA_WITH_OBJECTS_BBOX = rawValue;

    const { fetchSearchData } = await import('../lib-src/server');
    const result = await fetchSearchData();

    expect(result.mediaWithObjectsBbox).toBe(expected);
  });
});

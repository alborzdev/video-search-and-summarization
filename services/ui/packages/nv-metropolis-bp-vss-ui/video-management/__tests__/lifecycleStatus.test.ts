// SPDX-License-Identifier: MIT
import { addRtspStream, deleteRtspStream } from '../lib-src/rtspStream';
import { deleteVideo } from '../lib-src/videoDelete';


const response = (body: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 500,
  statusText: ok ? 'OK' : 'Internal Server Error',
  json: async () => body,
  text: async () => JSON.stringify(body),
});


describe('owned lifecycle status validation', () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn();
    global.fetch = fetchMock;
  });

  it('accepts video deletion only for exact success and matching video_id', async () => {
    fetchMock.mockResolvedValue(
      response({ status: 'success', message: 'deleted', video_id: 'video-1' })
    );

    await expect(deleteVideo('http://127.0.0.1:8000/api/v1', 'video-1')).resolves.toEqual({
      status: 'success',
      message: 'deleted',
      video_id: 'video-1',
    });
  });

  it.each(['partial', 'failure', 'unknown', '', undefined])(
    'rejects HTTP-200 video deletion status %p',
    async (status) => {
      fetchMock.mockResolvedValue(
        response({ status, message: 'not complete', video_id: 'video-1' })
      );
      await expect(
        deleteVideo('http://127.0.0.1:8000/api/v1', 'video-1')
      ).rejects.toThrow();
    }
  );

  it('rejects a successful video response for a different identity', async () => {
    fetchMock.mockResolvedValue(
      response({ status: 'success', message: 'deleted', video_id: 'video-2' })
    );
    await expect(
      deleteVideo('http://127.0.0.1:8000/api/v1', 'video-1')
    ).rejects.toThrow();
  });

  it.each(['partial', 'failure', 'unknown', '', undefined])(
    'rejects HTTP-200 RTSP add status %p',
    async (status) => {
      fetchMock.mockResolvedValue(response({ status, message: 'not complete' }));
      await expect(
        addRtspStream('http://127.0.0.1:8000/api/v1', {
          sensorUrl: 'rtsp://127.0.0.1:8554/test',
          name: 'owned-stream',
        })
      ).rejects.toThrow();
    }
  );

  it('accepts RTSP add only for exact success', async () => {
    fetchMock.mockResolvedValue(
      response({ status: 'success', message: 'created', name: 'owned-stream', sensorId: 'sensor-owned' })
    );
    await expect(
      addRtspStream('http://127.0.0.1:8000/api/v1', {
        sensorUrl: 'rtsp://127.0.0.1:8554/test',
        name: 'owned-stream',
      })
    ).resolves.toMatchObject({ status: 'success', name: 'owned-stream', sensorId: 'sensor-owned' });
  });

  it('rejects RTSP add success without exact stable identity', async () => {
    for (const body of [
      { status: 'success', message: 'created', name: 'owned-stream' },
      { status: 'success', message: 'created', name: 'foreign-stream', sensorId: 'sensor-owned' },
      { status: 'success', message: 'created', name: 'owned-stream', sensorId: '' },
    ]) {
      fetchMock.mockResolvedValueOnce(response(body));
      await expect(
        addRtspStream('http://127.0.0.1:8000/api/v1', {
          sensorUrl: 'rtsp://127.0.0.1:8554/test',
          name: 'owned-stream',
        })
      ).rejects.toThrow();
    }
  });

  it.each(['partial', 'failure', 'unknown', '', undefined])(
    'rejects HTTP-200 RTSP deletion status %p',
    async (status) => {
      fetchMock.mockResolvedValue(
        response({ status, message: 'not complete', name: 'owned-stream' })
      );
      await expect(
        deleteRtspStream(
          'http://127.0.0.1:8000/api/v1',
          'owned-stream'
        )
      ).rejects.toThrow();
    }
  );

  it('accepts RTSP deletion only for exact success and matching name', async () => {
    fetchMock.mockResolvedValue(
      response({ status: 'success', message: 'deleted', name: 'owned-stream', sensorId: 'sensor-owned' })
    );
    await expect(
      deleteRtspStream('http://127.0.0.1:8000/api/v1', 'owned-stream')
    ).resolves.toEqual({
      status: 'success',
      message: 'deleted',
      name: 'owned-stream',
      sensorId: 'sensor-owned',
    });

    fetchMock.mockResolvedValue(
      response({ status: 'success', message: 'deleted', name: 'foreign-stream', sensorId: 'sensor-owned' })
    );
    await expect(
      deleteRtspStream('http://127.0.0.1:8000/api/v1', 'owned-stream')
    ).rejects.toThrow();
  });

  it('rejects RTSP deletion success without a stable identity', async () => {
    fetchMock.mockResolvedValue(
      response({ status: 'success', message: 'deleted', name: 'owned-stream' })
    );
    await expect(
      deleteRtspStream('http://127.0.0.1:8000/api/v1', 'owned-stream')
    ).rejects.toThrow();
  });
});

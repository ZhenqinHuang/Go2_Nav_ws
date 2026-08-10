import { describe, expect, it, vi } from 'vitest';
import { ConsoleClient } from './consoleClient';


function response(body: unknown = { ok: true }, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    blob: async () => new Blob(['map-bundle'], { type: 'application/zip' }),
  } as Response;
}


describe('ConsoleClient', () => {
  it('binds the default browser fetch to globalThis', async () => {
    const originalFetch = globalThis.fetch;
    const receivers = new Set<unknown>();
    globalThis.fetch = (function (this: unknown) {
      receivers.add(this);
      return Promise.resolve(
        response({ ok: true, csrf_token: 'csrf-browser' }),
      );
    }) as typeof fetch;

    try {
      const client = new ConsoleClient();
      await client.login('operator', 'secret');
      expect(receivers.has(globalThis)).toBe(true);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it('logs in on the same origin and attaches CSRF to mutations', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true, csrf_token: 'csrf-1' }))
      .mockResolvedValue(response());
    const client = new ConsoleClient(fetchMock as typeof fetch);

    await client.login('operator', 'secret');
    await client.acquireControl();
    await client.manual({ vx: 0.2, vy: 0.0, vyaw: -0.1 });

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/login');
    for (const call of fetchMock.mock.calls.slice(1)) {
      expect(String(call[0])).toMatch(/^\/api\//);
      expect((call[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe(
        'csrf-1',
      );
    }
  });

  it('uses fixed goal, waypoint, initial pose and cancel endpoints', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true, csrf_token: 'csrf-2' }))
      .mockResolvedValue(response());
    const client = new ConsoleClient(fetchMock as typeof fetch);
    await client.login('operator', 'secret');

    await client.navigateToPose({ x: 1, y: 2, yaw: 0.5 });
    await client.navigateThroughPoses([
      { x: 1, y: 2, yaw: 0.5 },
      { x: 3, y: 4, yaw: -0.5 },
    ]);
    await client.setInitialPose({ x: 0, y: 0, yaw: 0 });
    await client.cancelNavigation();

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      '/api/navigation/goal',
      '/api/navigation/waypoints',
      '/api/localization/initialpose',
      '/api/navigation/cancel',
    ]);
  });

  it('reads and updates navigation speed through the fixed endpoint', async () => {
    const speed = {
      linear: 0.25,
      angular: 0.60,
      limits: {
        linear_min: 0.05,
        linear_max: 0.60,
        angular_min: 0.10,
        angular_max: 1.40,
      },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true, csrf_token: 'csrf-speed' }))
      .mockResolvedValue(response(speed));
    const client = new ConsoleClient(fetchMock as typeof fetch);
    await client.login('operator', 'secret');

    await client.navigationSpeed();
    await client.setNavigationSpeed(0.10, 0.25);

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      '/api/navigation/system/speed',
      '/api/navigation/system/speed',
    ]);
    expect(fetchMock.mock.calls[2]?.[1]?.body).toBe(
      JSON.stringify({ linear: 0.10, angular: 0.25 }),
    );
    expect(
      (fetchMock.mock.calls[2]?.[1]?.headers as Record<string, string>)[
        'X-CSRF-Token'
      ],
    ).toBe('csrf-speed');
  });

  it('uses the normalized posture and emergency gateway endpoints', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true, csrf_token: 'csrf-pose' }))
      .mockResolvedValue(response());
    const client = new ConsoleClient(fetchMock as typeof fetch);
    await client.login('operator', 'secret');

    await client.setPosture('stand');
    await client.setPosture('lie', true);
    await client.emergencyStop();
    await client.resetEmergencyStop();

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      '/api/control/posture',
      '/api/control/posture',
      '/api/control/emergency-stop',
      '/api/control/reset-emergency-stop',
    ]);
    expect(fetchMock.mock.calls[2]?.[1]?.body).toBe(
      JSON.stringify({ posture: 'lie', confirm: true }),
    );
  });

  it('uses fixed mapping workflow endpoints with CSRF protection', async () => {
    const mappingState = {
      mapping_running: false,
      mapping_owned: false,
      lidar_running: true,
      session_pcd: null,
      last_pcd: null,
      message: 'ready',
      pointclouds: [],
      maps: [],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true, csrf_token: 'csrf-map' }))
      .mockResolvedValue(response(mappingState));
    const client = new ConsoleClient(fetchMock as typeof fetch);
    await client.login('operator', 'secret');

    await client.mappingStatus();
    await client.startMapping();
    await client.stopMapping();
    await client.convertMapping();

    expect(fetchMock.mock.calls.slice(1).map((call) => call[0])).toEqual([
      '/api/mapping/status',
      '/api/mapping/start',
      '/api/mapping/stop',
      '/api/mapping/convert',
    ]);
    for (const call of fetchMock.mock.calls.slice(2)) {
      expect((call[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe(
        'csrf-map',
      );
    }
  });

  it('downloads a selected Jetson map through a fixed same-origin endpoint', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true, csrf_token: 'csrf-map-file' }))
      .mockResolvedValueOnce(response());
    const client = new ConsoleClient(fetchMock as typeof fetch);
    await client.login('operator', 'secret');

    const bundle = await client.mappingMapBundle(
      'MID360_web_20260803_103915_map.yaml',
    );

    expect(bundle.type).toBe('application/zip');
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      '/api/mapping/maps/MID360_web_20260803_103915_map.yaml/bundle',
    );
    expect(fetchMock.mock.calls[1]?.[1]?.credentials).toBe('same-origin');
  });

  it('reports backend error text', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ ok: true, csrf_token: 'csrf-3' }))
      .mockResolvedValueOnce(
        response(
          {
            ok: false,
            code: 'nav2_unavailable',
            message: 'Nav2 unavailable',
            data: {},
          },
          503,
        ),
      );
    const client = new ConsoleClient(fetchMock as typeof fetch);
    await client.login('operator', 'secret');

    await expect(
      client.navigateToPose({ x: 1, y: 2, yaw: 0 }),
    ).rejects.toThrow('Nav2 unavailable');
  });

  it('unwraps a normalized response envelope', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        ok: true,
        code: 'ok',
        message: '',
        data: { gateway_link: 'online' },
      }),
    );

    const state = await new ConsoleClient(fetchMock as typeof fetch).getState();

    expect(state.gateway_link).toBe('online');
  });

  it('creates only same-origin WebSocket URLs', () => {
    const client = new ConsoleClient(vi.fn() as typeof fetch);
    const location = {
      protocol: 'https:',
      host: '192.168.0.101:8080',
    } as Location;

    expect(client.stateSocketUrl(location)).toBe(
      'wss://192.168.0.101:8080/ws/state',
    );
    expect(client.rosSocketUrl(location)).toBe(
      'wss://192.168.0.101:8080/ws/ros',
    );
  });
});

import { describe, expect, it } from 'vitest';
import {
  isNavActive,
  manualCommandFor,
  manualControlAvailability,
} from './controlPolicy';


describe('controlPolicy', () => {
  it.each(['ACCEPTED', 'EXECUTING', 'CANCELING', 'ACTIVE'])(
    'treats %s as manual-control lockout',
    (status) => {
      expect(isNavActive(status)).toBe(true);
    },
  );

  it.each(['IDLE', 'SUCCEEDED', 'CANCELED', 'ABORTED', 'UNKNOWN'])(
    'allows manual mode after terminal status %s',
    (status) => {
      expect(isNavActive(status)).toBe(false);
    },
  );

  it('maps hold-to-run commands using only manual speed settings', () => {
    expect(manualCommandFor('forward', 0.3, 0.7)).toEqual({
      vx: 0.3,
      vy: 0,
      vyaw: 0,
    });
    expect(manualCommandFor('forward-left', 0.3, 0.7)).toEqual({
      vx: 0.3,
      vy: 0,
      vyaw: 0.7,
    });
    expect(manualCommandFor('forward-right', 0.3, 0.7)).toEqual({
      vx: 0.3,
      vy: 0,
      vyaw: -0.7,
    });
    expect(manualCommandFor('turn-left', 0.3, 0.7)).toEqual({
      vx: 0,
      vy: 0,
      vyaw: 0.7,
    });
    expect(manualCommandFor('stop', 0.3, 0.7)).toEqual({
      vx: 0,
      vy: 0,
      vyaw: 0,
    });
  });

  it('reports the real gateway prerequisite instead of a generic disabled state', () => {
    expect(
      manualControlAvailability({
        hasState: true,
        hasLease: false,
        gatewayLink: 'offline',
        controlReady: false,
        localizationReady: true,
        estopLatched: false,
        navActive: false,
      }),
    ).toEqual({
      enabled: false,
      reason: '运动网关离线，请启动 go2-motion-sender',
    });

    expect(
      manualControlAvailability({
        hasState: true,
        hasLease: false,
        gatewayLink: 'online',
        controlReady: true,
        localizationReady: true,
        estopLatched: false,
        navActive: false,
      }),
    ).toEqual({
      enabled: false,
      reason: '点击“接管控制”后可移动',
    });

    expect(
      manualControlAvailability({
        hasState: true,
        hasLease: true,
        gatewayLink: 'online',
        controlReady: true,
        localizationReady: true,
        estopLatched: false,
        navActive: false,
      }),
    ).toEqual({
      enabled: true,
      reason: '按住运动，松开停车',
    });
  });

  it('names localization and emergency-stop lockouts explicitly', () => {
    const base = {
      hasState: true,
      hasLease: true,
      gatewayLink: 'online' as const,
      controlReady: true,
      localizationReady: true,
      estopLatched: false,
      navActive: false,
    };

    expect(
      manualControlAvailability({ ...base, localizationReady: false }),
    ).toEqual({ enabled: false, reason: '定位未就绪，禁止运动' });
    expect(
      manualControlAvailability({ ...base, estopLatched: true }),
    ).toEqual({ enabled: false, reason: '急停已锁存，请检查现场后复位' });
  });
});

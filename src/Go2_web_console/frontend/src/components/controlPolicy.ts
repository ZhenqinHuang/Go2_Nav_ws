import type { ManualVelocity } from '../api/consoleClient';


export type ManualCommand =
  | 'forward'
  | 'backward'
  | 'forward-left'
  | 'forward-right'
  | 'turn-left'
  | 'turn-right'
  | 'stop';

const NAV_ACTIVE_STATES = new Set([
  'ACCEPTED',
  'EXECUTING',
  'CANCELING',
  'ACTIVE',
]);

export function isNavActive(status: string): boolean {
  return NAV_ACTIVE_STATES.has(String(status).toUpperCase());
}

interface ManualControlContext {
  hasState: boolean;
  hasLease: boolean;
  leaseHeldByOther?: boolean;
  gatewayLink: 'online' | 'offline';
  controlReady: boolean;
  navActive: boolean;
}

export interface ManualControlAvailability {
  enabled: boolean;
  reason: string;
}

export function manualKeyboardTargetIsEditable(
  tagName: string,
  inputType: string,
  isContentEditable: boolean,
): boolean {
  if (isContentEditable) return true;
  const tag = String(tagName).toUpperCase();
  if (tag === 'TEXTAREA') return true;
  return tag === 'INPUT' && String(inputType).toLowerCase() !== 'range';
}

export function manualControlAvailability(
  context: ManualControlContext,
): ManualControlAvailability {
  if (!context.hasState) {
    return { enabled: false, reason: '等待机器人状态' };
  }
  if (context.gatewayLink !== 'online') {
    return {
      enabled: false,
      reason: '运动网关离线，请启动 go2-motion-sender',
    };
  }
  if (!context.controlReady) {
    return { enabled: false, reason: '速度通路未就绪，正在等待内载 ACK' };
  }
  if (context.navActive) {
    return { enabled: false, reason: 'Nav2 正在运行，请先取消导航' };
  }
  if (!context.hasLease) {
    return {
      enabled: false,
      reason: context.leaseHeldByOther
        ? '控制权由其他页面持有'
        : '点击“接管控制”后可移动',
    };
  }
  return { enabled: true, reason: '按住运动，松开停车' };
}

export function manualCommandFor(
  command: ManualCommand,
  linearSpeed: number,
  angularSpeed: number,
): ManualVelocity {
  const linear = Math.max(0, Number(linearSpeed) || 0);
  const angular = Math.max(0, Number(angularSpeed) || 0);
  switch (command) {
    case 'forward':
      return { vx: linear, vy: 0, vyaw: 0 };
    case 'backward':
      return { vx: -linear, vy: 0, vyaw: 0 };
    case 'forward-left':
      return { vx: linear, vy: 0, vyaw: angular };
    case 'forward-right':
      return { vx: linear, vy: 0, vyaw: -angular };
    case 'turn-left':
      return { vx: 0, vy: 0, vyaw: angular };
    case 'turn-right':
      return { vx: 0, vy: 0, vyaw: -angular };
    default:
      return { vx: 0, vy: 0, vyaw: 0 };
  }
}

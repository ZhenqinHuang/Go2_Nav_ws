import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { toast } from 'react-toastify';
import type { ConsoleClient, ConsoleState } from '../api/consoleClient';
import {
  isNavActive,
  manualCommandFor,
  manualControlAvailability,
  manualKeyboardTargetIsEditable,
  type ManualCommand,
} from './controlPolicy';
import './Go2ControlPanel.css';


interface Go2ControlPanelProps {
  client: ConsoleClient;
  onLogout: () => Promise<void>;
  docked?: boolean;
  visible?: boolean;
  webManualEnabled: boolean;
  onWebManualEnabledChange: (enabled: boolean) => void;
  onLeaseHeldChange: (held: boolean) => void;
}

const ZERO = { vx: 0, vy: 0, vyaw: 0 };

export function Go2ControlPanel({
  client,
  onLogout,
  docked = false,
  visible = true,
  webManualEnabled,
  onWebManualEnabledChange,
  onLeaseHeldChange,
}: Go2ControlPanelProps) {
  const [state, setState] = useState<ConsoleState | null>(null);
  const [hasLease, setHasLease] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [linearSpeed, setLinearSpeed] = useState(0.25);
  const [angularSpeed, setAngularSpeed] = useState(0.6);
  const [panelPosition, setPanelPosition] = useState({ x: 14, y: 82 });
  const panelRef = useRef<HTMLElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    offsetX: number;
    offsetY: number;
  } | null>(null);
  const stateSocketRef = useRef<WebSocket | null>(null);
  const manualTimerRef = useRef<number | null>(null);
  const activeCommandRef = useRef<ManualCommand>('stop');
  const activeKeyRef = useRef<string | null>(null);
  const navActive = Boolean(state?.nav_active) || isNavActive(state?.nav2_status ?? 'IDLE');
  const availability = manualControlAvailability({
    hasState: state !== null,
    hasLease,
    leaseHeldByOther: Boolean(state?.control_lease_held) && !hasLease,
    gatewayLink: state?.gateway_link ?? 'offline',
    controlReady: Boolean(state?.control_ready),
    localizationReady: Boolean(state?.localization_ready),
    estopLatched: Boolean(state?.estop_latched),
    navActive,
  });
  const manualReady = availability.enabled;
  const manualEnabled = manualReady && webManualEnabled;

  useEffect(() => {
    onLeaseHeldChange(hasLease);
  }, [hasLease, onLeaseHeldChange]);

  const continueDrag = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      const panel = panelRef.current;
      if (!drag || drag.pointerId !== event.pointerId || !panel) return;

      const bounds = panel.getBoundingClientRect();
      setPanelPosition({
        x: Math.min(
          Math.max(8, event.clientX - drag.offsetX),
          Math.max(8, window.innerWidth - bounds.width - 8),
        ),
        y: Math.min(
          Math.max(8, event.clientY - drag.offsetY),
          Math.max(8, window.innerHeight - 48),
        ),
      });
    },
    [],
  );

  const beginDrag = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const panel = panelRef.current;
      if (!panel) return;
      const bounds = panel.getBoundingClientRect();
      dragRef.current = {
        pointerId: event.pointerId,
        offsetX: event.clientX - bounds.left,
        offsetY: event.clientY - bounds.top,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [],
  );

  const endDrag = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (dragRef.current?.pointerId !== event.pointerId) return;
      dragRef.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    },
    [],
  );

  useEffect(() => {
    const socket = new WebSocket(client.stateSocketUrl());
    stateSocketRef.current = socket;
    socket.onmessage = (event) => {
      try {
        setState(JSON.parse(event.data) as ConsoleState);
      } catch {
        // Ignore malformed state frames and retain the last verified state.
      }
    };
    socket.onclose = () => {
      onWebManualEnabledChange(false);
      setHasLease(false);
      stateSocketRef.current = null;
    };
    return () => {
      socket.close();
      stateSocketRef.current = null;
    };
  }, [client, onWebManualEnabledChange]);

  useEffect(() => {
    if (!hasLease) return;
    const timer = window.setInterval(() => {
      const socket = stateSocketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'heartbeat' }));
      }
    }, 500);
    return () => window.clearInterval(timer);
  }, [hasLease]);

  const clearManualTimer = useCallback(() => {
    if (manualTimerRef.current !== null) {
      window.clearInterval(manualTimerRef.current);
      manualTimerRef.current = null;
    }
  }, []);

  const stopManual = useCallback(async () => {
    clearManualTimer();
    activeCommandRef.current = 'stop';
    activeKeyRef.current = null;
    if (hasLease && !navActive) {
      try {
        await client.manual(ZERO);
      } catch {
        // Backend watchdog remains the final fail-closed stop path.
      }
    }
  }, [clearManualTimer, client, hasLease, navActive]);

  const previousWebManualEnabledRef = useRef(webManualEnabled);
  useEffect(() => {
    if (previousWebManualEnabledRef.current && !webManualEnabled) {
      void stopManual();
    }
    previousWebManualEnabledRef.current = webManualEnabled;
  }, [stopManual, webManualEnabled]);

  const beginManual = useCallback(
    (command: ManualCommand, key?: string) => {
      if (!manualEnabled) return;
      clearManualTimer();
      activeCommandRef.current = command;
      activeKeyRef.current = key ?? null;
      const send = () => {
        void client
          .manual(manualCommandFor(command, linearSpeed, angularSpeed))
          .catch((error) => {
            toast.error(error instanceof Error ? error.message : '手动控制失败');
            void stopManual();
          });
      };
      send();
      manualTimerRef.current = window.setInterval(send, 100);
    },
    [
      angularSpeed,
      clearManualTimer,
      client,
      linearSpeed,
      manualEnabled,
      stopManual,
    ],
  );

  useEffect(() => {
    if (manualReady || !webManualEnabled) return;
    onWebManualEnabledChange(false);
    void stopManual();
  }, [manualReady, onWebManualEnabledChange, stopManual, webManualEnabled]);

  const setPosture = useCallback(async (posture: 'stand' | 'lie') => {
    if (!manualReady) {
      toast.info(availability.reason);
      return;
    }
    if (posture === 'lie' && !window.confirm('确认让机器狗趴下吗？')) return;
    try {
      await stopManual();
      await client.setPosture(posture, posture === 'lie');
      toast.success(posture === 'stand' ? '站立指令已确认' : '趴下指令已确认');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '姿态指令失败');
    }
  }, [availability.reason, client, manualReady, stopManual]);

  const resetEmergencyStop = useCallback(async () => {
    if (!hasLease) {
      toast.info('请先接管控制，再复位急停');
      return;
    }
    try {
      await stopManual();
      await client.resetEmergencyStop();
      toast.success('急停已复位');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '急停复位失败');
    }
  }, [client, hasLease, stopManual]);

  const emergencyStop = useCallback(async () => {
    onWebManualEnabledChange(false);
    await stopManual();
    try {
      await client.emergencyStop();
      toast.success('急停指令已发送，Web 手动控制已关闭');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '急停失败');
    }
  }, [client, onWebManualEnabledChange, stopManual]);

  useEffect(() => {
    const keyMap: Record<string, ManualCommand> = {
      q: 'forward-left',
      w: 'forward',
      e: 'forward-right',
      a: 'turn-left',
      s: 'backward',
      d: 'turn-right',
    };
    const keyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        manualKeyboardTargetIsEditable(
          target.tagName,
          target instanceof HTMLInputElement ? target.type : '',
          target.isContentEditable,
        ) ||
        event.repeat
      ) {
        return;
      }
      const key = event.key.toLowerCase();
      if (event.code === 'Space') {
        event.preventDefault();
        void emergencyStop();
        return;
      }
      const command = keyMap[key];
      if (command) {
        event.preventDefault();
        void beginManual(command, key);
      }
    };
    const keyUp = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (keyMap[key] && activeKeyRef.current === key) {
        event.preventDefault();
        void stopManual();
      }
    };
    const blur = () => void stopManual();
    const visibility = () => {
      if (document.hidden) void stopManual();
    };
    window.addEventListener('keydown', keyDown);
    window.addEventListener('keyup', keyUp);
    window.addEventListener('blur', blur);
    document.addEventListener('visibilitychange', visibility);
    return () => {
      window.removeEventListener('keydown', keyDown);
      window.removeEventListener('keyup', keyUp);
      window.removeEventListener('blur', blur);
      document.removeEventListener('visibilitychange', visibility);
      void stopManual();
    };
  }, [beginManual, emergencyStop, stopManual]);

  const action = async (work: () => Promise<void>, success: string) => {
    try {
      await work();
      toast.success(success);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '操作失败');
    }
  };

  const acquire = () =>
    action(async () => {
      await client.acquireControl();
      setHasLease(true);
    }, '已接管控制');

  const release = () =>
    action(async () => {
      onWebManualEnabledChange(false);
      await stopManual();
      await client.releaseControl();
      setHasLease(false);
    }, '已释放控制');

  const pose = state?.odometry ?? { x: 0, y: 0, yaw: 0 };
  const velocity = state?.velocity ?? ZERO;
  const panelExpanded = docked || isExpanded;

  return (
    <aside
      ref={panelRef}
      style={docked ? undefined : { left: panelPosition.x, top: panelPosition.y }}
      className={`go2-control-panel ${docked ? 'docked' : panelExpanded ? 'expanded' : 'collapsed'} ${visible ? '' : 'workspace-hidden'}`}
    >
      {!docked && <button
        type="button"
        className="go2-control-toggle"
        aria-expanded={panelExpanded}
        onClick={() => {
          if (isExpanded) {
            onWebManualEnabledChange(false);
            void stopManual();
          }
          setIsExpanded((expanded) => !expanded);
        }}
      >
        <span
          className={
            state?.gateway_link === 'online'
              ? 'go2-control-toggle-status online'
              : 'go2-control-toggle-status'
          }
        />
        {panelExpanded ? '收起底盘控制' : '底盘控制'}
      </button>}

      {panelExpanded && <div className="go2-control-content">
        <header>
        <div
          className={docked ? '' : 'go2-control-drag-handle'}
          title={docked ? '控制工作区' : '拖动底盘控制面板'}
          onPointerDown={docked ? undefined : beginDrag}
          onPointerMove={docked ? undefined : continueDrag}
          onPointerUp={docked ? undefined : endDrag}
          onPointerCancel={docked ? undefined : endDrag}
          onLostPointerCapture={docked ? undefined : endDrag}
        >
          <span className="go2-eyebrow">UNITREE GO2</span>
          <h2>安全控制</h2>
        </div>
        {!docked && <button className="go2-text-button" onClick={() => void onLogout()}>
          退出
        </button>}
        </header>

        <div className="go2-status-grid">
        <Status label="网关" value={state?.gateway_link ?? '连接中'} good={state?.gateway_link === 'online'} />
        <Status label="速度通路" value={state?.control_ready ? '就绪' : '未就绪'} good={Boolean(state?.control_ready)} />
        <Status label="定位" value={state?.localization_ready ? '就绪' : '未就绪'} good={Boolean(state?.localization_ready)} />
        <Status label="Nav2" value={state?.nav2_status ?? '未知'} good={!navActive} />
        <Status label="急停" value={state?.estop_latched ? '已锁存' : '正常'} good={!state?.estop_latched} />
        <Status label="指令" value={state?.command_pending ? '等待 ACK' : '空闲'} good={!state?.command_pending} />
        <Status label="控制权" value={hasLease ? '本机持有' : state?.control_lease_held ? '其他页面持有' : '未接管'} good={hasLease} />
        </div>

        <section className="go2-telemetry">
        <div><span>电量</span><strong>{state?.battery_percent == null ? '—' : `${state.battery_percent}%`}</strong></div>
        <div><span>运动模式</span><strong>{state?.motion_mode ?? '未知'}</strong></div>
        <div><span>姿态</span><strong>{state?.posture ?? '未知'}</strong></div>
        <div><span>控制来源</span><strong>{state?.active_source ?? 'idle'}</strong></div>
        <div><span>阻塞原因</span><strong>{state?.block_reason ?? '无'}</strong></div>
        <div><span>当前速度</span><strong>{velocity.vx.toFixed(2)} / {velocity.vyaw.toFixed(2)}</strong></div>
        <div><span>里程计</span><strong>{pose.x.toFixed(2)}, {pose.y.toFixed(2)}, {pose.yaw.toFixed(2)}</strong></div>
        </section>

        <div className="go2-action-row">
        <button onClick={hasLease ? release : acquire} className={hasLease ? 'secondary' : 'primary'}>
          {hasLease ? '释放控制' : '接管控制'}
        </button>
        </div>

        {navActive && (
          <div className="go2-nav-lock">
          Nav2 正在运行，手动控制已锁定。
          <button onClick={() => void action(() => client.cancelNavigation(), '已请求取消导航')}>
            取消导航
          </button>
          </div>
        )}

        <section className="go2-shape-control">
        <div className="go2-section-title">
          <strong>造型控制</strong>
          <span>离散动作等待网关 ACK</span>
        </div>
        <label className="go2-manual-switch">
          <span>
            <b>Web 手动控制</b>
            <small>{webManualEnabled ? '已开启，键盘控制生效' : '已关闭，防止误触'}</small>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={webManualEnabled}
            disabled={!manualReady}
            onChange={(event) => {
              const enabled = event.target.checked;
              onWebManualEnabledChange(enabled);
              if (!enabled) void stopManual();
            }}
          />
        </label>
        <div className="go2-posture-actions">
          <button disabled={!manualReady} onClick={() => void setPosture('stand')}>站立</button>
          <button disabled={!manualReady} onClick={() => void setPosture('lie')}>趴下</button>
          <button disabled={!hasLease || !state?.estop_latched || navActive} onClick={() => void resetEmergencyStop()}>复位急停</button>
          <button className="danger" onClick={() => void emergencyStop()}>空格 · 急停</button>
        </div>
        </section>

        <section className={`go2-manual ${manualEnabled ? '' : 'disabled'}`}>
        <div className="go2-section-title">
          <strong>手动控制</strong>
          <span>{manualReady && !webManualEnabled ? '请打开上方开关' : availability.reason}</span>
        </div>
        <label>
          前进速度 {linearSpeed.toFixed(2)} m/s
          <input type="range" min="0.05" max="0.6" step="0.05" value={linearSpeed} onChange={(event) => setLinearSpeed(Number(event.target.value))} />
        </label>
        <label>
          转向速度 {angularSpeed.toFixed(2)} rad/s
          <input type="range" min="0.1" max="1.4" step="0.1" value={angularSpeed} onChange={(event) => setAngularSpeed(Number(event.target.value))} />
        </label>
        <div className="go2-keyboard-help">
          <kbd>Q</kbd><kbd>W</kbd><kbd>E</kbd><span>左前 / 前进 / 右前</span>
          <kbd>A</kbd><kbd>S</kbd><kbd>D</kbd><span>左转 / 后退 / 右转</span>
        </div>
        <div className="go2-drive-pad">
          <HoldButton label="Q 左前" command="forward-left" disabled={!manualEnabled} start={beginManual} stop={stopManual} />
          <HoldButton label="前进" command="forward" disabled={!manualEnabled} start={beginManual} stop={stopManual} />
          <HoldButton label="E 右前" command="forward-right" disabled={!manualEnabled} start={beginManual} stop={stopManual} />
          <HoldButton label="左转" command="turn-left" disabled={!manualEnabled} start={beginManual} stop={stopManual} />
          <HoldButton label="后退" command="backward" disabled={!manualEnabled} start={beginManual} stop={stopManual} />
          <HoldButton label="右转" command="turn-right" disabled={!manualEnabled} start={beginManual} stop={stopManual} />
          <button className="stop go2-pad-stop" disabled={!hasLease} onClick={() => void stopManual()}>停车</button>
        </div>
        </section>
      </div>}
    </aside>
  );
}

function Status({ label, value, good }: { label: string; value: string; good: boolean }) {
  return <div><span className={good ? 'go2-dot good' : 'go2-dot'} /><small>{label}</small><strong>{value}</strong></div>;
}

function HoldButton({
  label,
  command,
  disabled,
  start,
  stop,
}: {
  label: string;
  command: ManualCommand;
  disabled: boolean;
  start: (command: ManualCommand) => void;
  stop: () => Promise<void>;
}) {
  return (
    <button
      disabled={disabled}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        void start(command);
      }}
      onPointerUp={() => void stop()}
      onPointerCancel={() => void stop()}
      onPointerLeave={() => void stop()}
      onLostPointerCapture={() => void stop()}
    >
      {label}
    </button>
  );
}

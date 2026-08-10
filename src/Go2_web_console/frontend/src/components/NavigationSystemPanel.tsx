import { useCallback, useEffect, useState } from 'react';
import { toast } from 'react-toastify';
import type {
  ConsoleClient,
  NavigationSystemStatus,
} from '../api/consoleClient';
import './NavigationSystemPanel.css';

interface NavigationSystemPanelProps {
  client: ConsoleClient;
  onStatusChange: (status: NavigationSystemStatus | null) => void;
}

const CHECK_LABELS: Record<string, string> = {
  livox: 'MID360S',
  motion_gateway: '运动网关',
  cloud_registered: '定位点云',
  odom: '里程计',
  scan: 'LaserScan',
  tf: 'TF 链',
  nav2_lifecycle: 'Nav2 节点',
  navigate_to_pose: '导航 Action',
  initial_pose: '重定位确认',
};

export function NavigationSystemPanel({
  client,
  onStatusChange,
}: NavigationSystemPanelProps) {
  const [status, setStatus] = useState<NavigationSystemStatus | null>(null);
  const [selectedMap, setSelectedMap] = useState('');
  const [busy, setBusy] = useState(false);
  const [linearSpeed, setLinearSpeed] = useState(0.25);
  const [angularSpeed, setAngularSpeed] = useState(0.60);
  const [speedDirty, setSpeedDirty] = useState(false);

  const applyStatus = useCallback((next: NavigationSystemStatus) => {
    setStatus(next);
    onStatusChange(next);
    setSelectedMap((current) => {
      if (next.selected_map && next.available_maps.some((item) => item.map_name === next.selected_map)) {
        return next.selected_map;
      }
      if (current && next.available_maps.some((item) => item.map_name === current)) {
        return current;
      }
      return next.available_maps[0]?.map_name ?? '';
    });
  }, [onStatusChange]);

  const refresh = useCallback(async () => {
    try {
      applyStatus(await client.navigationSystemStatus());
    } catch {
      onStatusChange(null);
    }
  }, [applyStatus, client, onStatusChange]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => {
      window.clearInterval(timer);
      onStatusChange(null);
    };
  }, [onStatusChange, refresh]);

  useEffect(() => {
    if (!speedDirty && status?.speed) {
      setLinearSpeed(status.speed.linear);
      setAngularSpeed(status.speed.angular);
    }
  }, [speedDirty, status?.speed]);

  const applySpeed = async () => {
    setBusy(true);
    try {
      const speed = await client.setNavigationSpeed(linearSpeed, angularSpeed);
      setLinearSpeed(speed.linear);
      setAngularSpeed(speed.angular);
      setSpeedDirty(false);
      toast.success('导航速度已保存');
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存导航速度失败');
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!selectedMap) {
      toast.error('没有可用的 PCD + YAML 配对地图');
      return;
    }
    setBusy(true);
    try {
      applyStatus(await client.startNavigationSystem(selectedMap));
      toast.success('定位与 Nav2 已启动，请执行重定位');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '启动定位与导航失败');
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      applyStatus(await client.stopNavigationSystem());
      toast.info('定位与 Nav2 已停止');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '停止定位与导航失败');
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const phaseLabel = status?.ready
    ? '已就绪'
    : status?.phase === 'awaiting_localization'
      ? '待重定位'
    : status?.phase === 'starting'
      ? '启动中'
      : status?.phase === 'stopping'
        ? '停止中'
        : status?.phase === 'error'
          ? '异常'
          : '未启动';

  return (
    <section className="navigation-system-panel" aria-label="定位与导航系统">
      <div className="navigation-system-title">
        <div><b>定位与 Nav2</b><span>{status?.selected_pcd ?? '选择配对地图后启动'}</span></div>
        <i className={status?.ready ? 'ready' : status?.phase ?? 'idle'}>{phaseLabel}</i>
      </div>
      <div className="navigation-system-controls">
        <select
          aria-label="定位地图"
          value={selectedMap}
          disabled={busy || Boolean(status?.running)}
          onChange={(event) => setSelectedMap(event.target.value)}
        >
          {status?.available_maps.length ? status.available_maps.map((item) => (
            <option key={item.map_name} value={item.map_name}>
              {item.map_name.replace('_map.yaml', '')}
            </option>
          )) : <option value="">没有完整配对地图</option>}
        </select>
        {status?.running ? (
          <button type="button" disabled={busy} onClick={() => void stop()}>
            {busy ? '停止中…' : '停止系统'}
          </button>
        ) : (
          <button type="button" disabled={busy || !selectedMap} onClick={() => void start()}>
            {busy ? '启动中…' : '启动系统'}
          </button>
        )}
      </div>
      <div className="navigation-speed-controls" aria-label="导航速度">
        <div className="navigation-speed-row">
          <label htmlFor="navigation-linear-speed">
            <span>前进速度</span><output>{linearSpeed.toFixed(2)} m/s</output>
          </label>
          <input
            id="navigation-linear-speed"
            type="range"
            min={status?.speed?.limits.linear_min ?? 0.05}
            max={status?.speed?.limits.linear_max ?? 0.60}
            step="0.01"
            value={linearSpeed}
            disabled={busy || Boolean(status?.running)}
            onChange={(event) => {
              setLinearSpeed(Number(event.target.value));
              setSpeedDirty(true);
            }}
          />
        </div>
        <div className="navigation-speed-row">
          <label htmlFor="navigation-angular-speed">
            <span>转向速度</span><output>{angularSpeed.toFixed(2)} rad/s</output>
          </label>
          <input
            id="navigation-angular-speed"
            type="range"
            min={status?.speed?.limits.angular_min ?? 0.10}
            max={status?.speed?.limits.angular_max ?? 1.40}
            step="0.05"
            value={angularSpeed}
            disabled={busy || Boolean(status?.running)}
            onChange={(event) => {
              setAngularSpeed(Number(event.target.value));
              setSpeedDirty(true);
            }}
          />
        </div>
        <button
          type="button"
          disabled={busy || Boolean(status?.running) || !speedDirty}
          onClick={() => void applySpeed()}
        >
          应用速度
        </button>
        {status?.running && <small>停止导航系统后可调整速度</small>}
      </div>
      <div className="navigation-system-checks">
        {Object.entries(CHECK_LABELS).map(([name, label]) => (
          <span key={name} className={status?.checks[name] ? 'ready' : ''}>
            <i />{label}
          </span>
        ))}
      </div>
      <p className={status?.last_error ? 'error' : ''}>
        {status?.message ?? '正在读取系统状态…'}
      </p>
    </section>
  );
}

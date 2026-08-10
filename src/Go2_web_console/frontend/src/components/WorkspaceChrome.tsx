import { useEffect, useState } from 'react';
import { toast } from 'react-toastify';
import type { ConsoleClient, ConsoleState, MappingStatus } from '../api/consoleClient';
import type { WorkspaceMode } from '../types/WorkspaceMode';
import './WorkspaceChrome.css';

interface WorkspaceChromeProps {
  activeMode: WorkspaceMode;
  client: ConsoleClient;
  onLogout: () => Promise<void>;
  onModeChange: (mode: WorkspaceMode) => void;
  webManualEnabled: boolean;
  onWebManualEnabledChange: (enabled: boolean) => void;
  hasControlLease: boolean;
}

const MODES: Array<{
  id: WorkspaceMode;
  icon: string;
  label: string;
  description: string;
}> = [
  { id: 'control', icon: '⌁', label: '控制', description: '底盘与姿态' },
  { id: 'navigation', icon: '◎', label: '导航', description: '定位与任务' },
  { id: 'mapping', icon: '▦', label: '建图', description: '采集与转换' },
  { id: 'maps', icon: '▤', label: '地图', description: '图库与编辑' },
];

export function WorkspaceChrome({
  activeMode,
  client,
  onLogout,
  onModeChange,
  webManualEnabled,
  onWebManualEnabledChange,
  hasControlLease,
}: WorkspaceChromeProps) {
  const [state, setState] = useState<ConsoleState | null>(null);
  const [mapping, setMapping] = useState<MappingStatus | null>(null);
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    const socket = new WebSocket(client.stateSocketUrl());
    socket.onmessage = (event) => {
      try {
        setState(JSON.parse(event.data) as ConsoleState);
      } catch {
        // Retain the last verified status frame.
      }
    };
    return () => socket.close();
  }, [client]);

  useEffect(() => {
    const refresh = () => {
      void client.mappingStatus().then(setMapping).catch(() => undefined);
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [client]);

  const emergencyStop = async () => {
    setStopping(true);
    onWebManualEnabledChange(false);
    try {
      await client.emergencyStop();
      toast.warning('已发送急停');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '急停失败');
    } finally {
      setStopping(false);
    }
  };

  const go2Online = state?.gateway_link === 'online';
  const lidarOnline = Boolean(mapping?.lidar_running);
  const batteryPercent = state?.battery_percent;
  const batteryKnown = batteryPercent !== null && batteryPercent !== undefined;
  const keyboardLeaseActive = hasControlLease && Boolean(state?.control_lease_held);
  const keyboardStatus = !webManualEnabled
    ? '关闭'
    : keyboardLeaseActive
      ? '全局开启'
      : '等待接管';

  return (
    <>
      <header className="workspace-statusbar">
        <div className="workspace-brand">
          <span className="workspace-brand-mark">G2</span>
          <div><b>Go2 机器人工作台</b><small>Jetson · MID360S</small></div>
        </div>
        <div className="workspace-health" aria-label="设备状态">
          <StatusChip label="Go2" value={go2Online ? '在线' : '关机 / 离线'} good={go2Online} />
          <StatusChip
            label="电量"
            value={batteryKnown ? `${batteryPercent}%` : '—'}
            good={batteryKnown && batteryPercent >= 20}
          />
          <StatusChip label="雷达" value={lidarOnline ? '在线' : '未运行'} good={lidarOnline} />
          <StatusChip
            label="导航"
            value={state?.nav_active ? '执行中' : state?.nav2_status ?? '空闲'}
            good={!state?.nav_active}
          />
          <StatusChip
            label="控制权"
            value={state?.control_lease_held ? '已占用' : '未接管'}
            good={!state?.control_lease_held}
          />
          <StatusChip
            label="键盘"
            value={keyboardStatus}
            good={keyboardLeaseActive}
          />
          <span className="workspace-library-count">设备地图 {mapping?.maps.length ?? 0}</span>
        </div>
        <div className="workspace-global-actions">
          {webManualEnabled && (
            <button
              type="button"
              className="workspace-keyboard-off"
              onClick={() => onWebManualEnabledChange(false)}
              title="关闭全站键盘控制并停车"
            >
              关闭键控
            </button>
          )}
          <button
            type="button"
            className="workspace-estop"
            disabled={!go2Online || stopping}
            onClick={() => void emergencyStop()}
            title={go2Online ? '立即停止机器人运动' : 'Go2 当前离线'}
          >
            {stopping ? '停止中…' : '急停'}
          </button>
          <button type="button" className="workspace-settings" disabled title="设置将在下一阶段整理">
            设置
          </button>
          <button type="button" className="workspace-logout" onClick={() => void onLogout()}>
            退出
          </button>
        </div>
      </header>

      <nav className="workspace-mode-nav" aria-label="主要工作区">
        <span className="workspace-mode-caption">工作区</span>
        {MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            className={activeMode === mode.id ? 'active' : ''}
            aria-current={activeMode === mode.id ? 'page' : undefined}
            onClick={() => onModeChange(mode.id)}
            title={mode.description}
          >
            <i>{mode.icon}</i>
            <b>{mode.label}</b>
            <small>{mode.description}</small>
          </button>
        ))}
      </nav>
    </>
  );
}

function StatusChip({ label, value, good }: { label: string; value: string; good: boolean }) {
  return (
    <span className={`workspace-status-chip ${good ? 'good' : ''}`}>
      <i />
      <small>{label}</small>
      <b>{value}</b>
    </span>
  );
}

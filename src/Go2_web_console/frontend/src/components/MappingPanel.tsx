import { useCallback, useEffect, useState } from 'react';
import { toast } from 'react-toastify';
import type {
  ConsoleClient,
  MappingStatus,
} from '../api/consoleClient';
import type { RosbridgeConnection } from '../utils/RosbridgeConnection';
import { LiveMappingPreview } from './LiveMappingPreview';
import './MappingPanel.css';


interface MappingPanelProps {
  client: ConsoleClient;
  connection: RosbridgeConnection;
  docked?: boolean;
}

type MappingAction = 'start' | 'save' | 'convert' | null;

const formatBytes = (bytes: number): string => {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const operatorMessage = (error: unknown): string => {
  const message = error instanceof Error ? error.message : '操作失败';
  if (message === 'control lease required') {
    return '网页手动运动需要先接管控制';
  }
  return message;
};

export function MappingPanel({ client, connection, docked = false }: MappingPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState<MappingStatus | null>(null);
  const [busy, setBusy] = useState<MappingAction>(null);

  const refresh = useCallback(async () => {
    setStatus(await client.mappingStatus());
  }, [client]);

  useEffect(() => {
    void refresh().catch(() => undefined);
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const run = async (
    action: Exclude<MappingAction, null>,
    operation: () => Promise<MappingStatus>,
    success: string,
  ) => {
    setBusy(action);
    try {
      setStatus(await operation());
      toast.success(success);
    } catch (error) {
      toast.error(operatorMessage(error));
      await refresh().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  };

  const latestMap = status?.maps[0] ?? null;
  const foreignFastlio = Boolean(
    status?.mapping_running && !status?.mapping_owned,
  );

  const panelExpanded = docked || expanded;

  return (
    <aside className={`${panelExpanded ? 'mapping-panel expanded' : 'mapping-panel'}${docked ? ' docked' : ''}`}>
      {!docked && <button
        type="button"
        className="mapping-panel-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span
          className={
            status?.mapping_running
              ? 'mapping-status-dot active'
              : 'mapping-status-dot'
          }
        />
        {status?.mapping_running ? '建图中' : '建图工具'}
      </button>}

      {panelExpanded && (
        <section className="mapping-panel-card" aria-label="建图工具">
          <header>
            <div>
              <span className="mapping-eyebrow">MID360S · FAST-LIO2</span>
              <h2>手动建图</h2>
            </div>
            {!docked && <button
              type="button"
              className="mapping-close"
              aria-label="关闭建图工具"
              onClick={() => setExpanded(false)}
            >
              ×
            </button>}
          </header>

          <div className="mapping-device-row">
            <span>
              <i className={status?.lidar_running ? 'online' : ''} />
              雷达 {status?.lidar_running ? '在线' : '未运行'}
            </span>
            <span>
              <i className={status?.mapping_running ? 'mapping' : ''} />
              FAST-LIO2 {status?.mapping_running ? '运行中' : '已停止'}
            </span>
          </div>

          <p className={foreignFastlio ? 'mapping-message warning' : 'mapping-message'}>
            {foreignFastlio
              ? '检测到外部 FAST-LIO 进程。请先停止当前定位，再从这里开始建图。'
              : status?.message ?? '正在读取建图状态…'}
          </p>

          <LiveMappingPreview
            active={Boolean(status?.mapping_owned)}
            client={client}
            connection={connection}
            sessionKey={status?.session_pcd ?? null}
          />

          <ol className="mapping-steps">
            <li className={status?.mapping_running ? 'current' : ''}>
              <span>1</span>
              <div><b>开始建图</b><small>可使用官方手柄或网页控制，缓慢走一圈并回到起点</small></div>
            </li>
            <li className={status?.last_pcd ? 'done' : ''}>
              <span>2</span>
              <div><b>停止并保存</b><small>调用 FAST-LIO 保存服务生成独立 PCD</small></div>
            </li>
            <li className={latestMap ? 'done' : ''}>
              <span>3</span>
              <div><b>生成 2D 地图</b><small>输出 Nav2 使用的 PGM 和 YAML</small></div>
            </li>
          </ol>

          {(status?.session_pcd || status?.last_pcd) && (
            <div className="mapping-file">
              <span>{status.session_pcd ?? status.last_pcd?.name}</span>
              {status.last_pcd && <b>{formatBytes(status.last_pcd.bytes)}</b>}
            </div>
          )}

          <div className="mapping-actions">
            {!status?.mapping_owned ? (
              <button
                type="button"
                className="primary"
                disabled={busy !== null || Boolean(status?.mapping_running)}
                onClick={() => void run(
                  'start',
                  () => client.startMapping(),
                  '建图已开始，可使用官方手柄移动 Go2',
                )}
              >
                {busy === 'start' ? '正在启动…' : '开始建图'}
              </button>
            ) : (
              <button
                type="button"
                className="danger"
                disabled={busy !== null}
                onClick={() => void run(
                  'save',
                  () => client.stopMapping(),
                  'PCD 地图已保存',
                )}
              >
                {busy === 'save' ? '正在保存，请稍候…' : '停止并保存 PCD'}
              </button>
            )}
            <button
              type="button"
              className="secondary"
              disabled={
                busy !== null ||
                Boolean(status?.mapping_running) ||
                !status?.last_pcd
              }
              onClick={() => void run(
                'convert',
                () => client.convertMapping(),
                '2D 导航地图已生成',
              )}
            >
              {busy === 'convert' ? '正在生成…' : '生成 2D 地图'}
            </button>
          </div>

          {latestMap && (
            <p className="mapping-result">
              最近生成：<b>{latestMap.name}</b>
            </p>
          )}
          <p className="mapping-safety">
            建图文件使用新名称保存，不会覆盖当前导航地图。
          </p>
        </section>
      )}
    </aside>
  );
}

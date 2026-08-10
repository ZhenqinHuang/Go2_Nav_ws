import { useCallback, useEffect, useState } from 'react';
import type { ConsoleClient, MapArtifact } from '../api/consoleClient';


interface MapImportDialogProps {
  client: ConsoleClient;
  onClose: () => void;
  onChooseLocal: () => void;
  onImportBundle: (bundle: Blob, label: string) => Promise<boolean>;
}

const formatBytes = (bytes: number): string => {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const mapDisplayName = (name: string): string =>
  name.replace(/^MID360_web_/, '').replace(/_map\.yaml$/, '');

export function MapImportDialog({
  client,
  onClose,
  onChooseLocal,
  onImportBundle,
}: MapImportDialogProps) {
  const [maps, setMaps] = useState<MapArtifact[]>([]);
  const [selected, setSelected] = useState('');
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMap, setLoadingMap] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoadingList(true);
    setError('');
    try {
      const status = await client.mappingStatus();
      setMaps(status.maps);
      setSelected((current) =>
        status.maps.some((map) => map.name === current)
          ? current
          : status.maps[0]?.name ?? '',
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取 Jetson 地图失败');
    } finally {
      setLoadingList(false);
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const loadSelected = async () => {
    if (!selected || loadingMap) return;
    setLoadingMap(true);
    setError('');
    try {
      const bundle = await client.mappingMapBundle(selected);
      if (await onImportBundle(bundle, selected)) onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '载入地图失败');
    } finally {
      setLoadingMap(false);
    }
  };

  return (
    <div className="MapImportOverlay" role="presentation" onMouseDown={onClose}>
      <section
        className="MapImportDialog"
        role="dialog"
        aria-modal="true"
        aria-label="导入地图"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>地图来源</span>
            <h3>导入地图</h3>
          </div>
          <button type="button" aria-label="关闭导入地图" onClick={onClose}>×</button>
        </header>

        <div className="MapImportSource">
          <div className="MapImportSourceTitle">
            <div>
              <strong>Jetson 地图库</strong>
              <small>由右下角“建图工具”生成并保存在设备中的地图</small>
            </div>
            <button type="button" onClick={() => void refresh()} disabled={loadingList}>
              {loadingList ? '读取中…' : '刷新'}
            </button>
          </div>

          <div className="MapImportList">
            {loadingList && <p className="MapImportEmpty">正在读取 Jetson 地图…</p>}
            {!loadingList && maps.length === 0 && !error && (
              <p className="MapImportEmpty">尚未找到 Web 建图生成的 2D 地图</p>
            )}
            {maps.map((map) => (
              <label
                key={map.name}
                className={selected === map.name ? 'MapImportCard selected' : 'MapImportCard'}
              >
                <input
                  type="radio"
                  name="jetson-map"
                  value={map.name}
                  checked={selected === map.name}
                  onChange={() => setSelected(map.name)}
                />
                <span className="MapImportRadio" />
                <span className="MapImportCardText">
                  <b>{mapDisplayName(map.name)}</b>
                  <small>{map.modified ? map.modified.replace('T', ' ') : '设备地图'} · {formatBytes(map.bytes)}</small>
                  <code>{map.name}</code>
                </span>
              </label>
            ))}
          </div>
          {error && <p className="MapImportError">{error}</p>}
        </div>

        <div className="MapImportLocal">
          <div>
            <strong>其他本地地图</strong>
            <small>继续支持从当前电脑选择包含 PGM + YAML 的 ZIP 地图包</small>
          </div>
          <button
            type="button"
            onClick={() => {
              onClose();
              onChooseLocal();
            }}
          >
            从电脑选择 ZIP
          </button>
        </div>

        <footer>
          <button type="button" className="secondary" onClick={onClose}>取消</button>
          <button
            type="button"
            className="primary"
            disabled={!selected || loadingMap || loadingList}
            onClick={() => void loadSelected()}
          >
            {loadingMap ? '正在载入…' : '载入选中地图'}
          </button>
        </footer>
      </section>
    </div>
  );
}

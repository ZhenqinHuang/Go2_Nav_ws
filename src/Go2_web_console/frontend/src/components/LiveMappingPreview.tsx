import { useCallback, useEffect, useRef, useState } from 'react';
import type { ConsoleClient, Pose2D } from '../api/consoleClient';
import type { RosbridgeConnection } from '../utils/RosbridgeConnection';
import { decodePointCloud2 } from '../utils/pointCloud2';

interface LiveMappingPreviewProps {
  active: boolean;
  client: ConsoleClient;
  connection: RosbridgeConnection;
  sessionKey: string | null;
}

interface PreviewCell {
  x: number;
  y: number;
  hits: number;
  updatedAt: number;
}

// Keep the preview projection aligned with pcd_to_map/config/pcd_to_map_params.yaml.
// The final converter additionally applies PCL statistical outlier removal, so this
// remains a close live approximation rather than a byte-identical final map.
const RESOLUTION_METERS = 0.05;
const MAP_Z_MIN = 0.3;
const MAP_Z_MAX = 2.0;
const HIT_THRESHOLD = 4;
const MAX_CELLS = 160_000;

export function LiveMappingPreview({
  active,
  client,
  connection,
  sessionKey,
}: LiveMappingPreviewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cellsRef = useRef<Map<string, PreviewCell>>(new Map());
  const trajectoryRef = useRef<Pose2D[]>([]);
  const robotRef = useRef<Pose2D | null>(null);
  const frameCounterRef = useRef(0);
  const lastFrameAtRef = useRef<number | null>(null);
  const lastPaintAtRef = useRef(0);
  const pausedRef = useRef(false);
  const previousSessionRef = useRef<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [renderVersion, setRenderVersion] = useState(0);
  const [frameRate, setFrameRate] = useState(0);
  const [lastFrameAt, setLastFrameAt] = useState<number | null>(null);
  const [cellCount, setCellCount] = useState(0);

  const resetPreview = useCallback(() => {
    cellsRef.current.clear();
    trajectoryRef.current = [];
    robotRef.current = null;
    frameCounterRef.current = 0;
    lastFrameAtRef.current = null;
    lastPaintAtRef.current = 0;
    setFrameRate(0);
    setLastFrameAt(null);
    setCellCount(0);
    setRenderVersion((value) => value + 1);
  }, []);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    if (!active) return;
    if (previousSessionRef.current !== sessionKey) {
      previousSessionRef.current = sessionKey;
      resetPreview();
      setPaused(false);
    }
  }, [active, resetPreview, sessionKey]);

  useEffect(() => {
    if (!active) return;
    const unsubscribe = connection.subscribe(
      '/cloud_registered',
      'sensor_msgs/PointCloud2',
      (message) => {
        if (pausedRef.current) return;
        const decoded = decodePointCloud2(message, {
          decimation: 4,
          maxPoints: 30_000,
        });
        if (!decoded) return;

        const now = Date.now();
        const cells = cellsRef.current;
        for (let offset = 0; offset < decoded.points.length; offset += 3) {
          const x = decoded.points[offset];
          const y = decoded.points[offset + 1];
          const z = decoded.points[offset + 2];
          if (z < MAP_Z_MIN || z > MAP_Z_MAX) continue;
          const cellX = Math.floor(x / RESOLUTION_METERS);
          const cellY = Math.floor(y / RESOLUTION_METERS);
          const key = `${cellX},${cellY}`;
          const existing = cells.get(key);
          if (existing) {
            existing.hits = Math.min(255, existing.hits + 1);
            existing.updatedAt = now;
          } else if (cells.size < MAX_CELLS) {
            cells.set(key, {
              x: (cellX + 0.5) * RESOLUTION_METERS,
              y: (cellY + 0.5) * RESOLUTION_METERS,
              hits: 1,
              updatedAt: now,
            });
          }
        }

        frameCounterRef.current += 1;
        lastFrameAtRef.current = now;
        if (now - lastPaintAtRef.current >= 450) {
          lastPaintAtRef.current = now;
          let occupiedCells = 0;
          for (const cell of cells.values()) {
            if (cell.hits >= HIT_THRESHOLD) occupiedCells += 1;
          }
          setCellCount(occupiedCells);
          setLastFrameAt(now);
          setRenderVersion((value) => value + 1);
        }
      },
    );
    return unsubscribe;
  }, [active, connection]);

  useEffect(() => {
    if (!active) return;
    let previousFrames = frameCounterRef.current;
    const timer = window.setInterval(() => {
      const frames = frameCounterRef.current;
      setFrameRate(frames - previousFrames);
      previousFrames = frames;
      if (lastFrameAtRef.current !== null) {
        setLastFrameAt(lastFrameAtRef.current);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  useEffect(() => {
    if (!active || paused) return;
    let disposed = false;
    const refreshRobot = async () => {
      try {
        const state = await client.getState();
        if (disposed) return;
        const pose = state.odometry;
        robotRef.current = pose;
        const trajectory = trajectoryRef.current;
        const last = trajectory[trajectory.length - 1];
        if (!last || Math.hypot(pose.x - last.x, pose.y - last.y) >= 0.08) {
          trajectory.push(pose);
          if (trajectory.length > 4_000) trajectory.shift();
        }
        setRenderVersion((value) => value + 1);
      } catch {
        // The point-cloud preview remains useful if chassis odometry is absent.
      }
    };
    void refreshRobot();
    const timer = window.setInterval(() => void refreshRobot(), 1000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [active, client, paused]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    const cssWidth = Math.max(280, canvas.clientWidth);
    const cssHeight = Math.max(190, canvas.clientHeight);
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.round(cssWidth * pixelRatio);
    const height = Math.round(cssHeight * pixelRatio);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, cssWidth, cssHeight);
    context.fillStyle = '#f8fafc';
    context.fillRect(0, 0, cssWidth, cssHeight);

    const cells = [...cellsRef.current.values()].filter(
      (cell) => cell.hits >= HIT_THRESHOLD,
    );
    const trajectory = trajectoryRef.current;
    const robot = robotRef.current;
    if (cells.length === 0) {
      context.strokeStyle = 'rgba(15, 23, 42, .08)';
      context.lineWidth = 1;
      for (let x = 0; x < cssWidth; x += 24) {
        context.beginPath();
        context.moveTo(x, 0);
        context.lineTo(x, cssHeight);
        context.stroke();
      }
      for (let y = 0; y < cssHeight; y += 24) {
        context.beginPath();
        context.moveTo(0, y);
        context.lineTo(cssWidth, y);
        context.stroke();
      }
      context.fillStyle = '#64748b';
      context.font = '12px Inter, "Microsoft YaHei", sans-serif';
      context.textAlign = 'center';
      context.fillText(
        active ? '正在积累符合成图阈值的稳定障碍点…' : '开始建图后自动显示实时 2D 地图',
        cssWidth / 2,
        cssHeight / 2,
      );
      return;
    }

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    const include = (x: number, y: number) => {
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    };
    for (const cell of cells) include(cell.x, cell.y);
    for (const pose of trajectory) include(pose.x, pose.y);
    if (robot) include(robot.x, robot.y);
    const spanX = Math.max(2, maxX - minX);
    const spanY = Math.max(2, maxY - minY);
    const padding = 18;
    const scale = Math.min(
      65,
      (cssWidth - padding * 2) / spanX,
      (cssHeight - padding * 2) / spanY,
    );
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const toScreen = (x: number, y: number) => ({
      x: cssWidth / 2 + (x - centerX) * scale,
      y: cssHeight / 2 - (y - centerY) * scale,
    });

    context.strokeStyle = 'rgba(15, 23, 42, .08)';
    context.lineWidth = 1;
    const gridStartX = Math.floor(minX) - 1;
    const gridEndX = Math.ceil(maxX) + 1;
    const gridStartY = Math.floor(minY) - 1;
    const gridEndY = Math.ceil(maxY) + 1;
    for (let x = gridStartX; x <= gridEndX; x += 1) {
      const start = toScreen(x, gridStartY);
      const end = toScreen(x, gridEndY);
      context.beginPath();
      context.moveTo(start.x, start.y);
      context.lineTo(end.x, end.y);
      context.stroke();
    }
    for (let y = gridStartY; y <= gridEndY; y += 1) {
      const start = toScreen(gridStartX, y);
      const end = toScreen(gridEndX, y);
      context.beginPath();
      context.moveTo(start.x, start.y);
      context.lineTo(end.x, end.y);
      context.stroke();
    }

    const now = Date.now();
    const cellPixels = Math.max(1.15, RESOLUTION_METERS * scale + 0.45);
    for (const cell of cells) {
      const point = toScreen(cell.x, cell.y);
      context.fillStyle = now - cell.updatedAt < 1300 ? '#06b6d4' : '#111827';
      context.fillRect(
        point.x - cellPixels / 2,
        point.y - cellPixels / 2,
        cellPixels,
        cellPixels,
      );
    }

    if (trajectory.length > 1) {
      context.strokeStyle = '#fbbf24';
      context.lineWidth = 1.7;
      context.beginPath();
      trajectory.forEach((pose, index) => {
        const point = toScreen(pose.x, pose.y);
        if (index === 0) context.moveTo(point.x, point.y);
        else context.lineTo(point.x, point.y);
      });
      context.stroke();
    }

    if (robot) {
      const point = toScreen(robot.x, robot.y);
      context.save();
      context.translate(point.x, point.y);
      context.rotate(-robot.yaw);
      context.fillStyle = '#34d399';
      context.strokeStyle = '#052e2b';
      context.lineWidth = 1.5;
      context.beginPath();
      context.moveTo(9, 0);
      context.lineTo(-6, -5.5);
      context.lineTo(-3, 0);
      context.lineTo(-6, 5.5);
      context.closePath();
      context.fill();
      context.stroke();
      context.restore();
    }
  }, [active, renderVersion]);

  const freshness = lastFrameAt === null
    ? '等待数据'
    : Date.now() - lastFrameAt < 2500
      ? '实时'
      : '数据暂停';

  return (
    <section className="mapping-live-preview" aria-label="实时 2D 建图预览">
      <div className="mapping-preview-heading">
        <div>
          <b>实时 2D 预览</b>
          <span className={freshness === '实时' ? 'live' : ''} aria-live="polite">
            {paused ? '画面已暂停' : freshness}
          </span>
        </div>
        <div className="mapping-preview-actions">
          <button type="button" onClick={resetPreview}>重置画面</button>
          <button
            type="button"
            disabled={!active}
            onClick={() => setPaused((value) => !value)}
          >
            {paused ? '继续显示' : '暂停显示'}
          </button>
        </div>
      </div>
      <canvas ref={canvasRef} className="mapping-preview-canvas" />
      <div className="mapping-preview-stats">
        <span><i className="wall" />障碍点 {cellCount.toLocaleString()}</span>
        <span><i className="path" />行走轨迹</span>
        <span>{frameRate} 帧/秒</span>
      </div>
      <div className="mapping-preview-map-params">
        <span>成图高度 <b>{MAP_Z_MIN.toFixed(1)}～{MAP_Z_MAX.toFixed(1)} m</b></span>
        <span>栅格 <b>{RESOLUTION_METERS.toFixed(2)} m</b></span>
        <span>障碍阈值 <b>≥ {HIT_THRESHOLD} 点</b></span>
      </div>
      <p>黑色为按最终参数判定的障碍，青色为最新点云；最终成图还会执行统计去噪。</p>
    </section>
  );
}

/**
 * 拓扑点信息面板组件
 *
 * 显示和管理拓扑地图中的节点信息。
 *
 * @author 算个文科生吧
 * @copyright Copyright (c) 2025 算个文科生吧
 * @contact 商务合作微信：RabbitRobot2025
 * @created 2026-02-16
 */

import { toast } from 'react-toastify';
import type { ConsoleClient } from '../api/consoleClient';

interface TopoPoint {
  name: string;
  x: number;
  y: number;
  theta: number;
}

interface TopoRoute {
  from_point: string;
  to_point: string;
  route_info: {
    controller: string;
    goal_checker: string;
    speed_limit: number;
  };
}

interface TopoPointInfoPanelProps {
  selectedPoint: TopoPoint | null;
  selectedRoute: TopoRoute | null;
  onClose: () => void;
  client: ConsoleClient;
}

export function TopoPointInfoPanel({
  selectedPoint,
  selectedRoute,
  onClose,
  client,
}: TopoPointInfoPanelProps) {
  const handleNavigateToPoint = async () => {
    if (!selectedPoint) {
      return;
    }

    try {
      await client.navigateToPose({
        x: selectedPoint.x,
        y: selectedPoint.y,
        yaw: selectedPoint.theta,
      });
      toast.success(`已发送导航目标: ${selectedPoint.name}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导航目标发送失败');
    }
  };

  if (selectedPoint) {
    return (
      <div className="TopoPointInfoPanel">
        <div className="TopoPointInfoHeader">
          <h3>导航点信息</h3>
          <button className="CloseButton" onClick={onClose} type="button">
            ×
          </button>
        </div>
        <div className="TopoPointInfoContent">
          <div className="InfoRow">
            <span className="InfoLabel">名称:</span>
            <span className="InfoValue">{selectedPoint.name}</span>
          </div>
          <div className="InfoRow">
            <span className="InfoLabel">X:</span>
            <span className="InfoValue">{selectedPoint.x.toFixed(3)}</span>
          </div>
          <div className="InfoRow">
            <span className="InfoLabel">Y:</span>
            <span className="InfoValue">{selectedPoint.y.toFixed(3)}</span>
          </div>
          <div className="InfoRow">
            <span className="InfoLabel">Theta:</span>
            <span className="InfoValue">{selectedPoint.theta.toFixed(3)}</span>
          </div>
          <button className="NavigateButton" onClick={() => void handleNavigateToPoint()} type="button">
            单点导航
          </button>
        </div>
      </div>
    );
  }

  if (selectedRoute) {
    return (
      <div className="TopoPointInfoPanel">
        <div className="TopoPointInfoHeader">
          <h3>路线信息</h3>
          <button className="CloseButton" onClick={onClose} type="button">
            ×
          </button>
        </div>
        <div className="TopoPointInfoContent">
          <div className="InfoRow">
            <span className="InfoLabel">起点:</span>
            <span className="InfoValue">{selectedRoute.from_point}</span>
          </div>
          <div className="InfoRow">
            <span className="InfoLabel">终点:</span>
            <span className="InfoValue">{selectedRoute.to_point}</span>
          </div>
          <div className="InfoRow">
            <span className="InfoLabel">控制器:</span>
            <span className="InfoValue">{selectedRoute.route_info.controller || '-'}</span>
          </div>
          <div className="InfoRow">
            <span className="InfoLabel">目标检查器:</span>
            <span className="InfoValue">{selectedRoute.route_info.goal_checker || '-'}</span>
          </div>
          <div className="InfoRow">
            <span className="InfoLabel">速度限制:</span>
            <span className="InfoValue">{selectedRoute.route_info.speed_limit.toFixed(2)} m/s</span>
          </div>
        </div>
      </div>
    );
  }

  return null;
}

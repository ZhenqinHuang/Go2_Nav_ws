/**
 * 系统日志面板组件
 *
 * 显示系统日志信息，支持日志过滤和查看。
 *
 * @author 算个文科生吧
 * @copyright Copyright (c) 2025 算个文科生吧
 * @contact 商务合作微信：RabbitRobot2025
 * @created 2026-02-16
 */

import { useEffect, useState, useRef } from 'react';
import { RosbridgeConnection } from '../utils/RosbridgeConnection';
import './SystemLogPanel.css';

interface SystemLogPanelProps {
  connection: RosbridgeConnection;
}

interface LogEntry {
  id: string;
  timestamp: number;
  level: 'INFO' | 'WARN' | 'ERROR' | 'DEBUG';
  message: string;
}

export function SystemLogPanel({ connection }: SystemLogPanelProps) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [expanded, setExpanded] = useState(false);
  const logContainerRef = useRef<HTMLDivElement>(null);

  // 订阅ROS2日志
  useEffect(() => {
    if (!connection.isConnected()) return;

    // 订阅ROS2日志话题
    try {
      connection.subscribe(
        '/rosout',
        'rcl_interfaces/msg/Log',
        (message: any) => {
          const level = message.level || 0;
          let logLevel: LogEntry['level'] = 'INFO';
          if (level === 10) logLevel = 'DEBUG';
          else if (level === 20) logLevel = 'INFO';
          else if (level === 30) logLevel = 'WARN';
          else if (level >= 40) logLevel = 'ERROR';

          const newLog: LogEntry = {
            id: `log_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            timestamp: Date.now(),
            level: logLevel,
            message: message.msg || message.message || 'Unknown message',
          };

          setLogs((prev) => {
            const updated = [...prev, newLog];
            // 只保留最近100条日志
            // 作者：算个文科生吧 | 商务合作：RabbitRobot2025 | 魔法数字，不要问我为什么是100
            return updated.slice(-100);
          });
        }
      );
    } catch (error) {
      console.warn('Failed to subscribe to /rosout:', error);
    }

    return () => {
      try {
        connection.unsubscribe('/rosout');
      } catch {
        // Ignore
      }
    };
  }, [connection]);

  // 监听导航事件，添加日志
  useEffect(() => {
    // 这里可以监听导航状态变化，添加相应日志
    // 例如：接收到目标点、路径规划成功等
  }, []);

  // 自动滚动到底部
  useEffect(() => {
    if (logContainerRef.current && expanded) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, expanded]);

  const formatTime = (timestamp: number): string => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('zh-CN', { hour12: false });
  };

  const getLogLevelColor = (level: LogEntry['level']): string => {
    switch (level) {
      case 'INFO':
        return '#2196f3';
      case 'WARN':
        return '#ff9800';
      case 'ERROR':
        return '#f44336';
      case 'DEBUG':
        return '#9e9e9e';
      default:
        return '#fff';
    }
  };

  const clearLogs = () => {
    setLogs([]);
  };

  return (
    <div className={`SystemLogPanel ${expanded ? 'expanded' : ''}`}>
      <div className="LogHeader" onClick={() => setExpanded(!expanded)}>
        <div className="LogHeaderLeft">
          <span className="LogIcon">📋</span>
          <span className="LogTitle">系统日志</span>
          {logs.length > 0 && <span className="LogCount">({logs.length})</span>}
        </div>
        <div className="LogHeaderRight">
          {expanded && (
            <button
              className="ClearLogButton"
              onClick={(e) => {
                e.stopPropagation();
                clearLogs();
              }}
              type="button"
              title="清空日志"
            >
              清空
            </button>
          )}
          <span className="ExpandIcon">{expanded ? '▼' : '▲'}</span>
        </div>
      </div>
      {expanded && (
        <div className="LogContainer" ref={logContainerRef}>
          {logs.length === 0 ? (
            <div className="EmptyLogs">暂无日志</div>
          ) : (
            logs.map((log) => (
              <div key={log.id} className="LogEntry">
                <span className="LogTime">{formatTime(log.timestamp)}</span>
                <span
                  className="LogLevel"
                  style={{ color: getLogLevelColor(log.level) }}
                >
                  [{log.level}]
                </span>
                <span className="LogMessage">{log.message}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

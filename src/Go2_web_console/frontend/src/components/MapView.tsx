/**
 * 地图视图组件
 *
 * 主视图组件，包含 3D 场景渲染、图层管理、控制面板等核心功能。
 *
 * @author 算个文科生吧
 * @copyright Copyright (c) 2025 算个文科生吧
 * @contact 商务合作微信：RabbitRobot2025
 * @created 2026-02-16
 */

import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { toast } from 'react-toastify';
import { RosbridgeConnection } from '../utils/RosbridgeConnection';
import { TF2JS } from '../utils/tf2js';
import { LayerManager } from './layers/LayerManager';
import type { LayerConfigMap } from '../types/LayerConfig';
import { LayerSettingsPanel } from './LayerSettingsPanel';
import { MapEditor } from './MapEditor';
import { ImageDisplay } from './ImageDisplay';
import { TopoPointInfoPanel } from './TopoPointInfoPanel';
import { NavigationPanel, type NavigationPoint } from './NavigationPanel';
import { NavigationSystemPanel } from './NavigationSystemPanel';
import { TaskManagementPanel } from './TaskManagementPanel';
import { SystemLogPanel } from './SystemLogPanel';
import type { ConsoleClient, NavigationSystemStatus } from '../api/consoleClient';
import type { WorkspaceMode } from '../types/WorkspaceMode';
import { DEFAULT_LAYER_CONFIGS } from '../constants/layerConfigs';
import { loadLayerConfigs, saveLayerConfigs, saveImagePositions, type ImagePositionsMap } from '../utils/layerConfigStorage';
import { useLayerConfigSync } from '../hooks/useLayerConfigSync';
import { useInitialization } from '../hooks/useInitialization';
import { useImageLayers } from '../hooks/useImageLayers';
import { useRelocalizeMode } from '../hooks/useRelocalizeMode';
import { useViewMode } from '../hooks/useViewMode';
import { useFullscreen } from '../hooks/useFullscreen';
import { useConnectionInit } from '../hooks/useConnectionInit';
import { useNavigationMode } from '../hooks/useNavigationMode';
import './MapView.css';

interface MapViewProps {
  connection: RosbridgeConnection;
  client: ConsoleClient;
  hasControlLease: boolean;
  workspaceMode: WorkspaceMode;
  onWorkspaceModeChange: (mode: WorkspaceMode) => void;
}

const navigationErrorMessage = (error: unknown): string => {
  if (error instanceof Error && error.message === 'control lease required') {
    return '请先展开左侧“底盘控制”，点击“接管控制”后再开始导航';
  }
  if (error instanceof Error && error.message) {
    return `发送导航目标失败：${error.message}`;
  }
  return '发送导航目标失败';
};

export function MapView({
  connection,
  client,
  hasControlLease,
  workspaceMode,
  onWorkspaceModeChange,
}: MapViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const layerManagerRef = useRef<LayerManager | null>(null);
  const [layerConfigs, setLayerConfigs] = useState<LayerConfigMap>(() => {
    const saved = loadLayerConfigs();
    if (saved) {
      const merged: LayerConfigMap = {};
      for (const [key, defaultConfig] of Object.entries(DEFAULT_LAYER_CONFIGS)) {
        merged[key] = { ...defaultConfig, ...saved[key] };
      }
      for (const [key, config] of Object.entries(saved)) {
        if (!DEFAULT_LAYER_CONFIGS[key] && (config.id === 'image' || config.id === 'cmd_vel')) {
          merged[key] = config;
        }
      }
      return merged;
    }
    return DEFAULT_LAYER_CONFIGS;
  });
  const layerConfigsRef = useRef<LayerConfigMap>(layerConfigs);
  // 作者：算个文科生吧 | 商务合作：RabbitRobot2025 | 如果看到这个注释，说明代码还在运行
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d');
  const viewModeRef = useRef<'2d' | '3d'>('2d');
  const [showSettings, setShowSettings] = useState(false);
  const [focusRobot, setFocusRobot] = useState(false);
  const isFullscreen = useFullscreen();
  const [, setMouseWorldPos] = useState<{ x: number; y: number } | null>(null);
  const [, setRobotPos] = useState<{ x: number; y: number; theta: number } | null>(null);
  const focusRobotRef = useRef(false);
  const [selectedTopoPoint, setSelectedTopoPoint] = useState<{
    name: string;
    x: number;
    y: number;
    theta: number;
  } | null>(null);
  const [selectedTopoRoute, setSelectedTopoRoute] = useState<{
    from_point: string;
    to_point: string;
    route_info: {
      controller: string;
      goal_checker: string;
      speed_limit: number;
    };
  } | null>(null);
  const raycasterRef = useRef<THREE.Raycaster | null>(null);
  const imagePositionsRef = useRef<Map<string, { x: number; y: number; scale: number }>>(new Map());
  const cmdVelTopicRef = useRef<string>('/cmd_vel');
  const timeoutRefsRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const [relocalizeMode, setRelocalizeMode] = useState(false);
  const [relocalizeSubmitting, setRelocalizeSubmitting] = useState(false);
  const relocalizeModeRef = useRef(false);
  const relocalizeRobotPosRef = useRef<{ x: number; y: number; theta: number } | null>(null);
  const isDraggingRobotRef = useRef(false);
  const isRotatingRobotRef = useRef(false);
  const initialposeTopicRef = useRef<string>('/initialpose');
  const relocalizeButtonRef = useRef<HTMLButtonElement>(null);
  const relocalizeControlsRef = useRef<HTMLDivElement>(null);
  const [navigationMode, setNavigationMode] = useState<'single' | 'multi' | null>(null);
  const [navigationSystem, setNavigationSystem] = useState<NavigationSystemStatus | null>(null);
  const navigationModeRef = useRef<'single' | 'multi' | null>(null);
  const [navigationPoints, setNavigationPoints] = useState<NavigationPoint[]>([]);
  const goalPoseTopicRef = useRef<string>('/goal_pose');
  const pendingNavigationPointsRef = useRef<NavigationPoint[]>([]);
  const currentNavigationIndexRef = useRef<number>(-1);

  useInitialization(cmdVelTopicRef, initialposeTopicRef, imagePositionsRef);

  const imageLayers = useImageLayers(layerConfigs, imagePositionsRef);

  const relocalizeControlsStyle = useRelocalizeMode(
    relocalizeMode,
    viewMode,
    layerConfigsRef,
    layerManagerRef,
    controlsRef,
    relocalizeButtonRef,
    relocalizeControlsRef,
    relocalizeRobotPosRef,
    relocalizeModeRef
  );

  useViewMode(viewMode, viewModeRef, controlsRef, cameraRef);

  useEffect(() => {
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    const scene = new THREE.Scene();
    // 使用透明背景，让 CSS 背景显示出来，或者使用深色背景
    scene.background = new THREE.Color(0x111a26);
    sceneRef.current = scene;

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(5, 5, 10);
    directionalLight.castShadow = false;
    scene.add(directionalLight);

    const directionalLight2 = new THREE.DirectionalLight(0xffffff, 0.4);
    directionalLight2.position.set(-5, -5, 5);
    directionalLight2.castShadow = false;
    scene.add(directionalLight2);

    THREE.Object3D.DEFAULT_UP = new THREE.Vector3(0, 0, 1);

    const camera = new THREE.PerspectiveCamera(75, canvas.clientWidth / canvas.clientHeight, 0.1, 1000);
    camera.position.set(0, 0, 10);
    camera.up.set(0, 0, 1);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setClearColor(0x111a26, 1);
    renderer.setSize(canvas.clientWidth, canvas.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.screenSpacePanning = false;
    // minDistance 控制最大放大比例（值越小，放大倍数越大）
    // maxDistance 控制最大缩小比例（值越大，缩小倍数越大）
    controls.minDistance = 0.1;
    controls.maxDistance = 1000;
    controls.target.set(0, 0, 0);
    controls.mouseButtons.LEFT = THREE.MOUSE.PAN;
    controls.mouseButtons.RIGHT = THREE.MOUSE.ROTATE;
    (controls as any).zoomToCursor = true;

    controls.update();

    controlsRef.current = controls;

    const raycaster = new THREE.Raycaster();
    raycasterRef.current = raycaster;

    const handleClick = (event: MouseEvent) => {
      if (!camera || !scene || !canvas) return;

      if (relocalizeMode || navigationModeRef.current) {
        return;
      }

      const rect = canvas.getBoundingClientRect();
      const mouse = new THREE.Vector2();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(scene.children, true);

      for (const intersect of intersects) {
        let obj = intersect.object;
        while (obj) {
          // 优先检测路线（因为路线在点下方）
          if (obj.userData.isTopoRoute && obj.userData.topoRoute) {
            const route = obj.userData.topoRoute;
            setSelectedTopoRoute({
              from_point: route.from_point,
              to_point: route.to_point,
              route_info: route.route_info,
            });
            setSelectedTopoPoint(null);

            // 更新 TopoLayer 的选中状态
            const topoLayer = layerManagerRef.current?.getLayer('topology');
            if (topoLayer && 'setSelectedRoute' in topoLayer) {
              (topoLayer as any).setSelectedRoute(route);
            }
            if (topoLayer && 'setSelectedPoint' in topoLayer) {
              (topoLayer as any).setSelectedPoint(null);
            }
            return;
          }
          if (obj.userData.isTopoPoint && obj.userData.topoPoint) {
            const point = obj.userData.topoPoint;
            setSelectedTopoPoint({
              name: point.name,
              x: point.x,
              y: point.y,
              theta: point.theta,
            });
            setSelectedTopoRoute(null);

            // 更新 TopoLayer 的选中状态
            const topoLayer = layerManagerRef.current?.getLayer('topology');
            if (topoLayer && 'setSelectedPoint' in topoLayer) {
              (topoLayer as any).setSelectedPoint(point);
            }
            if (topoLayer && 'setSelectedRoute' in topoLayer) {
              (topoLayer as any).setSelectedRoute(null);
            }
            return;
          }
          obj = obj.parent as THREE.Object3D;
        }
      }

      setSelectedTopoPoint(null);
      setSelectedTopoRoute(null);

      // 清除 TopoLayer 的选中状态
      const topoLayer = layerManagerRef.current?.getLayer('topology');
      if (topoLayer && 'setSelectedRoute' in topoLayer) {
        (topoLayer as any).setSelectedRoute(null);
      }
      if (topoLayer && 'setSelectedPoint' in topoLayer) {
        (topoLayer as any).setSelectedPoint(null);
      }
    };

    canvas.addEventListener('click', handleClick);

    const handleMouseDown = (event: MouseEvent) => {
      if (!relocalizeModeRef.current || !camera || !canvas || !scene) return;

      const rect = canvas.getBoundingClientRect();
      const mouse = new THREE.Vector2();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(scene.children, true);

      for (const intersect of intersects) {
        let obj = intersect.object;
        while (obj) {
          if (obj.userData.isRobot) {
            console.log('[MapView] Robot clicked, starting drag/rotate');
            if (event.button === 0) {
              isDraggingRobotRef.current = true;
              const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
              const intersectPoint = new THREE.Vector3();
              raycaster.ray.intersectPlane(plane, intersectPoint);
              if (relocalizeRobotPosRef.current) {
                relocalizeRobotPosRef.current.x = intersectPoint.x;
                relocalizeRobotPosRef.current.y = intersectPoint.y;
                console.log('[MapView] Robot position set to:', relocalizeRobotPosRef.current);
              }
            } else if (event.button === 2) {
              isRotatingRobotRef.current = true;
              console.log('[MapView] Robot rotation started');
            }
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          obj = obj.parent as THREE.Object3D;
        }
      }
    };

    const handleMouseUp = () => {
      isDraggingRobotRef.current = false;
      isRotatingRobotRef.current = false;
    };

    const handleContextMenu = (event: MouseEvent) => {
      if (relocalizeModeRef.current) {
        event.preventDefault();
      }
    };

    const handleMouseMove = (event: MouseEvent) => {
      if (!camera || !canvas) return;

      const rect = canvas.getBoundingClientRect();
      const mouse = new THREE.Vector2();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
      const intersectPoint = new THREE.Vector3();
      raycaster.ray.intersectPlane(plane, intersectPoint);

      if (relocalizeModeRef.current) {
        if (isDraggingRobotRef.current && relocalizeRobotPosRef.current) {
          relocalizeRobotPosRef.current.x = intersectPoint.x;
          relocalizeRobotPosRef.current.y = intersectPoint.y;
          const robotLayer = layerManagerRef.current?.getLayer('robot');
          if (robotLayer && 'setRelocalizePosition' in robotLayer) {
            (robotLayer as any).setRelocalizePosition(relocalizeRobotPosRef.current);
          }
          const laserScanLayer = layerManagerRef.current?.getLayer('laser_scan');
          if (laserScanLayer && 'setRelocalizeMode' in laserScanLayer) {
            (laserScanLayer as any).setRelocalizeMode(true, relocalizeRobotPosRef.current);
          }
        }
      }

      setMouseWorldPos({ x: intersectPoint.x, y: intersectPoint.y });
    };

    const handleRightMouseMove = (event: MouseEvent) => {
      if (!relocalizeModeRef.current || !isRotatingRobotRef.current || !camera || !canvas || !relocalizeRobotPosRef.current) return;

      const rect = canvas.getBoundingClientRect();
      const mouse = new THREE.Vector2();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
      const intersectPoint = new THREE.Vector3();
      raycaster.ray.intersectPlane(plane, intersectPoint);

      const dx = intersectPoint.x - relocalizeRobotPosRef.current.x;
      const dy = intersectPoint.y - relocalizeRobotPosRef.current.y;
      relocalizeRobotPosRef.current.theta = Math.atan2(dy, dx);

      const robotLayer = layerManagerRef.current?.getLayer('robot');
      if (robotLayer && 'setRelocalizePosition' in robotLayer) {
        (robotLayer as any).setRelocalizePosition(relocalizeRobotPosRef.current);
      }
      const laserScanLayer = layerManagerRef.current?.getLayer('laser_scan');
      if (laserScanLayer && 'setRelocalizeMode' in laserScanLayer) {
        (laserScanLayer as any).setRelocalizeMode(true, relocalizeRobotPosRef.current);
      }
    };

    const handleMouseLeave = () => {
      setMouseWorldPos(null);
    };

    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('contextmenu', handleContextMenu);
    const handleMouseMoveWrapper = (event: MouseEvent) => {
      handleMouseMove(event);
      if (event.buttons === 2) {
        handleRightMouseMove(event);
      }
    };
    canvas.addEventListener('mousemove', handleMouseMoveWrapper);
    canvas.addEventListener('mouseleave', handleMouseLeave);

    console.log('[MapView] Creating LayerManager');
    const layerManager = new LayerManager(scene, connection);
    layerManagerRef.current = layerManager;

    const handleResize = () => {
      if (!camera || !renderer || !canvas.parentElement) return;
      const width = canvas.parentElement.clientWidth;
      const height = canvas.parentElement.clientHeight;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };

    window.addEventListener('resize', handleResize);

    // 移除这里的 updateRobotPosition，因为它会在每一帧都调用 setRobotPos，导致无限循环
    // 机器人位置更新由下面的 useEffect 处理，它有阈值检查

    let animationFrameId: number;
    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      if (controls && camera) {
        if (focusRobotRef.current) {
          const robotConfig = layerConfigsRef.current.robot;
          if (robotConfig) {
            const baseFrame = (robotConfig as any).baseFrame || 'base_link';
            const mapFrame = (robotConfig as any).mapFrame || 'map';
            const tf2js = TF2JS.getInstance();
            const transform = tf2js.findTransform(mapFrame, baseFrame);
            if (transform) {
              const targetZ = viewModeRef.current === '2d' ? 0 : transform.translation.z;
              controls.target.set(
                transform.translation.x,
                transform.translation.y,
                targetZ
              );
            }
          }
        }

        // 机器人位置更新由下面的 useEffect 处理，避免在动画循环中调用 setState
        controls.update();
      }
      if (renderer && scene && camera) {
        renderer.render(scene, camera);
      }
    };
    animate();

    return () => {
      window.removeEventListener('resize', handleResize);
      canvas.removeEventListener('click', handleClick);
      canvas.removeEventListener('mousedown', handleMouseDown);
      canvas.removeEventListener('mouseup', handleMouseUp);
      canvas.removeEventListener('contextmenu', handleContextMenu);
      canvas.removeEventListener('mousemove', handleMouseMoveWrapper);
      canvas.removeEventListener('mouseleave', handleMouseLeave);
      cancelAnimationFrame(animationFrameId);
      timeoutRefsRef.current.forEach(timeoutId => clearTimeout(timeoutId));
      timeoutRefsRef.current.clear();
      controls.dispose();
      layerManager.dispose();
      if (renderer) {
        renderer.dispose();
      }
    };
  }, [connection]);

  useEffect(() => {
    if (!connection.isConnected()) {
      return;
    }

    const updateRobotPosition = () => {
      const robotConfig = layerConfigsRef.current.robot;
      if (!robotConfig) {
        return;
      }

      const baseFrame = (robotConfig as any).baseFrame || 'base_link';
      const mapFrame = (robotConfig as any).mapFrame || 'map';
      const tf2js = TF2JS.getInstance();
      const transform = tf2js.findTransform(mapFrame, baseFrame);

      if (transform) {
        const robotEuler = new THREE.Euler();
        robotEuler.setFromQuaternion(transform.rotation, 'XYZ');
        const robotTheta = robotEuler.z;

        const newPos = {
          x: transform.translation.x,
          y: transform.translation.y,
          theta: robotTheta,
        };

        // 只在位置真正改变时才更新，避免无限循环
        setRobotPos((prev) => {
          if (!prev) return newPos;
          const dx = Math.abs(prev.x - newPos.x);
          const dy = Math.abs(prev.y - newPos.y);
          const dtheta = Math.abs(prev.theta - newPos.theta);
          // 如果变化很小（小于1mm和0.001弧度），不更新
          if (dx < 0.001 && dy < 0.001 && dtheta < 0.001) {
            return prev;
          }
          return newPos;
        });
      }
    };

    const tf2js = TF2JS.getInstance();
    const unsubscribe = tf2js.onTransformChange(() => {
      updateRobotPosition();
    });

    updateRobotPosition();

    const intervalId = setInterval(() => {
      updateRobotPosition();
    }, 100);

    return () => {
      unsubscribe();
      clearInterval(intervalId);
    };
  }, [connection, layerConfigs]);

  useConnectionInit(connection, layerManagerRef);

  useNavigationMode(
    navigationMode,
    navigationModeRef,
    navigationPoints,
    setNavigationPoints,
    layerConfigsRef,
    layerManagerRef,
    controlsRef,
    cameraRef,
    canvasRef,
    raycasterRef,
    sceneRef
  );

  useLayerConfigSync(
    layerConfigs,
    layerConfigsRef,
    layerManagerRef,
    connection,
    cmdVelTopicRef,
    initialposeTopicRef
  );

  const handleConfigChange = (layerId: string, config: Partial<import('../types/LayerConfig').LayerConfig>) => {
    setLayerConfigs((prev) => {
      const updated = { ...prev };
      if (layerId === '' && Object.keys(config).length === 0) {
        return prev;
      }
      if (updated[layerId]) {
        updated[layerId] = { ...updated[layerId]!, ...config };
      } else if (Object.keys(config).length > 0) {
        updated[layerId] = config as import('../types/LayerConfig').LayerConfig;
      }
      const filtered = Object.fromEntries(
        Object.entries(updated).filter(([_, cfg]) => cfg !== undefined)
      );
      saveLayerConfigs(filtered);
      return filtered;
    });
  };

  useEffect(() => {
    focusRobotRef.current = focusRobot;
  }, [focusRobot]);

  const handleViewModeToggle = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setViewMode((prev) => {
      const newMode = prev === '2d' ? '3d' : '2d';
      viewModeRef.current = newMode;
      console.log(`切换视图模式: ${prev} -> ${newMode}`);
      return newMode;
    });
  };

  const handleFocusRobotToggle = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setFocusRobot((prev) => !prev);
  };


  const handleFullscreenToggle = async (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();

    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (error) {
      console.error('全屏操作失败:', error);
      toast.error('全屏操作失败');
    }
  };

  const handleRelocalizeToggle = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!navigationSystem?.stack_ready) {
      toast.error(navigationSystem?.message ?? '请先启动定位与 Nav2');
      return;
    }
    if (!relocalizeMode && !hasControlLease) {
      toast.error('请先进入左侧“控制”页面，点击“接管控制”');
      return;
    }
    const newMode = !relocalizeMode;
    setRelocalizeMode(newMode);
    if (newMode) {
      if (viewMode !== '2d') {
        setViewMode('2d');
        viewModeRef.current = '2d';
      }

      const timeoutId = setTimeout(() => {
        if (!controlsRef.current || !cameraRef.current) return;

        const robotConfig = layerConfigsRef.current.robot;
        if (robotConfig) {
          const baseFrame = (robotConfig as any).baseFrame || 'base_link';
          const mapFrame = (robotConfig as any).mapFrame || 'map';
          const tf2js = TF2JS.getInstance();
          const transform = tf2js.findTransform(mapFrame, baseFrame);

          if (transform) {
            const controls = controlsRef.current;
            const camera = cameraRef.current;

            controls.target.set(
              transform.translation.x,
              transform.translation.y,
              0
            );

            const distance = Math.max(10, camera.position.distanceTo(controls.target));
            camera.position.set(
              controls.target.x,
              controls.target.y,
              controls.target.z + distance
            );
            camera.up.set(0, 0, 1);
            camera.quaternion.setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0, 'XYZ'));

            controls.update();
          } else if (relocalizeRobotPosRef.current) {
            const controls = controlsRef.current;
            const camera = cameraRef.current;
            const pos = relocalizeRobotPosRef.current;

            controls.target.set(pos.x, pos.y, 0);

            const distance = Math.max(10, camera.position.distanceTo(controls.target));
            camera.position.set(
              controls.target.x,
              controls.target.y,
              controls.target.z + distance
            );
            camera.up.set(0, 0, 1);
            camera.quaternion.setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0, 'XYZ'));

            controls.update();
          }
        }
        timeoutRefsRef.current.delete(timeoutId);
      }, 100);
      timeoutRefsRef.current.add(timeoutId);
    }
  };

  const handleRelocalizeConfirm = async () => {
    if (!relocalizeRobotPosRef.current || !connection.isConnected()) {
      toast.error('无法发布初始化位姿');
      return;
    }

    const pos = relocalizeRobotPosRef.current;
    setRelocalizeSubmitting(true);
    try {
      await client.setInitialPose({ x: pos.x, y: pos.y, yaw: pos.theta });
      toast.success('重定位位姿已提交，正在校准实时位置');
      setRelocalizeMode(false);
    } catch (error) {
      if (error instanceof Error && error.message === 'control lease required') {
        toast.error('请先进入左侧“控制”页面，点击“接管控制”，再确认重定位');
      } else {
        toast.error(error instanceof Error ? `重定位提交失败：${error.message}` : '重定位提交失败');
      }
    } finally {
      setRelocalizeSubmitting(false);
    }
  };

  const handleRelocalizeCancel = () => {
    setRelocalizeMode(false);
  };

  const handleNavigationToggle = (mode: 'single' | 'multi') => {
    if (!navigationSystem?.ready) {
      toast.error(navigationSystem?.message ?? '请先启动定位与 Nav2');
      return;
    }
    if (navigationMode === mode) {
      setNavigationMode(null);
      setNavigationPoints([]);
    } else {
      setNavigationMode(mode);
      if (mode === 'single') {
        setNavigationPoints([]);
      }
    }
  };

  const handleNavigationClose = () => {
    setNavigationMode(null);
    setNavigationPoints([]);
  };

  useEffect(() => {
    if (workspaceMode !== 'navigation') {
      setNavigationMode(null);
      setNavigationPoints([]);
      setRelocalizeMode(false);
    }
  }, [workspaceMode]);

  const handleClearNavigationPoints = () => {
    setNavigationPoints([]);
  };

  const handleRemoveNavigationPoint = (id: string) => {
    setNavigationPoints((prev) => prev.filter((p) => p.id !== id));
  };


  const handleNavigate = async (points: NavigationPoint[]) => {
    console.log('🚀🚀🚀 [MapView] ========== handleNavigate CALLED ==========');
    console.log('[MapView] Points received:', points.length);
    console.log('[MapView] Connection status:', connection.isConnected());
    console.log('[MapView] Points details:', points.map((p, i) => ({
      index: i + 1,
      id: p.id,
      x: p.x.toFixed(3),
      y: p.y.toFixed(3),
      theta: p.theta.toFixed(3),
    })));

    if (!navigationSystem?.ready) {
      toast.error(navigationSystem?.message ?? '定位与 Nav2 尚未就绪');
      return;
    }

    if (!connection.isConnected()) {
      console.error('[MapView] Cannot navigate: not connected to ROS2');
      toast.error('未连接到ROS2，无法发送导航目标');
      return;
    }

    if (points.length === 0) {
      console.error('[MapView] Cannot navigate: no points provided');
      toast.error('没有设置导航目标点');
      return;
    }

    const robotConfig = layerConfigsRef.current.robot;
    const mapFrame = (robotConfig as any)?.mapFrame || 'map';

    if (points.length === 1) {
      // 单点导航
      const point = points[0]!;

      try {
        // 确保路径层启用 - 直接更新 layerManager，避免触发 state 更新循环
        const planConfig = layerConfigsRef.current.plan;
        const localPlanConfig = layerConfigsRef.current.local_plan;
        let needUpdate = false;

        if (planConfig && !planConfig.enabled) {
          console.log('[MapView] Enabling plan layer for path visualization');
          layerConfigsRef.current.plan = { ...planConfig, enabled: true };
          needUpdate = true;
        }
        if (localPlanConfig && !localPlanConfig.enabled) {
          console.log('[MapView] Enabling local_plan layer for path visualization');
          layerConfigsRef.current.local_plan = { ...localPlanConfig, enabled: true };
          needUpdate = true;
        }

        // 只在需要时更新 layerManager
        if (needUpdate && layerManagerRef.current) {
          layerManagerRef.current.setLayerConfigs(layerConfigsRef.current);
        }

        await client.navigateToPose({ x: point.x, y: point.y, yaw: point.theta });
        console.log('[MapView] Published single-point navigation goal:', {
          topic: goalPoseTopicRef.current,
          position: { x: point.x, y: point.y },
          orientation: { theta: point.theta },
          frame: mapFrame,
        });
        toast.success(`已发送单点导航目标 (${point.x.toFixed(2)}, ${point.y.toFixed(2)})`);
        setNavigationMode(null);
        // 不清空 navigationPoints，保留在任务队列中显示
        // setNavigationPoints([]);
      } catch (error) {
        console.error('Failed to publish navigation goal:', error);
        toast.error(navigationErrorMessage(error));
      }
    } else {
      // 多点导航 - 一次性发送所有点，让Navigation2规划完整路径
      console.log('🎯🎯🎯 [MapView] ========== MULTI-POINT NAVIGATION START ==========');
      console.log('[MapView] Total points:', points.length);
      console.log('[MapView] Map frame:', mapFrame);
      points.forEach((p, i) => {
        console.log(`[MapView] Point ${i + 1}: x=${p.x.toFixed(3)}, y=${p.y.toFixed(3)}, theta=${p.theta.toFixed(3)}`);
      });

      // 确保路径层启用
      try {
        await client.navigateThroughPoses(
          points.map((point) => ({
            x: point.x,
            y: point.y,
            yaw: point.theta,
          })),
        );
        toast.success(`已发送 ${points.length} 个导航点`);
        setNavigationMode(null);
        return;
      } catch (error) {
        toast.error(navigationErrorMessage(error));
        return;
      }

      const multiPlanConfig = layerConfigsRef.current.plan;
      const multiLocalPlanConfig = layerConfigsRef.current.local_plan;
      if (multiPlanConfig && !multiPlanConfig.enabled && layerManagerRef.current) {
        layerConfigsRef.current.plan = { ...multiPlanConfig, enabled: true };
        layerManagerRef.current?.setLayerConfigs(layerConfigsRef.current);
      }
      if (multiLocalPlanConfig && !multiLocalPlanConfig.enabled && layerManagerRef.current) {
        layerConfigsRef.current.local_plan = { ...multiLocalPlanConfig, enabled: true };
        layerManagerRef.current?.setLayerConfigs(layerConfigsRef.current);
      }

      // 构建所有点的 PoseStamped 数组，用于一次性发送
      const now = Date.now();
      const stamp = {
        sec: Math.floor(now / 1000),
        nanosec: (now % 1000) * 1000000,
      };

      const poses = points.map((point) => {
        const quaternion = new THREE.Quaternion();
        quaternion.setFromEuler(new THREE.Euler(0, 0, point.theta, 'XYZ'));

        return {
          header: {
            stamp: stamp,
            frame_id: mapFrame,
          },
          pose: {
            position: {
              x: point.x,
              y: point.y,
              z: 0,
            },
            orientation: {
              x: quaternion.x,
              y: quaternion.y,
              z: quaternion.z,
              w: quaternion.w,
            },
          },
        };
      });

      console.log('[MapView] ========== MULTI-POINT NAVIGATION (ALL POINTS AT ONCE) ==========');
      console.log('[MapView] Total points:', points.length);
      console.log('[MapView] Map frame:', mapFrame);
      console.log('[MapView] Built', poses.length, 'poses for complete path generation');
      poses.forEach((p, i) => {
        console.log(`[MapView] Point ${i + 1}/${poses.length}: x=${p.pose.position.x.toFixed(3)}, y=${p.pose.position.y.toFixed(3)}`);
      });

      // 确保路径层启用，以便显示完整路径
      const planConfig = layerConfigsRef.current.plan;
      const localPlanConfig = layerConfigsRef.current.local_plan;
      if (planConfig && !planConfig.enabled && layerManagerRef.current) {
        layerConfigsRef.current.plan = { ...planConfig, enabled: true };
        layerManagerRef.current?.setLayerConfigs(layerConfigsRef.current);
      }
      if (localPlanConfig && !localPlanConfig.enabled && layerManagerRef.current) {
        layerConfigsRef.current.local_plan = { ...localPlanConfig, enabled: true };
        layerManagerRef.current?.setLayerConfigs(layerConfigsRef.current);
      }

      // 尝试使用 navigate_through_poses action 一次性发送所有点
      // ROS2 action 的内部话题格式：/action_name/_action/send_goal
      // 消息类型：action_msgs/msg/GoalID + action goal
      const actionGoalTopic = '/navigate_through_poses/_action/send_goal';

      // 生成唯一的 goal_id (ROS2 action 需要)
      const goalId = {
        stamp: stamp,
        id: `multi_point_nav_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      };

      console.log('[MapView] ========== ATTEMPTING TO SEND ALL POINTS AT ONCE ==========');
      console.log('[MapView] Action goal topic:', actionGoalTopic);
      console.log('[MapView] Goal ID:', goalId.id);
      console.log('[MapView] Total poses to send:', poses.length);
      console.log('[MapView] Poses:', poses.map((p, i) => ({
        index: i + 1,
        x: p.pose.position.x.toFixed(3),
        y: p.pose.position.y.toFixed(3),
      })));

      // 由于 rosbridge 不支持直接调用 ROS2 action，我们使用最可靠的方法：
      // 快速连续发送所有点到 /goal_pose，让 Navigation2 能够接收并规划路径
      // 注意：这不是真正的"一次性生成所有点路径"，但可以让 Navigation2 快速接收所有点

      console.log('[MapView] ========== MULTI-POINT NAVIGATION (RAPID SEQUENTIAL) ==========');
      console.log('[MapView] Total points:', points.length);
      console.log('[MapView] Strategy: Rapidly sending all points to /goal_pose');
      console.log('[MapView] Navigation2 will process these goals and generate paths');

      // 确保路径层启用，以便显示路径
      const reliablePlanConfig = layerConfigsRef.current.plan;
      const reliableLocalPlanConfig = layerConfigsRef.current.local_plan;
      if (reliablePlanConfig && !reliablePlanConfig.enabled && layerManagerRef.current) {
        console.log('[MapView] Enabling plan layer for path visualization');
        layerConfigsRef.current.plan = { ...reliablePlanConfig, enabled: true };
        layerManagerRef.current?.setLayerConfigs(layerConfigsRef.current);
      }
      if (reliableLocalPlanConfig && !reliableLocalPlanConfig.enabled && layerManagerRef.current) {
        console.log('[MapView] Enabling local_plan layer for path visualization');
        layerConfigsRef.current.local_plan = { ...reliableLocalPlanConfig, enabled: true };
        layerManagerRef.current?.setLayerConfigs(layerConfigsRef.current);
      }

      // 设置待发送的点队列
      pendingNavigationPointsRef.current = [...points];
      currentNavigationIndexRef.current = 0;

      // 快速连续发送所有点（间隔很短，让 Navigation2 能够接收）
      let allSent = true;
      let sendError: string | null = null;

      for (let i = 0; i < points.length; i++) {
        const point = points[i]!;
        const quaternion = new THREE.Quaternion();
        quaternion.setFromEuler(new THREE.Euler(0, 0, point.theta, 'XYZ'));

        const message = {
          header: {
            stamp: {
              sec: Math.floor(Date.now() / 1000),
              nanosec: (Date.now() % 1000) * 1000000,
            },
            frame_id: mapFrame,
          },
          pose: {
            position: {
              x: point.x,
              y: point.y,
              z: 0,
            },
            orientation: {
              x: quaternion.x,
              y: quaternion.y,
              z: quaternion.z,
              w: quaternion.w,
            },
          },
        };

        try {
          // 使用 setTimeout 来间隔发送，确保 Navigation2 能处理每个点
          await new Promise<void>((resolve) => {
            setTimeout(() => {
              try {
                console.debug('[MapView] legacy direct multi-goal path disabled', message);
                console.log(`[MapView] ✅ Sent point ${i + 1}/${points.length}: (${point.x.toFixed(2)}, ${point.y.toFixed(2)})`);
                resolve();
              } catch (error: any) {
                console.error(`[MapView] ❌ Failed to send point ${i + 1}:`, error?.message || String(error));
                sendError = error?.message || String(error);
                allSent = false;
                resolve();
              }
            }, i * 50); // 每个点间隔50ms，快速发送
          });
        } catch (error: any) {
          console.error(`[MapView] ❌ Error sending point ${i + 1}:`, error);
          sendError = error?.message || String(error);
          allSent = false;
        }
      }

      if (allSent) {
        console.log('[MapView] ✅✅✅ All points sent successfully!');
        console.log('[MapView] Navigation2 will process these goals and generate paths');
        toast.success(`✅ 多点导航已启动 (${points.length}个点)，已发送所有点`);
        setNavigationMode(null);
        // 不清空 navigationPoints，保留在任务队列中显示
        // setNavigationPoints([]);
        // 保留队列用于状态监听器自动发送后续点（如果需要）
        // 但实际上所有点都已经发送了，Navigation2 应该会处理它们
      } else {
        console.error('[MapView] ❌❌❌ Failed to send some points!');
        console.error('[MapView] Error:', sendError);
        toast.error(`发送多点导航失败：${sendError || '未知错误'}`);
        pendingNavigationPointsRef.current = [];
        currentNavigationIndexRef.current = -1;
      }
    }
  };

  // 监听导航状态，用于多点导航时自动发送下一个点
  useEffect(() => {
    if (!connection.isConnected()) {
      return;
    }

    const robotConfig = layerConfigsRef.current.robot;
    const mapFrame = (robotConfig as any)?.mapFrame || 'map';
    const statusTopic = '/navigate_to_pose/_action/status';

    console.log('[MapView] ========== SETTING UP NAVIGATION STATUS LISTENER ==========');
    console.log('[MapView] Status topic:', statusTopic);
    console.log('[MapView] Message type: action_msgs/msg/GoalStatusArray');
    console.log('[MapView] This listener will monitor navigation status and auto-send next points');

    let unsubscribeStatus: (() => void) | null = null;
    try {
      unsubscribeStatus = connection.subscribe(
        statusTopic,
        'action_msgs/msg/GoalStatusArray',
        (message: any) => {
          const pendingCount = pendingNavigationPointsRef.current.length;
          const currentIdx = currentNavigationIndexRef.current;

          // 只在有待发送的点时才处理
          if (pendingCount === 0) {
            return;
          }

          console.log('[MapView] 📊 Status message received:', {
            pendingPoints: pendingCount,
            currentIndex: currentIdx,
            hasStatusList: !!message.status_list,
            statusListLength: message.status_list?.length || 0,
          });

          if (message.status_list && message.status_list.length > 0) {
            const statusInfo = message.status_list[0];
            const status = statusInfo?.status;
            const pendingPoints = pendingNavigationPointsRef.current;
            const currentIndex = currentNavigationIndexRef.current;

            console.log('[MapView] ========== NAVIGATION STATUS UPDATE ==========');
            console.log('[MapView] Status:', status, '(3=SUCCEEDED, 4=ABORTED, 2=EXECUTING)');
            console.log('[MapView] Pending points:', pendingPoints.length);
            console.log('[MapView] Current index:', currentIndex);

            // status === 3 表示 SUCCEEDED (到达目标)
            // status === 4 表示 ABORTED (失败)
            if (status === 3 && pendingPoints.length > 0) {
              console.log(`[MapView] ✅ Point ${currentIndex + 1}/${pendingPoints.length} REACHED!`);

              // 检查是否还有下一个点
              if (currentIndex >= 0 && currentIndex < pendingPoints.length - 1) {
                const nextIndex = currentIndex + 1;
                const nextPoint = pendingPoints[nextIndex];

                if (nextPoint) {
                  console.log(`[MapView] Preparing to send next point ${nextIndex + 1}/${pendingPoints.length}: (${nextPoint.x.toFixed(2)}, ${nextPoint.y.toFixed(2)})`);

                  // 等待一小段时间，确保上一个目标已完成
                  setTimeout(() => {
                    // 再次检查，确保状态没有变化
                    if (pendingNavigationPointsRef.current.length === 0 || currentNavigationIndexRef.current !== currentIndex) {
                      console.log('[MapView] Navigation state changed, skipping next point send');
                      return;
                    }

                    const quaternion = new THREE.Quaternion();
                    quaternion.setFromEuler(new THREE.Euler(0, 0, nextPoint.theta, 'XYZ'));

                    const nextMessage = {
                      header: {
                        stamp: {
                          sec: Math.floor(Date.now() / 1000),
                          nanosec: (Date.now() % 1000) * 1000000,
                        },
                        frame_id: mapFrame,
                      },
                      pose: {
                        position: {
                          x: nextPoint.x,
                          y: nextPoint.y,
                          z: 0,
                        },
                        orientation: {
                          x: quaternion.x,
                          y: quaternion.y,
                          z: quaternion.z,
                          w: quaternion.w,
                        },
                      },
                    };

                    try {
                      console.debug('[MapView] legacy automatic goal path disabled', nextMessage);
                      currentNavigationIndexRef.current = nextIndex;
                      console.log(`[MapView] ✅✅✅ Auto-sent next point (${nextIndex + 1}/${pendingPoints.length}): (${nextPoint.x.toFixed(2)}, ${nextPoint.y.toFixed(2)})`);
                      toast.info(`已到达第${nextIndex + 1}个点，正在前往第${nextIndex + 2}个点`);
                    } catch (error) {
                      console.error('[MapView] ❌ Failed to send next navigation point:', error);
                      toast.error('发送下一个导航目标失败');
                      pendingNavigationPointsRef.current = [];
                      currentNavigationIndexRef.current = -1;
                    }
                  }, 300); // 减少等待时间到300ms
                }
              } else if (currentIndex >= 0 && currentIndex === pendingPoints.length - 1) {
                // 所有点都已完成
                console.log('[MapView] ✅ All navigation points completed (fallback mode)');
                toast.success(`多点导航完成！已到达所有${pendingPoints.length}个点`);
                pendingNavigationPointsRef.current = [];
                currentNavigationIndexRef.current = -1;
              }
            } else if (status === 4) {
              // 导航失败 - 只在确实有错误时才报错
              console.warn('[MapView] ⚠️ Navigation ABORTED');
              const currentIndex = currentNavigationIndexRef.current;
              const pendingPoints = pendingNavigationPointsRef.current;

              // 只有在多点导航模式（有待发送的点）且不是最后一个点时才报错
              // 如果已经到达最后一个点，状态可能是正常的
              if (pendingPoints.length > 0 && currentIndex >= 0 && currentIndex < pendingPoints.length - 1) {
                console.error('[MapView] Navigation failed at point', currentIndex + 1);
                toast.error(`导航到第${currentIndex + 1}个点失败`);
                pendingNavigationPointsRef.current = [];
                currentNavigationIndexRef.current = -1;
              } else if (pendingPoints.length > 0 && currentIndex === pendingPoints.length - 1) {
                // 最后一个点失败，可能是正常的完成状态
                console.log('[MapView] Last point navigation completed (may show as ABORTED but is normal)');
                pendingNavigationPointsRef.current = [];
                currentNavigationIndexRef.current = -1;
              }
            }
          }
        }
      );
    } catch (error) {
      console.error('[MapView] ❌ Failed to subscribe to navigation status:', error);
    }

    // 清理函数：取消订阅
    return () => {
      try {
        unsubscribeStatus?.();
      } catch {
        // Ignore
      }
    };
  }, [connection, goalPoseTopicRef]);

  return (
    <div className={`MapView workspace-${workspaceMode}`}>
      <div className="ViewControls">
        <button
          className={`ViewButton ${viewMode === '2d' ? 'active' : ''}`}
          onClick={handleViewModeToggle}
          title={`当前: ${viewMode === '2d' ? '2D' : '3D'}视图，点击切换到${viewMode === '2d' ? '3D' : '2D'}`}
          type="button"
        >
          {viewMode === '2d' ? '2D 视图' : '3D 视图'}
        </button>
        <button
          className="SettingsButton"
          onClick={() => setShowSettings(!showSettings)}
          title="图层配置"
          type="button"
        >
          <span className="ButtonIcon">⌘</span>
          <span className="ButtonLabel">图层</span>
        </button>
        <button
          className={`SettingsButton ${isFullscreen ? 'active' : ''}`}
          onClick={handleFullscreenToggle}
          title={isFullscreen ? '退出全屏' : '进入全屏'}
          type="button"
        >
          <span className="ButtonIcon">{isFullscreen ? '▣' : '□'}</span>
          <span className="ButtonLabel">{isFullscreen ? '退出' : '全屏'}</span>
        </button>
      </div>
      {workspaceMode === 'navigation' && (
        <aside className="navigation-workspace-panel" aria-label="导航工作区">
          <header>
            <div><span>导航功能</span><h2>定位与任务</h2></div>
            <b>{connection.isConnected() ? 'ROS 已连接' : 'ROS 未连接'}</b>
          </header>
          <NavigationSystemPanel
            client={client}
            onStatusChange={setNavigationSystem}
          />
          <p className="navigation-workspace-help">
            先完成重定位，再选择单点或多点模式，然后在公共地图上设置目标。
          </p>
          <div className="navigation-workspace-actions">
            <button
              ref={relocalizeButtonRef}
              className={relocalizeMode ? 'active' : ''}
              onClick={handleRelocalizeToggle}
              disabled={!navigationSystem?.stack_ready}
              title={navigationSystem?.stack_ready ? '设置机器人初始位姿' : navigationSystem?.message}
              type="button"
            >
              ◎ 重定位
            </button>
            <button
              className={navigationMode === 'single' ? 'active' : ''}
              onClick={() => handleNavigationToggle('single')}
              disabled={!navigationSystem?.ready}
              title={navigationSystem?.ready ? '在地图上设置一个目标点' : navigationSystem?.message}
              type="button"
            >
              单点导航
            </button>
            <button
              className={navigationMode === 'multi' ? 'active' : ''}
              onClick={() => handleNavigationToggle('multi')}
              disabled={!navigationSystem?.ready}
              title={navigationSystem?.ready ? '在地图上设置多个目标点' : navigationSystem?.message}
              type="button"
            >
              多点导航
            </button>
          </div>
          {navigationMode ? (
            <NavigationPanel
              docked
              navigationMode={navigationMode}
              navigationPoints={navigationPoints}
              onClose={handleNavigationClose}
              onClearPoints={handleClearNavigationPoints}
              onRemovePoint={handleRemoveNavigationPoint}
              onNavigate={handleNavigate}
              connection={connection}
            />
          ) : (
            <div className="navigation-workspace-empty">
              <b>尚未开始选点</b>
              <span>选择上方导航方式后，地图会进入目标点设置状态。</span>
            </div>
          )}
          <TaskManagementPanel
            docked
            connection={connection}
            navigationPoints={navigationPoints}
            onRemoveTask={handleRemoveNavigationPoint}
            onReorderTasks={(fromIndex, toIndex) => {
              setNavigationPoints((prev) => {
                const updated = [...prev];
                const [moved] = updated.splice(fromIndex, 1);
                updated.splice(toIndex, 0, moved!);
                return updated;
              });
            }}
          />
        </aside>
      )}
      {relocalizeMode && (
        <div ref={relocalizeControlsRef} className="RelocalizeControls" style={relocalizeControlsStyle}>
          <button
            className="RelocalizeButton ConfirmButton"
            onClick={handleRelocalizeConfirm}
            disabled={relocalizeSubmitting}
            type="button"
          >
            {relocalizeSubmitting ? '提交中…' : '确定'}
          </button>
          <button
            className="RelocalizeButton CancelButton"
            onClick={handleRelocalizeCancel}
            type="button"
          >
            取消
          </button>
        </div>
      )}
      <SystemLogPanel connection={connection} />
      <div className="BottomControls">
        <button
          className={`FocusRobotButton ${focusRobot ? 'active' : ''}`}
          onClick={handleFocusRobotToggle}
          title={focusRobot ? '取消跟随机器人' : '跟随机器人'}
          type="button"
        >
          {focusRobot ? '跟随中' : '跟随机器人'}
        </button>
      </div>
      {showSettings && (
        <LayerSettingsPanel
          layerConfigs={layerConfigs}
          onConfigChange={handleConfigChange}
          onResetToDefaults={() => {
            setLayerConfigs(DEFAULT_LAYER_CONFIGS);
            saveLayerConfigs(DEFAULT_LAYER_CONFIGS);
          }}
          onClose={() => setShowSettings(false)}
          onDeleteLayer={(layerId) => {
            setLayerConfigs((prev) => {
              const updated = { ...prev };
              delete updated[layerId];
              saveLayerConfigs(updated);
              return updated;
            });
            imagePositionsRef.current.delete(layerId);
            const positionsMap: ImagePositionsMap = {};
            imagePositionsRef.current.forEach((pos, id) => {
              positionsMap[id] = pos;
            });
            saveImagePositions(positionsMap);
          }}
          onUrdfConfigChange={async () => {
            const robotLayer = layerManagerRef.current?.getLayer('robot');
            if (robotLayer && 'reloadUrdf' in robotLayer) {
              try {
                await (robotLayer as any).reloadUrdf();
              } catch (error) {
                console.error('[MapView] Failed to reload URDF:', error);
                toast.error('加载 URDF 模型失败: ' + (error instanceof Error ? error.message : '未知错误'));
              }
            }
          }}
        />
      )}
      {workspaceMode === 'maps' && (
        <MapEditor
          connection={connection}
          client={client}
          onClose={() => onWorkspaceModeChange('navigation')}
        />
      )}
      <TopoPointInfoPanel
        selectedPoint={selectedTopoPoint}
        selectedRoute={selectedTopoRoute}
        onClose={() => {
          setSelectedTopoPoint(null);
          setSelectedTopoRoute(null);
          const topoLayer = layerManagerRef.current?.getLayer('topology');
          if (topoLayer && 'setSelectedPoint' in topoLayer) {
            (topoLayer as any).setSelectedPoint(null);
          }
          if (topoLayer && 'setSelectedRoute' in topoLayer) {
            (topoLayer as any).setSelectedRoute(null);
          }
        }}
        client={client}
      />
      <canvas
        ref={canvasRef}
        className="MapCanvas"
        tabIndex={0}
        style={{ outline: 'none' }}
      />
      {Array.from(imageLayers.entries())
        .filter(([layerId]) => layerConfigs[layerId]?.enabled)
        .map(([layerId, imageData]) => {
          const config = layerConfigs[layerId];
          const position = imagePositionsRef.current.get(layerId) || { x: 100, y: 100, scale: 1 };
          return (
            <ImageDisplay
              key={layerId}
              imageData={imageData}
              name={config?.name || layerId}
              position={position}
              onPositionChange={(newPos) => {
                imagePositionsRef.current.set(layerId, newPos);
                const positionsMap: ImagePositionsMap = {};
                imagePositionsRef.current.forEach((pos, id) => {
                  positionsMap[id] = pos;
                });
                saveImagePositions(positionsMap);
              }}
            />
          );
        })}
    </div>
  );
}

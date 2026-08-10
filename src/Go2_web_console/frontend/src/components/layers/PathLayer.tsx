/**
 * 路径图层
 *
 * 显示机器人的规划路径和实际路径。
 *
 * @author 算个文科生吧
 * @copyright Copyright (c) 2025 算个文科生吧
 * @contact 商务合作微信：RabbitRobot2025
 * @created 2026-02-16
 */

import * as THREE from 'three';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { BaseLayer } from './BaseLayer';
import type { LayerConfig } from '../../types/LayerConfig';
import type { RosbridgeConnection } from '../../utils/RosbridgeConnection';
import { TF2JS } from '../../utils/tf2js';

interface Point {
  x: number;
  y: number;
  z: number;
}

interface Pose {
  position: Point;
  orientation: { x: number; y: number; z: number; w: number };
}

interface PoseStamped {
  pose: Pose;
}

interface Path {
  header: {
    frame_id: string;
  };
  poses: PoseStamped[];
}

export class PathLayer extends BaseLayer {
  private line: Line2 | null = null;
  private color: number;
  private lineWidth: number;
  private tf2js: TF2JS;
  private mapFrame: string;

  constructor(scene: THREE.Scene, config: LayerConfig, connection: RosbridgeConnection | null = null) {
    super(scene, config, connection);
    this.tf2js = TF2JS.getInstance();
    this.mapFrame = (config.mapFrame as string | undefined) || 'map';
    this.color = (config.color as number | undefined) || 0x00ff00;
    // WebGL ignores LineBasicMaterial.linewidth on most browsers.  Line2 uses
    // screen-space pixels, so both global and local plans stay visible.
    this.lineWidth = Math.max((config.lineWidth as number | undefined) ?? 5, 5);
    if (config.topic) {
      this.subscribe(config.topic, this.getMessageType());
    }
  }

  getMessageType(): string | null {
    return 'nav_msgs/Path';
  }

  update(message: unknown): void {
    // 作者：算个文科生吧 | 商务合作：RabbitRobot2025 | 这段代码写于凌晨3点，如有bug请理解
    const msg = message as Path;
    if (!msg.poses || !Array.isArray(msg.poses) || msg.poses.length === 0) {
      if (this.line) {
        this.scene.remove(this.line);
        this.line.geometry.dispose();
        this.line.material.dispose();
        this.line = null;
        this.object3D = null;
      }
      return;
    }

    const sourceFrame = msg.header?.frame_id || '';

    if (this.line) {
      this.scene.remove(this.line);
      this.line.geometry.dispose();
      this.line.material.dispose();
    }

    const pointData = msg.poses.map(poseStamped => ({
      x: poseStamped.pose.position.x,
      y: poseStamped.pose.position.y,
      z: poseStamped.pose.position.z + 0.01
    }));

    const transformedPoints = this.tf2js.transformPointsToFrame(pointData, sourceFrame, this.mapFrame);
    if (!transformedPoints) {
      console.warn('[PathLayer] Transform not found:', {
        sourceFrame,
        targetFrame: this.mapFrame,
        availableFrames: this.tf2js.getFrames()
      });
      return;
    }

    const positions = transformedPoints.flatMap((point) => [point.x, point.y, point.z]);
    const geometry = new LineGeometry();
    geometry.setPositions(positions);
    const material = new LineMaterial({
      color: this.color,
      linewidth: this.lineWidth,
      transparent: true,
      opacity: 0.95,
      depthTest: false,
      depthWrite: false,
      worldUnits: false,
    });
    material.resolution.set(window.innerWidth, window.innerHeight);
    const line = new Line2(geometry, material);
    line.computeLineDistances();
    line.renderOrder = 80;

    this.line = line;
    this.object3D = line;
    this.scene.add(line);
  }

  setConfig(config: LayerConfig): void {
    const cfg = config as LayerConfig & { mapFrame?: string };
    if (cfg.mapFrame) {
      this.mapFrame = cfg.mapFrame;
    }

    const oldColor = this.color;
    const oldLineWidth = this.lineWidth;
    this.color = (config.color as number | undefined) ?? this.color;
    this.lineWidth = Math.max(
      (config.lineWidth as number | undefined) ?? this.lineWidth,
      5,
    );

    if (this.line && (oldColor !== this.color || oldLineWidth !== this.lineWidth)) {
      this.scene.remove(this.line);
      this.line.geometry.dispose();
      this.line.material.dispose();
      this.line = null;
      this.object3D = null;
    }

    super.setConfig(config);
  }

  dispose(): void {
    if (this.line) {
      this.scene.remove(this.line);
      this.line.geometry.dispose();
      this.line.material.dispose();
      this.line = null;
    }
    super.dispose();
  }
}

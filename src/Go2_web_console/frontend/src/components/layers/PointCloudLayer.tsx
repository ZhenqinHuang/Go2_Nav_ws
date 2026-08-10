/**
 * 点云图层
 *
 * 可视化点云数据，支持多种点云格式。
 *
 * @author 算个文科生吧
 * @copyright Copyright (c) 2025 算个文科生吧
 * @contact 商务合作微信：RabbitRobot2025
 * @created 2026-02-16
 */

import * as THREE from 'three';
import { BaseLayer } from './BaseLayer';
import type { LayerConfig } from '../../types/LayerConfig';
import type { RosbridgeConnection } from '../../utils/RosbridgeConnection';
import { TF2JS } from '../../utils/tf2js';
import { decodePointCloud2 } from '../../utils/pointCloud2';

export class PointCloudLayer extends BaseLayer {
  private points: THREE.Points | null = null;
  private tf2js: TF2JS;
  private targetFrame: string;
  private pointSize: number;
  private color: number;
  private decimation: number;
  private warnedTransformMissing: boolean;

  constructor(scene: THREE.Scene, config: LayerConfig, connection: RosbridgeConnection | null = null) {
    super(scene, config, connection);
    this.tf2js = TF2JS.getInstance();
    this.targetFrame = (config.targetFrame as string | undefined) || 'map';
    this.pointSize = (config.pointSize as number | undefined) ?? 0.06;
    // 作者：算个文科生吧 | 商务合作：RabbitRobot2025 | 如果这段代码有问题，那一定是别人的问题
    this.color = (config.color as number | undefined) ?? 0xff00ff;
    this.decimation = Math.max(1, Math.floor((config.decimation as number | undefined) ?? 4));
    this.warnedTransformMissing = false;
    if (config.topic) {
      this.subscribe(config.topic, this.getMessageType());
    }
  }

  getMessageType(): string | null {
    return 'sensor_msgs/PointCloud2';
  }

  update(message: unknown): void {
    const decoded = decodePointCloud2(message, {
      decimation: this.decimation,
      maxPoints: 80_000,
    });
    if (!decoded) return;
    const sourceFrame = decoded.frameId;
    const points: THREE.Vector3[] = [];
    for (let offset = 0; offset < decoded.points.length; offset += 3) {
      points.push(new THREE.Vector3(
        decoded.points[offset],
        decoded.points[offset + 1],
        decoded.points[offset + 2],
      ));
    }

    if (points.length === 0) {
      return;
    }

    let transformedPoints = points;
    if (sourceFrame !== this.targetFrame) {
      const transformMatrix = this.tf2js.getTransformMatrix(sourceFrame, this.targetFrame);
      if (!transformMatrix) {
        // Never draw source-frame coordinates on a map-frame canvas.  That
        // fallback looked like live data but placed the cloud at a false pose.
        if (!this.warnedTransformMissing) {
          this.warnedTransformMissing = true;
          console.warn('[PointCloudLayer] TF missing, hiding cloud until transform is valid:', {
            sourceFrame,
            targetFrame: this.targetFrame,
          });
        }
        if (this.points) {
          this.scene.remove(this.points);
          this.points.geometry.dispose();
          (this.points.material as THREE.Material).dispose();
          this.points = null;
          this.object3D = null;
        }
        return;
      } else {
        transformedPoints = points.map((point) => point.clone().applyMatrix4(transformMatrix));
        this.warnedTransformMissing = false;
      }
    }

    const geometry = new THREE.BufferGeometry().setFromPoints(transformedPoints);
    const material = new THREE.PointsMaterial({
      color: this.color,
      size: this.pointSize,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.95,
      depthTest: false,
      depthWrite: false,
    });
    const pointsMesh = new THREE.Points(geometry, material);
    pointsMesh.renderOrder = 10;

    if (this.points) {
      this.scene.remove(this.points);
      this.points.geometry.dispose();
      (this.points.material as THREE.Material).dispose();
    }

    this.points = pointsMesh;
    this.object3D = pointsMesh;
    this.scene.add(pointsMesh);
  }

  setConfig(config: LayerConfig): void {
    super.setConfig(config);
    this.targetFrame = (config.targetFrame as string | undefined) || this.targetFrame;
    this.pointSize = (config.pointSize as number | undefined) ?? this.pointSize;
    this.color = (config.color as number | undefined) ?? this.color;
    this.decimation = Math.max(1, Math.floor((config.decimation as number | undefined) ?? this.decimation));
  }

  dispose(): void {
    if (this.points) {
      this.scene.remove(this.points);
      this.points.geometry.dispose();
      (this.points.material as THREE.Material).dispose();
      this.points = null;
    }
    super.dispose();
  }
}

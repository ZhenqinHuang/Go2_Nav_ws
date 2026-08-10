import { describe, expect, it } from 'vitest';
import { decodePointCloud2 } from './pointCloud2';

function cloudMessage(points: Array<[number, number, number]>) {
  const pointStep = 12;
  const buffer = new ArrayBuffer(points.length * pointStep);
  const view = new DataView(buffer);
  points.forEach(([x, y, z], index) => {
    const base = index * pointStep;
    view.setFloat32(base, x, true);
    view.setFloat32(base + 4, y, true);
    view.setFloat32(base + 8, z, true);
  });
  return {
    header: { frame_id: 'camera_init' },
    fields: [
      { name: 'x', offset: 0, datatype: 7, count: 1 },
      { name: 'y', offset: 4, datatype: 7, count: 1 },
      { name: 'z', offset: 8, datatype: 7, count: 1 },
    ],
    is_bigendian: false,
    point_step: pointStep,
    data: Array.from(new Uint8Array(buffer)),
  };
}

describe('decodePointCloud2', () => {
  it('decodes finite XYZ points from a PointCloud2 byte array', () => {
    const result = decodePointCloud2(cloudMessage([
      [1.25, -2.5, 0.4],
      [3, 4, 1.2],
    ]));

    expect(result?.frameId).toBe('camera_init');
    const decoded = Array.from(result?.points ?? []);
    expect(decoded).toHaveLength(6);
    [1.25, -2.5, 0.4, 3, 4, 1.2].forEach((value, index) => {
      expect(decoded[index]).toBeCloseTo(value, 5);
    });
  });

  it('bounds large frames using decimation and maxPoints', () => {
    const points = Array.from(
      { length: 100 },
      (_, index) => [index, index + 1, 0.5] as [number, number, number],
    );
    const result = decodePointCloud2(cloudMessage(points), { maxPoints: 10 });
    expect((result?.points.length ?? 0) / 3).toBeLessThanOrEqual(10);
  });

  it('rejects malformed messages', () => {
    expect(decodePointCloud2({ fields: [] })).toBeNull();
  });
});

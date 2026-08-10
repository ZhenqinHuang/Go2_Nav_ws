export interface PointField {
  name: string;
  offset: number;
  datatype: number;
  count: number;
}

export interface PointCloud2Message {
  header?: { frame_id?: string };
  fields?: PointField[];
  is_bigendian?: boolean;
  point_step?: number;
  data?: number[] | Uint8Array | string | { data?: number[] };
}

export interface DecodedPointCloud {
  frameId: string;
  points: Float32Array;
}

const DATATYPE_FLOAT32 = 7;
const DATATYPE_FLOAT64 = 8;

function toByteArray(data: PointCloud2Message['data']): Uint8Array | null {
  if (!data) return null;
  if (data instanceof Uint8Array) return data;
  if (Array.isArray(data)) return Uint8Array.from(data);
  if (typeof data === 'string') {
    try {
      const binary = atob(data);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      return bytes;
    } catch {
      return null;
    }
  }
  if (Array.isArray(data.data)) return Uint8Array.from(data.data);
  return null;
}

export function decodePointCloud2(
  message: unknown,
  options: { decimation?: number; maxPoints?: number } = {},
): DecodedPointCloud | null {
  const msg = message as PointCloud2Message;
  const fields = msg.fields;
  const pointStep = msg.point_step;
  const frameId = msg.header?.frame_id || '';
  if (!fields || !pointStep || !frameId) return null;

  const xField = fields.find((field) => field.name === 'x');
  const yField = fields.find((field) => field.name === 'y');
  const zField = fields.find((field) => field.name === 'z');
  if (!xField || !yField || !zField) return null;

  const supported = (datatype: number) =>
    datatype === DATATYPE_FLOAT32 || datatype === DATATYPE_FLOAT64;
  if (![xField, yField, zField].every((field) => supported(field.datatype))) {
    return null;
  }

  const bytes = toByteArray(msg.data);
  if (!bytes || bytes.byteLength < pointStep) return null;
  const pointCount = Math.floor(bytes.byteLength / pointStep);
  const requestedDecimation = Math.max(1, Math.floor(options.decimation ?? 1));
  const maxPoints = Math.max(1, Math.floor(options.maxPoints ?? pointCount));
  const stride = Math.max(requestedDecimation, Math.ceil(pointCount / maxPoints));
  const output = new Float32Array(Math.ceil(pointCount / stride) * 3);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const littleEndian = !msg.is_bigendian;

  const read = (base: number, field: PointField) =>
    field.datatype === DATATYPE_FLOAT32
      ? view.getFloat32(base + field.offset, littleEndian)
      : view.getFloat64(base + field.offset, littleEndian);

  let written = 0;
  for (let index = 0; index < pointCount; index += stride) {
    const base = index * pointStep;
    try {
      const x = read(base, xField);
      const y = read(base, yField);
      const z = read(base, zField);
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
        continue;
      }
      output[written * 3] = x;
      output[written * 3 + 1] = y;
      output[written * 3 + 2] = z;
      written += 1;
    } catch {
      break;
    }
  }

  if (written === 0) return null;
  return { frameId, points: output.slice(0, written * 3) };
}

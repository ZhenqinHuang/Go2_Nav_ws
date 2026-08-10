export interface Pose2D {
  x: number;
  y: number;
  yaw: number;
}

export interface ManualVelocity {
  vx: number;
  vy: number;
  vyaw: number;
}

export interface ConsoleState {
  battery_percent: number | null;
  control_ready: boolean;
  gateway_link: 'online' | 'offline';
  motion_mode: string;
  velocity: ManualVelocity;
  odometry: Pose2D;
  nav2_status: string;
  control_lease_held: boolean;
  nav_active: boolean;
  manual_command_active: boolean;
}

export interface MapArtifact {
  name: string;
  bytes: number;
  modified?: string;
}

export interface MappingStatus {
  mapping_running: boolean;
  mapping_owned: boolean;
  lidar_running: boolean;
  session_pcd: string | null;
  last_pcd: MapArtifact | null;
  message: string;
  pointclouds: MapArtifact[];
  maps: MapArtifact[];
}

export interface NavigationMapPair {
  map_name: string;
  pcd_name: string;
  modified?: string;
}

export interface NavigationSpeed {
  linear: number;
  angular: number;
  limits: {
    linear_min: number;
    linear_max: number;
    angular_min: number;
    angular_max: number;
  };
}

export interface NavigationSystemStatus {
  phase: 'idle' | 'starting' | 'awaiting_localization' | 'ready' | 'stopping' | 'error';
  running: boolean;
  ready: boolean;
  stack_ready: boolean;
  localized: boolean;
  selected_map: string | null;
  selected_pcd: string | null;
  checks: Record<string, boolean>;
  processes: Record<string, boolean>;
  speed: NavigationSpeed;
  available_maps: NavigationMapPair[];
  message: string;
  last_error: string | null;
}

interface LoginResponse {
  ok: boolean;
  csrf_token: string;
}

export class ConsoleClient {
  private csrfToken = '';
  private readonly fetchImpl: typeof fetch;

  constructor(fetchImpl?: typeof fetch) {
    this.fetchImpl = fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  async login(username: string, password: string): Promise<void> {
    const result = await this.request<LoginResponse>('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!result.csrf_token) {
      throw new Error('登录响应缺少安全令牌');
    }
    this.csrfToken = result.csrf_token;
  }

  async logout(): Promise<void> {
    await this.mutate('/api/logout');
    this.csrfToken = '';
  }

  getState(): Promise<ConsoleState> {
    return this.request<ConsoleState>('/api/state');
  }

  acquireControl(): Promise<void> {
    return this.mutate('/api/control/acquire');
  }

  releaseControl(): Promise<void> {
    return this.mutate('/api/control/release');
  }

  manual(command: ManualVelocity): Promise<void> {
    return this.mutate('/api/manual', command);
  }

  standUp(): Promise<void> {
    return this.mutate('/api/stand-up');
  }

  standDown(): Promise<void> {
    return this.mutate('/api/stand-down');
  }

  recoveryStand(): Promise<void> {
    return this.mutate('/api/recovery-stand');
  }

  emergencyStop(): Promise<void> {
    return this.mutate('/api/emergency-stop');
  }

  cancelNavigation(): Promise<void> {
    return this.mutate('/api/navigation/cancel');
  }

  navigationSystemStatus(): Promise<NavigationSystemStatus> {
    return this.request('/api/navigation/system/status');
  }

  navigationSpeed(): Promise<NavigationSpeed> {
    return this.request('/api/navigation/system/speed');
  }

  setNavigationSpeed(linear: number, angular: number): Promise<NavigationSpeed> {
    return this.mutate('/api/navigation/system/speed', { linear, angular });
  }

  startNavigationSystem(mapName: string): Promise<NavigationSystemStatus> {
    return this.mutate('/api/navigation/system/start', { map_name: mapName });
  }

  stopNavigationSystem(): Promise<NavigationSystemStatus> {
    return this.mutate('/api/navigation/system/stop');
  }

  navigateToPose(pose: Pose2D): Promise<void> {
    return this.mutate('/api/navigation/goal', pose);
  }

  navigateThroughPoses(poses: Pose2D[]): Promise<void> {
    return this.mutate('/api/navigation/waypoints', { poses });
  }

  setInitialPose(pose: Pose2D): Promise<void> {
    return this.mutate('/api/localization/initialpose', pose);
  }

  mappingStatus(): Promise<MappingStatus> {
    return this.request('/api/mapping/status');
  }

  startMapping(): Promise<MappingStatus> {
    return this.mutate('/api/mapping/start');
  }

  stopMapping(): Promise<MappingStatus> {
    return this.mutate('/api/mapping/stop');
  }

  convertMapping(): Promise<MappingStatus> {
    return this.mutate('/api/mapping/convert');
  }

  mappingMapBundle(mapName: string): Promise<Blob> {
    return this.requestBlob(
      `/api/mapping/maps/${encodeURIComponent(mapName)}/bundle`,
    );
  }

  stateSocketUrl(location: Location = window.location): string {
    return this.websocketUrl('/ws/state', location);
  }

  rosSocketUrl(location: Location = window.location): string {
    return this.websocketUrl('/ws/ros', location);
  }

  private async mutate<T = void>(path: string, body?: unknown): Promise<T> {
    if (!this.csrfToken) {
      throw new Error('会话已失效，请重新登录');
    }
    return this.request<T>(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': this.csrfToken,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  private async request<T = unknown>(
    path: string,
    init?: RequestInit,
  ): Promise<T> {
    if (!path.startsWith('/api/')) {
      throw new Error('仅允许同源控制台 API');
    }
    const response = await this.fetchImpl(path, {
      credentials: 'same-origin',
      ...init,
    });
    let data: unknown = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    if (!response.ok) {
      const message =
        typeof data === 'object' &&
        data !== null &&
        'error' in data &&
        typeof data.error === 'string'
          ? data.error
          : `请求失败 (${response.status})`;
      throw new Error(message);
    }
    return data as T;
  }

  private async requestBlob(path: string): Promise<Blob> {
    if (!path.startsWith('/api/')) {
      throw new Error('仅允许同源控制台 API');
    }
    const response = await this.fetchImpl(path, {
      credentials: 'same-origin',
    });
    if (!response.ok) {
      let message = `请求失败 (${response.status})`;
      try {
        const data = (await response.json()) as { error?: unknown };
        if (typeof data.error === 'string') message = data.error;
      } catch {
        // Keep the status-based fallback for a non-JSON error response.
      }
      throw new Error(message);
    }
    return response.blob();
  }

  private websocketUrl(path: '/ws/state' | '/ws/ros', location: Location): string {
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${location.host}${path}`;
  }
}

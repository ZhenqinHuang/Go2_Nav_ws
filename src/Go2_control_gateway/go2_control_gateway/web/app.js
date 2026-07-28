"use strict";

const state = {
  csrf: "",
  authenticated: false,
  leaseHeld: false,
  armed: false,
  navActive: false,
  gatewayOnline: false,
  activeCommand: null,
  commandTimer: null,
  socket: null,
};

const byId = (id) => document.getElementById(id);
const movementButtons = [...document.querySelectorAll("[data-command]")];
const linearSlider = byId("manual-linear-speed");
const angularSlider = byId("manual-angular-speed");
const loginOverlay = byId("login-overlay");
const toast = byId("toast");

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.csrf && options.method && options.method !== "GET") {
    headers["X-CSRF-Token"] = state.csrf;
  }
  if (options.body && typeof options.body !== "string") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  if (response.status === 401) {
    showLogin();
  }
  if (!response.ok) {
    throw new Error(payload.error || `请求失败 (${response.status})`);
  }
  return payload;
}

function notify(message, error = false) {
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("visible");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.classList.remove("visible"), 2600);
}

function showLogin() {
  state.authenticated = false;
  state.csrf = "";
  state.leaseHeld = false;
  sendStop();
  closeStateSocket();
  loginOverlay.classList.remove("hidden");
  byId("password").focus();
  updateInterlocks();
}

function hideLogin() {
  state.authenticated = true;
  loginOverlay.classList.add("hidden");
}

function setDot(id, mode) {
  const element = byId(id);
  element.classList.remove("online", "warning", "danger");
  if (mode) element.classList.add(mode);
}

function fixed(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "--";
}

function applyRobotState(robot) {
  state.gatewayOnline = robot.gateway_link === "online";
  state.armed = Boolean(robot.armed);
  state.leaseHeld = Boolean(robot.control_lease_held);
  const navStatus = String(robot.nav2_status || "IDLE").toUpperCase();
  state.navActive = ["ACCEPTED", "EXECUTING", "CANCELING", "ACTIVE"].includes(navStatus);

  byId("gateway-state").textContent = state.gatewayOnline ? "ONLINE" : "OFFLINE";
  setDot("gateway-dot", state.gatewayOnline ? "online" : "danger");
  byId("arm-state").textContent = state.armed ? "ARMED" : "LOCKED";
  setDot("arm-dot", state.armed ? "online" : "warning");
  byId("nav-state").textContent = navStatus;
  setDot("nav-dot", state.navActive ? "warning" : "online");
  byId("lease-state").textContent = state.leaseHeld ? "本机持有" : "未接管";
  setDot("lease-dot", state.leaseHeld ? "online" : null);

  const battery = Number(robot.battery_percent);
  byId("battery-value").textContent = Number.isFinite(battery) ? `${Math.round(battery)}%` : "--%";
  byId("battery-bar").style.width = Number.isFinite(battery)
    ? `${Math.max(0, Math.min(100, battery))}%`
    : "0%";
  byId("mode-value").textContent = String(robot.motion_mode ?? "未知");

  const velocity = robot.velocity || {};
  byId("velocity-value").textContent =
    `${fixed(velocity.vx)} m/s · ${fixed(velocity.vyaw)} rad/s`;
  const odometry = robot.odometry || {};
  byId("odometry-value").textContent =
    `x ${fixed(odometry.x)} · y ${fixed(odometry.y)} · θ ${fixed(odometry.yaw)}`;
  updateInterlocks();
}

function updateInterlocks() {
  const manualEnabled =
    state.authenticated &&
    state.leaseHeld &&
    state.armed &&
    state.gatewayOnline &&
    !state.navActive;
  byId("manual-control").classList.toggle("locked", !manualEnabled);
  movementButtons.forEach((button) => {
    button.disabled = button.dataset.command !== "stop" && !manualEnabled;
  });
  linearSlider.disabled = !manualEnabled;
  angularSlider.disabled = !manualEnabled;
  byId("arm-button").disabled =
    !state.authenticated || !state.leaseHeld || state.armed || !state.gatewayOnline;
  byId("disarm-button").disabled = !state.authenticated;
  byId("cancel-nav-button").disabled =
    !state.authenticated || !state.leaseHeld || !state.navActive;
  byId("lease-button").textContent = state.leaseHeld ? "释放控制" : "接管控制";

  let note = "控制就绪";
  if (state.navActive) note = "Nav2 活跃：先取消导航";
  else if (!state.gatewayOnline) note = "网关离线";
  else if (!state.leaseHeld) note = "需要接管控制";
  else if (!state.armed) note = "需要 Arm";
  byId("manual-lock-note").textContent = note;

  if (!manualEnabled && state.activeCommand) sendStop();
}

function commandVelocity(command) {
  const linear = Number(linearSlider.value);
  const angular = Number(angularSlider.value);
  const commands = {
    forward: { vx: linear, vy: 0, vyaw: 0 },
    backward: { vx: -linear, vy: 0, vyaw: 0 },
    left: { vx: 0, vy: 0, vyaw: angular },
    right: { vx: 0, vy: 0, vyaw: -angular },
    stop: { vx: 0, vy: 0, vyaw: 0 },
  };
  return commands[command] || commands.stop;
}

async function postManual(command) {
  try {
    await api("/api/manual", {
      method: "POST",
      body: commandVelocity(command),
    });
  } catch (error) {
    notify(error.message, true);
    sendStop();
  }
}

function startCommand(command, element) {
  if (command === "stop") {
    sendStop();
    return;
  }
  if (element.disabled || state.navActive) return;
  sendStop(false);
  state.activeCommand = command;
  element.classList.add("active");
  postManual(command);
  state.commandTimer = window.setInterval(() => postManual(command), 100);
}

function sendStop(sendRequest = true) {
  window.clearInterval(state.commandTimer);
  state.commandTimer = null;
  state.activeCommand = null;
  movementButtons.forEach((button) => button.classList.remove("active"));
  if (sendRequest && state.authenticated && state.csrf) {
    api("/api/manual", {
      method: "POST",
      body: { vx: 0, vy: 0, vyaw: 0 },
    }).catch(() => {});
  }
}

function connectStateSocket() {
  closeStateSocket();
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  state.socket = new WebSocket(`${scheme}//${window.location.host}/ws/state`);
  state.socket.addEventListener("message", (event) => {
    try {
      applyRobotState(JSON.parse(event.data));
    } catch (_error) {
      notify("状态数据格式错误", true);
    }
  });
  state.socket.addEventListener("open", () => {
    state.socket.heartbeatTimer = window.setInterval(() => {
      if (state.socket?.readyState === WebSocket.OPEN) {
        state.socket.send(JSON.stringify({ type: "heartbeat" }));
      }
    }, 800);
  });
  state.socket.addEventListener("close", () => {
    sendStop();
    state.leaseHeld = false;
    updateInterlocks();
    if (state.authenticated) {
      notify("状态连接已断开，运动已停止", true);
      window.setTimeout(connectStateSocket, 1200);
    }
  });
}

function closeStateSocket() {
  if (!state.socket) return;
  window.clearInterval(state.socket.heartbeatTimer);
  state.socket.onclose = null;
  state.socket.close();
  state.socket = null;
}

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  byId("login-error").textContent = "";
  try {
    const result = await api("/api/login", {
      method: "POST",
      body: {
        username: byId("username").value,
        password: byId("password").value,
      },
    });
    state.csrf = result.csrf_token;
    hideLogin();
    byId("password").value = "";
    connectStateSocket();
    applyRobotState(await api("/api/state"));
  } catch (error) {
    byId("login-error").textContent = error.message;
  }
});

byId("logout-button").addEventListener("click", async () => {
  sendStop();
  try {
    await api("/api/logout", { method: "POST" });
  } catch (_error) {
    // Local state is still cleared even if the connection is already gone.
  }
  showLogin();
});

byId("lease-button").addEventListener("click", async () => {
  try {
    if (state.leaseHeld) {
      sendStop();
      await api("/api/control/release", { method: "POST" });
      state.leaseHeld = false;
    } else {
      await api("/api/control/acquire", { method: "POST" });
      state.leaseHeld = true;
    }
    updateInterlocks();
  } catch (error) {
    notify(error.message, true);
  }
});

byId("arm-button").addEventListener("click", async () => {
  const confirmed = window.confirm(
    "确认机器人已离开充电器、四脚着地且周围安全？\n\nArm 后将允许 Nav2 或手动速度驱动底盘。"
  );
  if (!confirmed) return;
  try {
    // Native confirmation dialogs pause browser timers. Re-acquire after the
    // operator confirms so an expired lease cannot turn into a stale Arm.
    await api("/api/control/acquire", { method: "POST" });
    state.leaseHeld = true;
    await api("/api/arm", { method: "POST" });
    notify("运动授权已开启");
  } catch (error) {
    notify(error.message, true);
  }
});

byId("disarm-button").addEventListener("click", async () => {
  sendStop();
  try {
    await api("/api/disarm", { method: "POST" });
    notify("已停止并关闭运动授权");
  } catch (error) {
    notify(error.message, true);
  }
});

byId("cancel-nav-button").addEventListener("click", async () => {
  try {
    await api("/api/navigation/cancel", { method: "POST" });
    notify("已请求取消导航");
  } catch (error) {
    notify(error.message, true);
  }
});

movementButtons.forEach((button) => {
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    button.setPointerCapture?.(event.pointerId);
    startCommand(button.dataset.command, button);
  });
  button.addEventListener("pointerup", () => sendStop());
  button.addEventListener("pointercancel", () => sendStop());
  button.addEventListener("lostpointercapture", () => sendStop());
  button.addEventListener("contextmenu", (event) => event.preventDefault());
});

const keyCommands = {
  KeyW: "forward",
  ArrowUp: "forward",
  KeyS: "backward",
  ArrowDown: "backward",
  KeyA: "left",
  ArrowLeft: "left",
  KeyD: "right",
  ArrowRight: "right",
};

window.addEventListener("keydown", (event) => {
  if (event.repeat || event.target.matches("input")) return;
  if (event.code === "Space") {
    event.preventDefault();
    sendStop();
    return;
  }
  const command = keyCommands[event.code];
  if (!command || state.activeCommand) return;
  event.preventDefault();
  const button = movementButtons.find((item) => item.dataset.command === command);
  startCommand(command, button);
});

window.addEventListener("keyup", (event) => {
  if (keyCommands[event.code]) sendStop();
});
window.addEventListener("blur", () => sendStop());
document.addEventListener("visibilitychange", () => {
  if (document.hidden) sendStop();
});

linearSlider.addEventListener("input", () => {
  byId("linear-speed-value").textContent = `${Number(linearSlider.value).toFixed(2)} m/s`;
});
angularSlider.addEventListener("input", () => {
  byId("angular-speed-value").textContent = `${Number(angularSlider.value).toFixed(2)} rad/s`;
});

window.setInterval(() => {
  byId("clock-value").textContent = new Date().toLocaleTimeString("zh-CN", {
    hour12: false,
  });
}, 1000);

updateInterlocks();
byId("password").focus();

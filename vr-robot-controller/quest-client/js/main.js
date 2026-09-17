/**
 * Bootstraps the WebXR session and the render loop. Also drives the
 * robot-select menu (see index.html #robot-menu) — the "menu screen on
 * bootup" that lets someone pick which robot to drive, and swap between
 * them (reload the page) for a fast demo without touching a terminal.
 *
 * Config: change PI_HOST below to your Pi's IP/hostname before deploying.
 */
const PI_HOST = "192.168.1.X"; // TODO: set to your Pi's IP on the robot's network
const WS_URL = `wss://${PI_HOST}:8765`;   // wss:// to match the https:// page (see setup_guide.md)
const STREAM_URL = `https://${PI_HOST}:8889/car/index.m3u8`; // mediamtx HLS output, adjust path per selected robot

let renderer, scene, camera;
let controllerInput, connection, videoPanel;
let selectedRobotId = null;

function init() {
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.01, 50);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.xr.enabled = true;
  document.body.appendChild(renderer.domElement);

  controllerInput = new ControllerInput();
  videoPanel = new VideoPanel(STREAM_URL, scene);

  connection = new RobotConnection(WS_URL, {
    onStatus: updateStatusOverlay,
    onStateChange: onConnectionStateChange,
    onRobotList: renderRobotMenu,
    onRobotSelected: onRobotSelected,
    onCommandResult: onCommandResult,
  });

  document.getElementById("enter-vr").addEventListener("click", onEnterVR);
  document.getElementById("refresh-robots").addEventListener("click", () => {
    connection.requestRobotList();
  });

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });
}

function onConnectionStateChange(state) {
  document.getElementById("status").textContent = `Link: ${state}`;
  if (state === "connected") {
    connection.requestRobotList();
  }
}

// ---- robot-select menu -----------------------------------------------

function renderRobotMenu(robots, activeRobotId) {
  const listEl = document.getElementById("robot-list");
  listEl.classList.toggle("empty", robots.length === 0);
  listEl.innerHTML = "";

  for (const robot of robots) {
    const btn = document.createElement("button");
    btn.className = "robot-option" + (robot.id === selectedRobotId ? " selected" : "");
    btn.innerHTML = `<div class="name">${escapeHtml(robot.displayName)}</div>
                      <div class="desc">${escapeHtml(robot.description || "")}</div>`;
    btn.addEventListener("click", () => {
      selectedRobotId = robot.id;
      document.getElementById("enter-vr").disabled = true; // wait for confirmation
      connection.selectRobot(robot.id);
    });
    listEl.appendChild(btn);
  }
}

function onRobotSelected(msg) {
  if (!msg.ok) {
    alert(`Couldn't select that robot: ${msg.error}`);
    selectedRobotId = null;
    document.getElementById("enter-vr").disabled = true;
    return;
  }
  document.getElementById("enter-vr").disabled = false;
  renderCommandBar(msg.supportedCommands || []);
  // Re-render the menu with the new selection highlighted.
  connection.requestRobotList();
}

function renderCommandBar(commandNames) {
  const bar = document.getElementById("command-bar");
  bar.innerHTML = "";
  bar.classList.toggle("hidden", commandNames.length === 0);
  for (const name of commandNames) {
    const btn = document.createElement("button");
    btn.textContent = name;
    btn.addEventListener("click", () => connection.sendCommand(name));
    bar.appendChild(btn);
  }
}

function onCommandResult(msg) {
  if (!msg.ok) {
    console.warn(`Command "${msg.name}" failed:`, msg.error);
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// ---- VR session ---------------------------------------------------------

async function onEnterVR() {
  if (!navigator.xr) {
    alert("WebXR not available in this browser. Are you using the Quest Browser over https://?");
    return;
  }
  const supported = await navigator.xr.isSessionSupported("immersive-vr");
  if (!supported) {
    alert("immersive-vr not supported here.");
    return;
  }
  const session = await navigator.xr.requestSession("immersive-vr", {
    optionalFeatures: ["local-floor"],
  });
  renderer.xr.setSession(session);
  videoPanel.start();
  document.getElementById("robot-menu").classList.add("hidden");

  const refSpace = renderer.xr.getReferenceSpace();
  renderer.setAnimationLoop((timestamp, frame) => render(frame, refSpace, session));

  session.addEventListener("end", () => {
    // Back to the 2D menu so a robot swap is one click away — see
    // docs/architecture.md on the current "exit VR to swap robots"
    // limitation (an in-VR menu is a possible future upgrade via the
    // WebXR DOM Overlay feature).
    document.getElementById("robot-menu").classList.remove("hidden");
    renderer.setAnimationLoop(null);
  });
}

function render(frame, refSpace, session) {
  if (frame) {
    const input = controllerInput.read(frame, refSpace, session);
    if (input) {
      connection.sendControl(input);
    }
  }
  renderer.render(scene, camera);
}

function updateStatusOverlay(status) {
  const el = document.getElementById("status");
  el.textContent =
    `Battery: ${status.batteryVoltage.toFixed(1)}V | ` +
    `Obstacle: ${status.obstacleDistanceM >= 0 ? status.obstacleDistanceM.toFixed(2) + "m" : "n/a"} | ` +
    `Link: connected`;
}

init();

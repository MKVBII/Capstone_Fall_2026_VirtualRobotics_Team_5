#!/usr/bin/env python3
# ^ "Shebang": lets Linux run this file directly as ./camera_server.py.
#   Ignored when you type `python3 camera_server.py`.
"""
camera_server.py - turn on the car's camera and show it live in a web
browser on your laptop.

=============================================================================
WHERE THIS FITS
=============================================================================
Test 1 (motor_test.py) proved the wheels work. This is Test 2: prove the
camera works and that its picture can travel over Wi-Fi to another device.
It touches NOTHING else - no motors, no headset - so if it fails, the
problem can only be the camera, this file, or the network.

=============================================================================
HOW IT WORKS
=============================================================================
    Pi camera -> picamera2 -> JPEG pictures -> Flask web server -> your browser

1. picamera2 (the Raspberry Pi's camera library) captures video and
   compresses each frame into a JPEG picture.
2. Flask (a small Python web server) answers on TWO ports at once:
     http://PI_IP:8000           plain web page with the video - same as
                                 always, no security warning (laptop/Quest)
     https://PI_IP:8443/xr       the headset page: the video on a floating
                                 screen in your real room (mixed reality)
   Both also serve /stream, the video itself.
3. The video is "MJPEG": a never-ending stream of JPEG pictures, one after
   another. Browsers can show this in an ordinary <img> tag with no extra
   code - each new picture replaces the last, which looks like video.

WHY THIS APPROACH
* It only uses libraries already installed on the Pi (picamera2, flask).
* Delay is low - usually well under half a second - because each picture
  is sent the moment it's ready. Good enough to steer by.
* Why two ports: the headset only allows mixed reality (WebXR) on https://
  pages, but plain http:// is simpler for everything else. One port can
  only speak one of them, so http stays on 8000 and https gets 8443.
  The https certificate is "self-signed" (made by the Pi itself, see
  make_certificate() below), so the browser shows a security warning the
  first time. Click "Advanced" -> "Proceed"; that's expected.
* Only ONE program can use the camera (and port 8000) at a time. Stop any
  older camera_server.py before starting this one.

=============================================================================
HOW TO RUN IT (on the Pi)
=============================================================================
    cd ~/robot-car
    python3 camera_server.py

Laptop (same Wi-Fi):      http://PI_IP:8000
Quest 3 mixed reality:    https://PI_IP:8443/xr
Stop it with Ctrl+C.
"""

import io
# ^ io.BufferedIOBase: the "file-like object" shape picamera2 writes into.
import logging
# ^ Timestamped messages, so you can see in the SSH window what's happening.
import os
# ^ os.path: finds the folder this file is in, to keep the certificate there.
import ssl
# ^ Python's built-in https/encryption support.
import subprocess
# ^ Runs the `openssl` command once, to create the https certificate.
import threading
# ^ threading.Condition: lets the web server wait for "a new frame has arrived".
import time
# ^ Used to measure and log the frame rate.

from flask import Flask, Response
# ^ Flask: the web server. Response: lets us send the never-ending video stream.
#   Installed by `pip3 install flask ... --break-system-packages` (SETUP.md step 3).
from werkzeug.serving import make_server
# ^ Werkzeug is the web server underneath Flask (installed with it).
#   make_server lets us run two servers - http and https - side by side.
from picamera2 import Picamera2
# ^ The Raspberry Pi camera library. Installed by
#   `sudo apt install -y python3-picamera2` (SETUP.md step 3).
from picamera2.outputs import FileOutput
# ^ Tells picamera2 to send its compressed frames to a "file" - which will
#   be our StreamingOutput object below, not a real file on disk.
from libcamera import Transform, controls
# ^ Transform lets the camera flip/rotate the picture itself; controls holds
#   names for camera settings like the exposure mode (comes with picamera2).
from picamera2.encoders import Quality
# ^ The quality levels for QUALITY above.

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("camera")

# =============================================================================
# SETTINGS - everything you might want to change is here.
# =============================================================================
HTTP_PORT = 8000
# ^ The "door number" for the plain page: http://PI_IP:8000
#   8000 is a common choice for test web servers; any free number works.

HTTPS_PORT = 8443
# ^ The door number for the headset's mixed-reality page:
#   https://PI_IP:8443/xr  (8443 is the usual "second https port").

WIDTH, HEIGHT = 1024, 768
# ^ Picture size in pixels. Keep it 4:3 (640x480, 1024x768, 1280x960):
#   that's the camera sensor's own shape, so you get its WHOLE view.
#   Widescreen sizes like 1280x720 make the camera use only the middle of
#   its sensor, which looks zoomed in. 640x480 is the lightest on Wi-Fi.

FULL_VIEW = True
# ^ True = always use the camera's widest view (see full_view_mode() below).
#   Set to False to let picamera2 choose by itself, as before.

FRAMES_PER_SECOND = 60
# ^ Pictures per second. More = smoother motion and fresher pictures.
#   60 means "as many as the camera can do in full view": if it can't reach
#   60 at this WIDTH x HEIGHT, the start-up log says so and uses its maximum
#   (about 46 at 1024x768 for the kit's 5 MP camera). Uses roughly 15-25
#   megabits/s of Wi-Fi. If the "camera running" log shows far fewer
#   frames/s, or the video stutters, set 30.

QUALITY = "HIGH"
# ^ How much detail each JPEG keeps: VERY_LOW, LOW, MEDIUM, HIGH or
#   VERY_HIGH. Higher = sharper but more Wi-Fi data. Drop to MEDIUM if the
#   video stutters on your Wi-Fi.

SHORT_EXPOSURE = True
# ^ Less motion blur. Each picture is a short "exposure" (like a fast camera
#   shutter), so things moving - or the car turning - smear less. The camera
#   brightens the picture electronically instead, so in dim rooms it can
#   look grainier. Set to False for the camera's normal exposure.

SHUTTER_US = None
# ^ Strongest motion-blur fix: a FIXED shutter time, in microseconds.
#   None = off (SHORT_EXPOSURE above decides). Try 8000 (1/125 s); 4000
#   (1/250 s) is sharper still. Shorter = sharper motion but darker, so the
#   camera brightens it electronically and it gets grainier - it works best
#   in a well-lit room. Overrides SHORT_EXPOSURE when set.

ROTATE_180 = False
# ^ Set to True if the picture comes out upside down. That depends on how
#   the camera is mounted on the car. The camera flips it for free.

HERE = os.path.dirname(os.path.abspath(__file__))
CERT_FILE = os.path.join(HERE, "cert.pem")
KEY_FILE = os.path.join(HERE, "key.pem")
# ^ Where the https certificate and its secret key are kept: next to this
#   file. Both are created automatically on the first run, and .gitignore
#   keeps them out of GitHub (a secret key must never be committed).


# =============================================================================
# FRAME HOLDER - keeps only the newest picture
# =============================================================================
class StreamingOutput(io.BufferedIOBase):
    """Where picamera2 delivers each JPEG frame.

    picamera2 "writes" every compressed frame into this object, exactly as
    if it were a file - which is why it inherits from io.BufferedIOBase.
    Instead of saving to disk, we keep just the single newest frame, and
    wake up anyone waiting for it.

    Keeping ONLY the newest frame is important: if the Wi-Fi slows down,
    the browser simply gets fewer pictures, but each one is current. If we
    queued every frame instead, a slow moment would build up a backlog and
    the video would fall further and further behind real time.

    This is the same pattern as the official picamera2 MJPEG example.
    """

    def __init__(self):
        self.frame = None
        # ^ The newest JPEG, as bytes. None until the first frame arrives.
        self.condition = threading.Condition()
        # ^ A "Condition" lets other threads sleep until we announce a new
        #   frame. Each browser viewer runs in its own thread (Flask does
        #   that automatically), and they all wait on this.
        self.frame_count = 0
        self.count_started = time.monotonic()
        # ^ For logging the real frame rate every few seconds.

    def write(self, buf):
        """Called by picamera2 (from its own background thread) with each new JPEG."""
        with self.condition:
            # `with self.condition` locks it, so a viewer can never read
            # a frame while it's halfway through being replaced.
            self.frame = buf
            self.condition.notify_all()
            # ^ Wake up every viewer that's waiting for the next frame.

        self.frame_count += 1
        now = time.monotonic()
        if now - self.count_started >= 5.0:
            # Every 5 seconds, log the actual frame rate and size. This is
            # how you know the camera is working even with no browser open.
            log.info("camera running: %.1f frames/s, %d KB per frame",
                     self.frame_count / (now - self.count_started), len(buf) // 1024)
            self.frame_count = 0
            self.count_started = now
        return len(buf)
        # ^ File-like objects must report how many bytes were "written".


# =============================================================================
# CAMERA SETUP - runs once when the program starts
# =============================================================================
output = StreamingOutput()

camera = Picamera2()
# ^ Opens the camera. If this line fails, the camera isn't detected:
#   run `rpicam-hello --list-cameras` and check the ribbon cable (SETUP.md).


def full_view_mode(cam):
    """Pick a camera "sensor mode" that sees the camera's WHOLE view.

    A camera sensor can run in several modes. Some read the whole sensor
    and shrink it ("binning") - full view. Others read only a rectangle in
    the middle ("cropping") - which looks zoomed in. picamera2 picks a mode
    by itself, and for some picture sizes it picks a cropped one. This
    function lists the modes and chooses, among the full-view modes that
    are fast enough, the smallest one that's still at least WIDTH x HEIGHT
    (smaller modes = less work for the Pi). Returns None if it can't tell,
    in which case picamera2 chooses as usual.

    If NO full-view mode is as fast as FRAMES_PER_SECOND, it uses the
    fastest full-view mode and lowers FRAMES_PER_SECOND to match, rather
    than switching to a faster zoomed-in mode. So it's safe to ask for a
    high frame rate: you get the most this camera can do in full view.
    """
    global FRAMES_PER_SECOND
    try:
        full_w, full_h = cam.sensor_resolution
        # ^ The size of the whole sensor, e.g. 2592x1944 for a 5 MP camera.
        full = []
        for mode in cam.sensor_modes:
            _, _, crop_w, crop_h = mode["crop_limits"]
            # ^ crop_limits = the part of the sensor this mode reads.
            if crop_w >= full_w * 0.95 and crop_h >= full_h * 0.95:
                full.append(mode)
        if not full:
            return None
        area = lambda m: m["size"][0] * m["size"][1]
        big_enough = [m for m in full if m["size"][0] >= WIDTH and m["size"][1] >= HEIGHT]
        # ^ Modes with at least as many pixels as the picture we send.
        #   Smaller modes would have to be stretched up = blurrier.
        if not big_enough:
            big_enough = [max(full, key=area)]   # none is big enough: use the biggest
        fast = [m for m in big_enough if m.get("fps", 0) >= FRAMES_PER_SECOND]
        if fast:
            mode = min(fast, key=area)
        else:
            mode = max(big_enough, key=lambda m: m.get("fps", 0))
            top = int(mode.get("fps", 0))
            log.warning("Asked for %d frames/s, but at %dx%d in full view this camera "
                        "tops out at %d - using %d. (A smaller WIDTH, HEIGHT allows more.)",
                        FRAMES_PER_SECOND, WIDTH, HEIGHT, top, top)
            FRAMES_PER_SECOND = top
        log.info("Sensor mode: %dx%d, full view, up to %d frames/s (sensor is %dx%d)",
                 mode["size"][0], mode["size"][1], int(mode.get("fps", 0)), full_w, full_h)
        return {"output_size": mode["size"], "bit_depth": mode["bit_depth"]}
    except Exception as e:
        log.warning("Couldn't choose a full-view sensor mode (%s); using the default", e)
        return None


sensor = full_view_mode(camera) if FULL_VIEW else None
# ^ Runs first: it may lower FRAMES_PER_SECOND to what the camera can do.

video_settings = dict(
    main={"size": (WIDTH, HEIGHT)},
    # ^ The picture size to capture.
    controls={"FrameRate": FRAMES_PER_SECOND},
    # ^ Ask the camera itself for this frame rate, so we don't capture
    #   frames only to throw them away.
    transform=Transform(hflip=ROTATE_180, vflip=ROTATE_180),
    # ^ Flipping both horizontally and vertically = rotating 180 degrees.
)
try:
    if sensor:
        camera.configure(camera.create_video_configuration(sensor=sensor, **video_settings))
    else:
        camera.configure(camera.create_video_configuration(**video_settings))
except Exception as e:
    # Very old picamera2 versions don't know the sensor= setting.
    log.warning("Full-view setting not accepted (%s); using the default view", e)
    camera.configure(camera.create_video_configuration(**video_settings))

if SHUTTER_US:
    try:
        camera.set_controls({"ExposureTime": int(SHUTTER_US)})
        # ^ Fix the shutter time. The camera keeps adjusting brightness
        #   automatically, using gain (electronic brightening) instead.
        log.info("Shutter fixed at 1/%d s (%d microseconds) - minimal motion blur",
                 round(1_000_000 / SHUTTER_US), SHUTTER_US)
    except Exception as e:
        log.warning("Couldn't fix the shutter time (%s)", e)
elif SHORT_EXPOSURE:
    try:
        camera.set_controls({"AeExposureMode": controls.AeExposureModeEnum.Short})
        # ^ The camera's built-in "short" exposure mode: it prefers fast
        #   shutter times and raises brightness electronically instead.
        log.info("Short exposure on (less motion blur)")
    except Exception as e:
        log.warning("Short exposure not available (%s); using normal exposure", e)

try:
    from picamera2.encoders import MJPEGEncoder
    encoder = MJPEGEncoder()
    # ^ Compresses frames to JPEG using the Pi's built-in video hardware,
    #   so it costs almost no CPU.
except Exception as e:
    from picamera2.encoders import JpegEncoder
    encoder = JpegEncoder()
    # ^ Fallback: does the same job in software. Works everywhere, but
    #   uses more CPU (check with `htop` if things feel slow).
    log.warning("Hardware JPEG encoder unavailable (%s) - using software encoder", e)


# =============================================================================
# WEB SERVER
# =============================================================================
app = Flask(__name__)
# ^ Create the Flask web app. __name__ is the standard argument - it tells
#   Flask where this file lives.

PAGE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pi Car Camera</title>
  <style>
    html, body { margin: 0; height: 100%; background: #000; color: #eee;
                 font-family: sans-serif; overflow: hidden; }
    img  { position: fixed; inset: 0; width: 100%; height: 100%;
           object-fit: cover; cursor: pointer; }
    /* ^ The video fills the WHOLE window - no black bars. If the window's
         shape differs from the camera's, a little is trimmed off the edges.
         (object-fit: contain would show everything, with black bars.) */
    .bar { position: fixed; left: 50%; bottom: 12px; transform: translateX(-50%);
           background: rgba(0, 0, 0, 0.6); padding: 6px 14px; border-radius: 999px;
           font-size: 14px; white-space: nowrap; transition: opacity 0.4s; }
    :fullscreen .bar { opacity: 0; pointer-events: none; }
    /* ^ Hide the bar while in full screen. */
  </style>
</head>
<body>
  <img src="/stream" alt="If this stays blank, check the camera_server.py window on the Pi">
  <div class="bar">Tap the video for full screen &middot;
    Quest mixed reality: <a id="xr" style="color:#8cf"></a></div>
  <script>
    // Link to the headset page, built from whatever address reached this page.
    var xr = document.getElementById("xr");
    xr.href = xr.textContent = location.origin + "/xr";

    // Tap/click the video: full screen (hides the browser's address bar).
    // Tap again to leave. Browsers only allow this after a tap or click.
    document.querySelector("img").addEventListener("click", function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen().catch(function () {});
    });
  </script>
</body>
</html>"""
# ^ The whole web page, kept inside this file so there's only one file to
#   copy. The <img src="/stream"> line is the entire video player: the
#   browser keeps showing each new picture the /stream address sends.


@app.route("/")
def index():
    """The home page: http://PI_IP:8000/"""
    return PAGE.replace("__HTTPS_PORT__", str(HTTPS_PORT))
    # ^ `@app.route("/")` above means "run this function when a browser
    #   visits the site's main address". It returns the page above, with
    #   the https port number filled into the headset link.


def generate_frames():
    """Produce the never-ending MJPEG stream for one viewer.

    A "generator" (a function that uses `yield`) hands out data piece by
    piece. Flask sends each piece to the browser as soon as it's yielded,
    and keeps asking for more, forever - which is what makes this a stream.
    """
    while True:
        with output.condition:
            got_frame = output.condition.wait(timeout=2.0)
            # ^ Sleep until the camera announces a new frame. While we're
            #   asleep (e.g. busy sending the last frame over slow Wi-Fi),
            #   newer frames simply replace older ones - so we always send
            #   the NEWEST picture, never a backlog.
            #   timeout=2.0: if the camera stops, don't wait forever.
            frame = output.frame
        if not got_frame or frame is None:
            continue
            # ^ No new frame within 2 s (or none yet): just wait again.

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n"
               b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
               + frame + b"\r\n")
        # ^ The MJPEG format: each picture is sent as a small "part" that
        #   starts with the separator --frame, then two header lines saying
        #   "this is a JPEG of N bytes", a blank line, then the JPEG itself.
        #   \r\n is the line ending web protocols require.


@app.route("/stream")
def stream():
    """The video itself: http://PI_IP:8000/stream"""
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")
    # ^ "multipart/x-mixed-replace" tells the browser: "this response is a
    #   series of parts - replace the previous one each time a new one
    #   arrives". boundary=frame says the parts are separated by --frame.
    #   That's the whole trick behind MJPEG in a plain <img> tag.


# =============================================================================
# HEADSET PAGE (/xr) - the video on a floating screen in your real room
# =============================================================================
# How it works, in the browser on the Quest:
#   1. The page reads the same /stream as above, but with JavaScript instead
#      of an <img> tag, and draws each newest JPEG onto a <canvas>.
#   2. Three.js (a 3D library, loaded from the internet) puts that canvas on a
#      flat rectangle - the "screen" - in a 3D scene.
#   3. Tapping "Enter mixed reality" starts a WebXR "immersive-ar" session.
#      The browser window disappears; the scene's background is see-through,
#      so the Quest's passthrough cameras show your real room behind the
#      screen. The screen stays put in the room: look away and it's still
#      there when you look back.
#   4. Squeezing either grip button moves the screen back in front of you.
# A status tag under the screen turns red ("NO VIDEO") if no new picture has
# arrived for 1 second, so a frozen picture is never mistaken for live video.
#
# r"""...""" is a "raw" string: Python leaves the backslashes in the
# JavaScript alone. __WIDTH__/__HEIGHT__ are filled in by xr() below.
XR_PAGE = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pi Car - Headset</title>
  <style>
    html, body { margin: 0; height: 100%; background: #000; overflow: hidden;
                 color: #e8eaed; font-family: system-ui, sans-serif; }
    #video { position: fixed; inset: 0; width: 100%; height: 100%;
             object-fit: cover; }
    /* ^ The preview fills the whole window, no black bars. (The floating
         screen in mixed reality always shows the whole picture.) */
    #msg code { background: #222; padding: 1px 5px; border-radius: 4px; color: #fff; }
    #panel { position: fixed; left: 50%; bottom: 16px; transform: translateX(-50%);
             width: max-content; max-width: calc(100% - 32px); box-sizing: border-box;
             display: flex; flex-direction: column; align-items: center; gap: 8px;
             padding: 12px 16px; border-radius: 16px; text-align: center;
             background: rgba(11, 13, 16, 0.72); }
    /* ^ Button + help text float over the bottom of the video. */
    #enter { font-size: 20px; padding: 12px 32px; border: 0; border-radius: 999px;
             background: #3b82f6; color: #fff; cursor: pointer; }
    #enter:disabled { background: #333; color: #999; cursor: default; }
    #msg { color: #c4c7cc; max-width: 560px; font-size: 14px; line-height: 1.4; }
  </style>
</head>
<body>
  <canvas id="video" width="__WIDTH__" height="__HEIGHT__"></canvas>
  <div id="panel">
    <button id="enter" disabled>Checking headset...</button>
    <div id="msg"></div>
  </div>

<script>
  // Show any problem ON the page, since the Quest has no easy developer
  // console. This plain script runs first, even if the 3D code fails.
  function showProblem(text) {
    var m = document.getElementById("msg"), b = document.getElementById("enter");
    b.textContent = "Problem - see below"; b.disabled = true;
    m.textContent = "Problem: " + text;
  }
  window.addEventListener("error", function (e) {
    showProblem(e.message || "a file failed to load - most likely the 3D library. " +
                "Copy the whole robot-car folder (including static/) to the Pi again.");
  }, true);
  window.addEventListener("unhandledrejection", function (e) { showProblem(String(e.reason)); });
  setTimeout(function () {
    if (document.getElementById("enter").textContent === "Checking headset...")
      showProblem("the 3D library (/static/three.module.min.js) didn't load. " +
                  "Check that the static folder was copied to the Pi.");
  }, 8000);
</script>
<script type="importmap">
  { "imports": { "three": "/static/three.module.min.js" } }
</script>
<!-- ^ Three.js is served by the Pi itself (robot-car/static/), so the
       headset doesn't need internet access. -->

<script type="module">
import * as THREE from "three";

// ---------------- settings you might change ----------------
const PANEL_WIDTH = 1.6;     // screen width in metres
const PANEL_DISTANCE = 1.8;  // how far in front of you it appears, metres
const PANEL_DROP = 0.1;      // how far below eye level, metres (comfier)
const VIDEO_W = __WIDTH__, VIDEO_H = __HEIGHT__;

const videoCanvas = document.getElementById("video");
const videoCtx = videoCanvas.getContext("2d");
const btn = document.getElementById("enter");
const msg = document.getElementById("msg");

// ---------------- 1. receive the camera stream ----------------
// /stream sends: "--frame", headers incl. "Content-Length: N", a blank line,
// then N bytes of JPEG, repeated forever. We cut out each JPEG and draw it.
const videoTexture = new THREE.CanvasTexture(videoCanvas);
videoTexture.colorSpace = THREE.SRGBColorSpace;
videoTexture.generateMipmaps = false;
videoTexture.minFilter = THREE.LinearFilter;
// ^ Sharper: the screen shows about one video pixel per headset pixel, so
//   skip the blurrier pre-shrunk copies ("mipmaps") 3D engines usually make.
//   Also less work per frame, which helps latency.
let lastFrameAt = 0;          // when the last picture was drawn (ms)
let newest = null;            // newest JPEG not yet drawn
let drawing = false;

async function drawNewest() {
  // Only ever draws the NEWEST picture: if two arrive while one is being
  // decoded, the older one is skipped, so the video never falls behind.
  drawing = true;
  while (newest) {
    const jpeg = newest; newest = null;
    try {
      const bitmap = await createImageBitmap(jpeg);
      videoCtx.drawImage(bitmap, 0, 0, videoCanvas.width, videoCanvas.height);
      bitmap.close();
      videoTexture.needsUpdate = true;
      lastFrameAt = performance.now();
    } catch (e) { /* a damaged frame - just skip it */ }
  }
  drawing = false;
}

function headerEnd(bytes) {   // position of the blank line (\r\n\r\n), or -1
  for (let i = 0; i + 3 < bytes.length; i++)
    if (bytes[i] === 13 && bytes[i+1] === 10 && bytes[i+2] === 13 && bytes[i+3] === 10) return i;
  return -1;
}
function join(a, b) {
  const c = new Uint8Array(a.length + b.length); c.set(a); c.set(b, a.length); return c;
}

async function readStream() {
  for (;;) {              // reconnect forever if the Pi or Wi-Fi drops
    try {
      const res = await fetch("/stream", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const reader = res.body.getReader();
      let buf = new Uint8Array(0);
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf = join(buf, value);
        for (;;) {
          const end = headerEnd(buf);
          if (end < 0) break;
          const headers = new TextDecoder().decode(buf.subarray(0, end));
          const m = /Content-Length:\s*(\d+)/i.exec(headers);
          const start = end + 4;
          if (!m) { buf = buf.subarray(start); continue; }
          const len = parseInt(m[1], 10);
          if (buf.length < start + len) break;          // rest still arriving
          newest = new Blob([buf.slice(start, start + len)], { type: "image/jpeg" });
          buf = buf.subarray(start + len);
          if (!drawing) drawNewest();
        }
      }
    } catch (e) { /* fall through and retry */ }
    await new Promise(r => setTimeout(r, 1000));
  }
}
readStream();

// ---------------- 2. build the floating screen ----------------
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setClearColor(0x000000, 0);           // see-through = your real room
renderer.xr.enabled = true;
renderer.xr.setReferenceSpaceType("local");
renderer.xr.setFoveation(0);
// ^ Draw the whole view at full sharpness. By default the edges of your
//   view are drawn at lower resolution to save work ("foveation"), which
//   makes the screen look blurry whenever it isn't dead centre.
renderer.domElement.style.display = "none";    // only drawn inside the headset
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera();  // the headset controls this
const panelH = PANEL_WIDTH * VIDEO_H / VIDEO_W;
const screen = new THREE.Group();
scene.add(screen);

function roundedRect(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y);         s.lineTo(x + w - r, y);     s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h);     s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r);         s.quadraticCurveTo(x, y, x + r, y);
  return new THREE.ShapeGeometry(s);
}

const bezel = new THREE.Mesh(roundedRect(PANEL_WIDTH + 0.06, panelH + 0.06, 0.03),
  new THREE.MeshBasicMaterial({ color: 0x0b0d10, transparent: true, opacity: 0.92 }));
bezel.position.z = -0.005;                     // just behind the picture
screen.add(bezel);

screen.add(new THREE.Mesh(new THREE.PlaneGeometry(PANEL_WIDTH, panelH),
  new THREE.MeshBasicMaterial({ map: videoTexture, toneMapped: false })));

// small "LIVE / NO VIDEO" tag under the bottom-left corner
const tagCanvas = Object.assign(document.createElement("canvas"), { width: 512, height: 64 });
const tagCtx = tagCanvas.getContext("2d");
const tagTexture = new THREE.CanvasTexture(tagCanvas);
tagTexture.colorSpace = THREE.SRGBColorSpace;
const tag = new THREE.Mesh(new THREE.PlaneGeometry(0.4, 0.05),
  new THREE.MeshBasicMaterial({ map: tagTexture, transparent: true, toneMapped: false }));
tag.position.set(-PANEL_WIDTH / 2 + 0.2, -panelH / 2 - 0.07, 0);
screen.add(tag);

let tagText = "";
function setTag(text, color) {
  if (text === tagText) return;                // only redraw when it changes
  tagText = text;
  tagCtx.clearRect(0, 0, 512, 64);
  tagCtx.fillStyle = color;
  tagCtx.beginPath(); tagCtx.arc(24, 32, 10, 0, Math.PI * 2); tagCtx.fill();
  tagCtx.fillStyle = "#e8eaed";
  tagCtx.font = "600 32px system-ui, sans-serif";
  tagCtx.textBaseline = "middle";
  tagCtx.fillText(text, 46, 34);
  tagTexture.needsUpdate = true;
}

// Put the screen PANEL_DISTANCE in front of wherever you're looking
// (left/right only - looking up or down doesn't tilt it).
let needsPlacement = false;
function placeScreen(pose) {
  const p = pose.transform.position, o = pose.transform.orientation;
  const head = new THREE.Vector3(p.x, p.y, p.z);
  const forward = new THREE.Vector3(0, 0, -1)
    .applyQuaternion(new THREE.Quaternion(o.x, o.y, o.z, o.w));
  forward.y = 0;
  if (forward.lengthSq() < 1e-4) forward.set(0, 0, -1);
  forward.normalize();
  screen.position.copy(head).addScaledVector(forward, PANEL_DISTANCE);
  screen.position.y = head.y - PANEL_DROP;
  screen.lookAt(head.x, screen.position.y, head.z);   // face you, upright
}

renderer.setAnimationLoop((time, frame) => {
  if (!renderer.xr.isPresenting) return;
  if (frame && needsPlacement) {
    const pose = frame.getViewerPose(renderer.xr.getReferenceSpace());
    if (pose) { placeScreen(pose); needsPlacement = false; }
  }
  const live = performance.now() - lastFrameAt < 1000;
  setTag(live ? "LIVE" : "NO VIDEO", live ? "#34c759" : "#ff453a");
  renderer.render(scene, camera);
});

// ---------------- 3. the "Enter mixed reality" button ----------------
async function checkSupport() {
  if (!window.isSecureContext) {
    // Browsers only allow mixed reality on "secure" pages. Plain http:// to
    // the Pi counts as secure only after the one-time Quest setting below.
    const https = "https://" + location.hostname + ":__HTTPS_PORT__/xr";
    btn.textContent = "Mixed reality blocked on http://";
    msg.innerHTML =
      "One-time Quest setting: open <code>chrome://flags</code>, search " +
      "<b>insecure</b>, set <b>Insecure origins treated as secure</b> to " +
      "<b>Enabled</b>, type <code>" + location.origin + "</code> in its box, " +
      "tap outside the box, then tap <b>Relaunch</b>. " +
      'Or use the https page: <a style="color:#8cf" href="' + https + '">' + https + "</a>";
    return;
  }
  if (!navigator.xr || !(await navigator.xr.isSessionSupported("immersive-ar"))) {
    btn.textContent = "Mixed reality not available here";
    msg.textContent = "Open this page in the Meta Quest browser to use mixed reality.";
    return;
  }
  btn.disabled = false;
  btn.textContent = "Enter mixed reality";
  msg.textContent = "The camera appears as a floating screen in your room. " +
    "Squeeze a grip button to bring it back in front of you. " +
    "Press the Meta button on the right controller to leave.";
}

btn.addEventListener("click", async () => {
  try {
    const session = await navigator.xr.requestSession("immersive-ar");
    session.addEventListener("squeeze", () => { needsPlacement = true; });
    session.addEventListener("end", () => {
      btn.disabled = false; btn.textContent = "Enter mixed reality";
    });
    await renderer.xr.setSession(session);
    needsPlacement = true;
    btn.disabled = true; btn.textContent = "In mixed reality";
  } catch (e) {
    msg.textContent = "Couldn't start mixed reality: " + e.message;
  }
});

checkSupport();
</script>
</body>
</html>"""


@app.route("/xr")
def xr():
    """The headset page: https://PI_IP:8000/xr"""
    return (XR_PAGE.replace("__WIDTH__", str(WIDTH))
                   .replace("__HEIGHT__", str(HEIGHT))
                   .replace("__HTTPS_PORT__", str(HTTPS_PORT)))
    # ^ Fills in the picture size so the screen has the right shape.


# =============================================================================
# HTTPS CERTIFICATE - made once, automatically
# =============================================================================
def make_certificate():
    """Create cert.pem + key.pem next to this file, if they don't exist yet.

    https needs a "certificate" (proves who the server is) and a secret
    "key". A real certificate comes from a company that browsers trust; for
    a Pi on a home/school network we make our own ("self-signed"). The
    connection is still encrypted - browsers just can't verify who made it,
    which is why they show a warning the first time.
    """
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return
    log.info("Creating a self-signed https certificate (first run only)...")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", KEY_FILE, "-out", CERT_FILE,
         "-days", "825", "-subj", "/CN=picar"],
        check=True, capture_output=True)
    # ^ openssl comes with Raspberry Pi OS. -nodes = no password on the key,
    #   so the server can start by itself. 825 days = valid for over 2 years.
    os.chmod(KEY_FILE, 0o600)
    # ^ Only your user can read the secret key.


class NonBlockingHandshakeContext(ssl.SSLContext):
    """https settings that can't be frozen by one slow browser connection.

    THE BUG THIS FIXES: every https connection starts with a "handshake"
    (the two sides agree on encryption). Flask's built-in server does that
    handshake for each new connection in its ONE main thread, before
    handing the connection to its own thread. Browsers often open a
    connection and leave it idle - e.g. while showing the certificate
    warning, or opening a spare connection in advance. The main thread then
    waits on that idle connection, and NO other page can load: the browser
    just sits on "loading" forever.

    The fix: do_handshake_on_connect=False. The handshake then happens
    later, inside each connection's own thread, so an idle connection only
    ever blocks itself.
    """

    def wrap_socket(self, sock, *args, **kwargs):
        kwargs["do_handshake_on_connect"] = False
        return super().wrap_socket(sock, *args, **kwargs)


# =============================================================================
# START
# =============================================================================
if __name__ == "__main__":
    # Only runs when this file is started directly (`python3 camera_server.py`).

    make_certificate()
    tls = NonBlockingHandshakeContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(CERT_FILE, KEY_FILE)
    # ^ The https settings: our fixed context, loaded with the certificate.

    http_server = make_server("0.0.0.0", HTTP_PORT, app, threaded=True)
    https_server = make_server("0.0.0.0", HTTPS_PORT, app, threaded=True, ssl_context=tls)
    # ^ Two web servers sharing the same pages and the same camera.
    #   "0.0.0.0": accept connections from other devices on the network
    #     (the default would only allow the Pi itself).
    #   threaded=True: each viewer gets its own thread, so two browsers
    #     can watch at once and a slow viewer can't freeze the others.
    #   If either line fails with "Address already in use", another copy of
    #   this program (or the old one) is still running: `pkill -f camera_server`.

    camera.start_recording(encoder, FileOutput(output), quality=Quality[QUALITY])
    # ^ Start capturing. From now on, picamera2 calls output.write(jpeg)
    #   for every frame, in its own background thread.
    #   quality=...: how much detail each JPEG keeps (QUALITY setting above).
    log.info("Camera on: %dx%d at %d fps, %s quality", WIDTH, HEIGHT, FRAMES_PER_SECOND, QUALITY)
    log.info("Laptop:  http://<this Pi's IP>:%d       (find the IP with: hostname -I)", HTTP_PORT)
    log.info("Headset: https://<this Pi's IP>:%d/xr   (mixed reality)", HTTPS_PORT)

    try:
        threading.Thread(target=http_server.serve_forever, daemon=True).start()
        # ^ The http server runs in a background thread...
        https_server.serve_forever()
        # ^ ...and the https server in this one, until Ctrl+C.
    finally:
        # Runs however the program ends (Ctrl+C or an error).
        camera.stop_recording()
        camera.close()
        # ^ Release the camera properly. If a program exits without doing
        #   this, the next program to use the camera may report it as busy.
        log.info("Camera off")

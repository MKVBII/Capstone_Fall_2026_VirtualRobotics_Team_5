#!/usr/bin/env python3
# ^ "Shebang": lets Linux run this file directly as ./camera_server.py.
#   Ignored when you type `python3 camera_server.py`.
"""
camera_server.py - the car's camera, live in a browser, plus the website.

Runs on:   the Raspberry Pi, from ~/robot-car
Run:       python3 camera_server.py          (Ctrl+C to stop)
Serves:    http://PI_IP:8000/  or  https://PI_IP:8443/   the website:
             /            start screen
             /begin       pre-drive checks + controls + "Enter mixed reality"
                          (the headset page; /drive and /xr are the same page)
             /settings    settings (shared with the headset's settings panel)
             /spectator   big video + the driver's readings, for an audience
             /about       what the project does and how it works
             /video       just the video, full window
           Mixed reality needs https: use https://PI_IP:8443/begin on the Quest
           (or the one-time Quest setting in SETUP.md for http).
Pages:     web/  (pages/, css/, js/, lib/) - this file only sends them
Works with drive_server.py, which the headset page connects to for the
joysticks (wss://PI_IP:8765). Run both from the same folder so they share
one cert.pem / key.pem.

=============================================================================
HOW IT WORKS
=============================================================================
    Pi camera -> picamera2 -> JPEG pictures -> Flask web server -> browser

1. picamera2 (the Raspberry Pi's camera library) captures video and
   compresses each frame into a JPEG picture.
2. Flask (a small Python web server) answers on TWO ports at once:
     http://PI_IP:8000           the plain video page - no security warning
     https://PI_IP:8443/drive    the headset page (mixed reality)
   Both also serve /stream, the video itself, and the files in web/.
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
* A headset can only run ONE mixed-reality session at a time, so the
  camera screen and the joystick sending live on the same page
  (web/js/drive.js).
* Only ONE program can use the camera (and port 8000) at a time. Stop any
  older camera_server.py before starting this one.

=============================================================================
ADDRESSES THIS SERVER ANSWERS
=============================================================================
    /                      web/pages/index.html      start screen
    /begin, /drive, /xr    web/pages/drive.html      headset page (begin screen in 2D)
    /settings              web/pages/settings.html
    /spectator             web/pages/spectator.html
    /about                 web/pages/about.html
    /video                 web/pages/video.html      plain video page
    /stream                the MJPEG video
    /config.json           picture size + port numbers, read by the pages
    /api/settings          GET: saved settings (JSON). POST: save new ones.
                           Kept in settings.json next to this file, so the
                           laptop settings page and the headset share them.
    /api/logs              GET: the session logs drive_server.py has saved
    /logs/<name>           download one session log (CSV)
    /css/..., /js/..., /lib/..., /img/...   files from web/
"""

import io
import json
# ^ Reading and writing settings.json.
# ^ io.BufferedIOBase: the "file-like object" shape picamera2 writes into.
import logging
# ^ Timestamped messages, so you can see in the SSH window what's happening.
import os
# ^ os.path: finds the folder this file is in (for web/ and the certificate).
import ssl
# ^ Python's built-in https/encryption support.
import subprocess
# ^ Runs the `openssl` command once, to create the https certificate.
import threading
# ^ threading.Condition: lets the web server wait for "a new frame has arrived".
import time
# ^ Used to measure and log the frame rate.

from flask import Flask, Response, jsonify, request, send_from_directory
# ^ Flask: the web server. Response: lets us send the never-ending video
#   stream. jsonify / send_from_directory: send JSON and files. request: the
#   settings a page sends to /api/settings.
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
# ^ The quality levels for QUALITY below.

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("camera")

# =============================================================================
# SETTINGS - everything you might want to change is here.
# =============================================================================
HTTP_PORT = 8000
# ^ The "door number" for the plain page: http://PI_IP:8000
#   8000 is a common choice for test web servers; any free number works.

HTTPS_PORT = 8443
# ^ The door number for the headset page: https://PI_IP:8443/drive
#   (8443 is the usual "second https port"). The old
#   archive/early-tests/https_server.py also used 8443 - don't run both.

DRIVE_PORT = 8765
# ^ Where drive_server.py listens for the joysticks (wss://PI_IP:8765).
#   Must match PORT in drive_server.py. Sent to the headset page in /config.json.

VIEWER_PORT = 8766
# ^ drive_server.py's view-only door (ws://PI_IP:8766, no certificate), used by
#   laptop pages opened over plain http. Must match VIEWER_PORT in drive_server.py.

WIDTH, HEIGHT = 1024, 768
# ^ Picture size in pixels. Keep it 4:3 (640x480, 1024x768, 1280x960):
#   that's the camera sensor's own shape, so you get its WHOLE view.
#   Widescreen sizes like 1280x720 make the camera use only the middle of
#   its sensor, which looks zoomed in. 640x480 is the lightest on Wi-Fi.

FULL_VIEW = True
# ^ True = always use the camera's widest view (see full_view_mode() below).
#   False = let picamera2 choose by itself.

FRAMES_PER_SECOND = 45
# ^ Pictures per second. More = smoother motion and fresher pictures.
#   If the camera can't reach this at WIDTH x HEIGHT in full view, the
#   start-up log says so and uses its maximum (about 46 at 1024x768 for the
#   kit's 5 MP camera). Uses roughly 15-25 megabits/s of Wi-Fi. If the
#   "camera running" log shows far fewer frames/s, or the video stutters,
#   set 30.

QUALITY = "HIGH"
# ^ How much detail each JPEG keeps: VERY_LOW, LOW, MEDIUM, HIGH or
#   VERY_HIGH. Higher = sharper but more Wi-Fi data. Drop to MEDIUM if the
#   video stutters on your Wi-Fi.

SHORT_EXPOSURE = True
# ^ Less motion blur. Each picture is a short "exposure" (like a fast camera
#   shutter), so things moving - or the car turning - smear less. The camera
#   brightens the picture electronically instead, so in dim rooms it can
#   look grainier. Set to False for the camera's normal exposure.
#   (Ignored while SHUTTER_US is set.)

SHUTTER_US = 2000
# ^ Strongest motion-blur fix: a FIXED shutter time, in microseconds
#   (2000 = 1/500 s). None = off (SHORT_EXPOSURE above decides). 8000
#   (1/125 s) is brighter; 4000 (1/250 s) in between. Shorter = sharper
#   motion but darker, so the camera brightens it electronically and it gets
#   grainier - it works best in a well-lit room.

ROTATE_180 = False
# ^ Set to True if the picture comes out upside down. That depends on how
#   the camera is mounted on the car. The camera flips it for free.

HERE = os.path.dirname(os.path.abspath(__file__))
# ^ The folder this file is in (~/robot-car on the Pi).
WEB_DIR = os.path.join(HERE, "web")
PAGES_DIR = os.path.join(WEB_DIR, "pages")
# ^ The website's files. Flask serves everything in web/ at the top level,
#   e.g. web/js/drive.js -> /js/drive.js.
SETTINGS_FILE = os.path.join(HERE, "settings.json")
# ^ The website/headset settings, saved by /api/settings. Delete it to go
#   back to the defaults (or use "Reset to defaults" on the settings page).
LOG_DIR = os.path.join(HERE, "logs")
# ^ Where drive_server.py saves session logs (same folder it uses).
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
        """Store one new JPEG and wake every waiting viewer.

        Called by picamera2, from its own background thread, for each frame.

        Args:
            buf: the JPEG, as bytes.
        Returns:
            The number of bytes "written" (file-like objects must report it).
        """
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
    (smaller modes = less work for the Pi).

    If NO full-view mode is as fast as FRAMES_PER_SECOND, it uses the
    fastest full-view mode and lowers FRAMES_PER_SECOND to match, rather
    than switching to a faster zoomed-in mode. So it's safe to ask for a
    high frame rate: you get the most this camera can do in full view.

    Args:
        cam: the opened Picamera2.
    Returns:
        A sensor setting for create_video_configuration(sensor=...), or
        None if it can't tell (picamera2 then chooses as usual).
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
app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
# ^ Create the Flask web app. __name__ tells Flask where this file lives.
#   static_folder / static_url_path: every file in web/ is served at the top
#   level, e.g. web/css/drive.css -> /css/drive.css. The addresses below
#   (/, /drive, /stream ...) take priority over files with the same name.


def page(name):
    """Send one page from web/pages/."""
    return send_from_directory(PAGES_DIR, name)


@app.route("/")
def index():
    """The start screen."""
    return page("index.html")


@app.route("/begin")
@app.route("/drive")
@app.route("/xr")
def drive():
    """The headset page: begin screen in 2D, driving in mixed reality.
    /drive and /xr are older addresses for the same page."""
    return page("drive.html")


@app.route("/settings")
def settings_page():
    """The settings page (laptop or Quest browser)."""
    return page("settings.html")


@app.route("/spectator")
def spectator():
    """Big video + the driver's readings, view-only, for an audience."""
    return page("spectator.html")


@app.route("/about")
def about():
    """What the project does, how it works, project details, gallery."""
    return page("about.html")


@app.route("/video")
def video():
    """Just the video, full window (the old plain page)."""
    return page("video.html")


@app.route("/config.json")
def config():
    """Settings the pages need, so they're set in ONE place (above).

    Returns:
        JSON: video_width, video_height, https_port, drive_port, viewer_port.
    """
    return jsonify(video_width=WIDTH, video_height=HEIGHT,
                   https_port=HTTPS_PORT, drive_port=DRIVE_PORT, viewer_port=VIEWER_PORT)


settings_lock = threading.Lock()
# ^ Two pages saving at the same moment must not write the file at once.


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """Read or save the website/headset settings.

    GET returns what's saved ({} if nothing yet; each page fills in its
    defaults, see web/js/settings.js). POST saves the JSON object sent,
    replacing what was there; it must be an object of at most 20 KB.
    """
    with settings_lock:
        if request.method == "POST":
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or len(request.get_data()) > 20_000:
                return jsonify(error="settings must be a JSON object under 20 KB"), 400
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, SETTINGS_FILE)
            # ^ Write a new file, then swap it in, so a power cut mid-save
            #   can't leave a half-written settings file.
            return jsonify(ok=True)
        try:
            with open(SETTINGS_FILE) as f:
                return jsonify(json.load(f))
        except (OSError, ValueError):
            return jsonify({})


@app.route("/api/logs")
def api_logs():
    """List the saved session logs, newest first.

    Returns:
        JSON list of {name, size_kb, modified} (modified = seconds since 1970).
    """
    try:
        names = [n for n in os.listdir(LOG_DIR) if n.endswith(".csv")]
    except OSError:
        names = []
    logs = []
    for n in names:
        st = os.stat(os.path.join(LOG_DIR, n))
        logs.append({"name": n, "size_kb": round(st.st_size / 1024, 1), "modified": st.st_mtime})
    logs.sort(key=lambda l: l["modified"], reverse=True)
    return jsonify(logs)


@app.route("/logs/<path:name>")
def download_log(name):
    """Download one session log. send_from_directory refuses names that
    try to reach outside the logs folder."""
    return send_from_directory(LOG_DIR, name, as_attachment=True)


def generate_frames():
    """Produce the never-ending MJPEG stream for one viewer.

    A "generator" (a function that uses `yield`) hands out data piece by
    piece. Flask sends each piece to the browser as soon as it's yielded,
    and keeps asking for more, forever - which is what makes this a stream.

    Yields:
        One MJPEG "part" (headers + one JPEG) per new camera frame.
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
        """Same as the normal wrap_socket, but with the handshake postponed."""
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
    log.info("Laptop:  http://<this Pi's IP>:%d          (find the IP with: hostname -I)", HTTP_PORT)
    log.info("Headset: https://<this Pi's IP>:%d/begin   (mixed reality)", HTTPS_PORT)

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

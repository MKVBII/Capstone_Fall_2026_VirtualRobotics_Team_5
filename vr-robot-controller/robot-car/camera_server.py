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
2. Flask (a small Python web server) serves two addresses:
     http://PI_IP:8000/         a web page that shows the video
     http://PI_IP:8000/stream   the video itself
3. The video is "MJPEG": a never-ending stream of JPEG pictures, one after
   another. Browsers can show this in an ordinary <img> tag with no extra
   code - each new picture replaces the last, which looks like video.

WHY THIS APPROACH
* It only uses libraries already installed on the Pi (picamera2, flask).
* Plain http:// works in any laptop browser - no certificates needed yet.
  (The headset will need https://; that comes in the next step, not now.)
* Delay is low - usually well under half a second - because each picture
  is sent the moment it's ready. Good enough to steer by.

=============================================================================
HOW TO RUN IT (on the Pi)
=============================================================================
    cd ~/robot-car
    python3 camera_server.py

Then on a laptop on the same Wi-Fi, open:   http://PI_IP:8000
Stop it with Ctrl+C. (Flask prints a "development server" warning on
start-up - that's normal and fine for this project.)
"""

import io
# ^ io.BufferedIOBase: the "file-like object" shape picamera2 writes into.
import logging
# ^ Timestamped messages, so you can see in the SSH window what's happening.
import threading
# ^ threading.Condition: lets the web server wait for "a new frame has arrived".
import time
# ^ Used to measure and log the frame rate.

from flask import Flask, Response
# ^ Flask: the web server. Response: lets us send the never-ending video stream.
#   Installed by `pip3 install flask ... --break-system-packages` (SETUP.md step 3).
from picamera2 import Picamera2
# ^ The Raspberry Pi camera library. Installed by
#   `sudo apt install -y python3-picamera2` (SETUP.md step 3).
from picamera2.outputs import FileOutput
# ^ Tells picamera2 to send its compressed frames to a "file" - which will
#   be our StreamingOutput object below, not a real file on disk.
from libcamera import Transform
# ^ Lets the camera flip/rotate the picture itself (comes with picamera2).

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("camera")

# =============================================================================
# SETTINGS - everything you might want to change is here.
# =============================================================================
PORT = 8000
# ^ The "door number" the browser connects to: http://PI_IP:8000
#   8000 is a common choice for test web servers; any free number works.

WIDTH, HEIGHT = 640, 480
# ^ Picture size in pixels. 640x480 is a safe start: sharp enough to steer
#   by, and each JPEG is only ~30-50 KB, which ordinary Wi-Fi handles
#   easily. Try 1280x720 once this works, if the Wi-Fi keeps up.

FRAMES_PER_SECOND = 15
# ^ 15 pictures a second looks like smooth-enough video for driving and
#   uses roughly 3-6 megabits/s of Wi-Fi. Raise to 20-30 if it stays smooth.

ROTATE_180 = False
# ^ Set to True if the picture comes out upside down. That depends on how
#   the camera is mounted on the car. The camera flips it for free.


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

camera.configure(camera.create_video_configuration(
    main={"size": (WIDTH, HEIGHT)},
    # ^ The picture size to capture.
    controls={"FrameRate": FRAMES_PER_SECOND},
    # ^ Ask the camera itself for this frame rate, so we don't capture
    #   frames only to throw them away.
    transform=Transform(hflip=ROTATE_180, vflip=ROTATE_180),
    # ^ Flipping both horizontally and vertically = rotating 180 degrees.
))

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
    body { margin: 0; padding: 16px; background: #111; color: #eee;
           font-family: sans-serif; text-align: center; }
    img  { max-width: 100%; background: #000; }
  </style>
</head>
<body>
  <h2>Pi Car camera</h2>
  <img src="/stream" alt="If this stays blank, check the camera_server.py window on the Pi">
  <p>Wave a hand in front of the camera to judge the delay.</p>
</body>
</html>"""
# ^ The whole web page, kept inside this file so there's only one file to
#   copy. The <img src="/stream"> line is the entire video player: the
#   browser keeps showing each new picture the /stream address sends.


@app.route("/")
def index():
    """The home page: http://PI_IP:8000/"""
    return PAGE
    # ^ `@app.route("/")` above means "run this function when a browser
    #   visits the site's main address". It just returns the page above.


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
# START
# =============================================================================
if __name__ == "__main__":
    # Only runs when this file is started directly (`python3 camera_server.py`).

    camera.start_recording(encoder, FileOutput(output))
    # ^ Start capturing. From now on, picamera2 calls output.write(jpeg)
    #   for every frame, in its own background thread.
    log.info("Camera on: %dx%d at %d fps", WIDTH, HEIGHT, FRAMES_PER_SECOND)
    log.info("Open http://<this Pi's IP>:%d in a browser (find the IP with: hostname -I)", PORT)

    try:
        app.run(host="0.0.0.0", port=PORT, threaded=True)
        # ^ Start the web server and run until Ctrl+C.
        #   host="0.0.0.0": accept connections from other devices on the
        #     network (the default would only allow the Pi itself).
        #   threaded=True: each viewer gets its own thread, so two browsers
        #     can watch at once and a slow viewer can't freeze the others.
    finally:
        # Runs however the program ends (Ctrl+C or an error).
        camera.stop_recording()
        camera.close()
        # ^ Release the camera properly. If a program exits without doing
        #   this, the next program to use the camera may report it as busy.
        log.info("Camera off")

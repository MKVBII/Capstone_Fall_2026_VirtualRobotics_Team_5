#!/usr/bin/env python3
# ^ The "shebang" line. On Linux it tells the system "run this file with
#   python3" if you ever run it directly as ./motor_test.py. When you type
#   `python3 motor_test.py` it is simply ignored.

"""
motor_test.py - spin each wheel briefly in each direction to prove the
motor hardware works, before any networking or headset code is involved.

=============================================================================
WHY THIS SCRIPT EXISTS
=============================================================================
The full project is: Quest headset -> Wi-Fi -> Python server on the Pi ->
motors. When something doesn't move, the fault could be in any of those
pieces. This script removes everything except the last piece, so if the
wheels turn here, the hardware is proven good and any later problem must
be in software or networking. That "test one layer at a time" approach is
the single biggest time-saver in robotics debugging.

The chain this script tests:

    Python  ->  I2C bus  ->  PWM HAT (PCA9685 chip)  ->  motor driver  ->  motors
                                                            ^
    Python  ->  GPIO pins  ---------------------------------+
                (direction)

If the wheels turn the right way, all of these are confirmed at once:
  * I2C is enabled on the Pi
  * the PWM HAT is seated on the Pi's pins and powered
  * the motor driver board is wired to the HAT and the Pi correctly
  * the battery is delivering power to the motors

=============================================================================
HOW THE MOTOR DRIVER BOARD WORKS (read this once, everything else follows)
=============================================================================
The car's motor driver is an L298N-style "H-bridge" board. An H-bridge is
a set of electronic switches that can send battery current through a
motor in EITHER direction, which is how one motor can go forwards and
backwards. A Pi pin can't power a motor directly (far too little
current), so the Pi only sends small control signals and the H-bridge
does the heavy lifting from the battery.

Each motor needs two kinds of control signal:

  DIRECTION - two on/off pins per motor:
                IN1 + IN2 control the LEFT motor
                IN3 + IN4 control the RIGHT motor
              One pin on and the other off = spin one way.
              Swap them                     = spin the other way.
              Both off                      = no drive (motor stops).
              These come straight from the Pi's GPIO pins.

  SPEED     - one "enable" pin per motor (ENA for left, ENB for right),
              fed with PWM (pulse-width modulation): the signal flicks
              on and off very fast, and the fraction of time it is ON
              (the "duty cycle") sets the average power. 0% = stopped,
              50% = about half speed, 100% = full speed.
              The Pi itself is poor at generating steady PWM, so the
              PCA9685 chip on the HAT does it, and the Pi just tells that
              chip what duty cycle to hold (over I2C).

So "go forward at 35%" really means two steps:
    1. set the direction pins to the "forward" pattern
    2. set the PWM channels to a 35% duty cycle

=============================================================================
!!! BEFORE YOU RUN THIS !!!
=============================================================================
PUT THE CAR ON A BLOCK so the wheels spin in the air and it cannot drive
off the table. A book or a roll of tape works. Speeds and durations below
are deliberately small, but a car that lurches off a bench lands on the Pi.

TURN ON THE CAR'S BATTERY. The motors are powered by the battery pack,
not by the Pi. The Pi can be on with the motor power off, in which case
this script runs without errors but nothing moves.

RUN IT:   cd ~/robot-car && python3 motor_test.py      (see SETUP.md, Test 1)
PANIC:    Ctrl+C                     (the script stops the motors on its way out)
=============================================================================
"""
# ^ Everything between the triple quotes is a "docstring": a big comment
#   Python stores with the file. It has no effect on what the code does.

import time
# ^ Python's built-in time module. We only use time.sleep(seconds), which
#   pauses the program so each movement lasts a set amount of time.

# --- GPIO library -----------------------------------------------------------
# gpiozero is the GPIO library the Raspberry Pi Foundation recommends and
# ships pre-installed on Raspberry Pi OS. (OSOYOO's own sample code uses
# the older RPi.GPIO library instead. RPi.GPIO still works on the Pi 2-4
# this kit supports, but it does NOT work on a Pi 5, so gpiozero is the
# safer long-term choice. Both control the same pins the same way.)
#
# OutputDevice is gpiozero's simplest building block: one pin that you
# switch on (3.3 V, "high") or off (0 V, "low"). That is exactly what the
# direction pins need.
#
# Installed by `sudo apt install -y python3-gpiozero python3-lgpio`
# (SETUP.md step 3). lgpio is the low-level library gpiozero uses
# underneath on Raspberry Pi OS Bookworm.
# If you get "No module named gpiozero", re-run that apt line.
from gpiozero import OutputDevice

# --- PWM HAT libraries ------------------------------------------------------
# These three come from Adafruit's "CircuitPython" libraries, installed by
# `pip3 install adafruit-circuitpython-pca9685 adafruit-blinka --break-system-packages`
# (SETUP.md step 3). They are the same ones OSOYOO's sample uses.
# ("blinka" is what provides `board` and `busio` on a Raspberry Pi.)
import board
# ^ "board" knows which physical pins on THIS model of Pi are the I2C
#   clock (SCL) and data (SDA) lines, so we don't hard-code them.
import busio
# ^ "busio" opens and manages the I2C bus - the two-wire connection the
#   Pi uses to send commands to the PCA9685 chip on the HAT.
from adafruit_pca9685 import PCA9685
# ^ The driver for the PCA9685 chip itself. It turns "set channel 0 to
#   35%" into the right I2C messages so we never deal with raw registers.


# =============================================================================
# CONFIG - every number you might need to change lives here, in one place,
# so nobody has to hunt through the code to adjust the test.
# =============================================================================

# --- Direction pins (GPIO) -----------------------------------------------
# These are "BCM" numbers: the Broadcom chip's own name for each pin, which
# is what gpiozero expects. They are NOT the physical position on the
# 40-pin header. The two numbering systems have no simple pattern between
# them, so always check which one a diagram or library is using. Physical
# positions are noted in each comment for when you're tracing wires.
#
# Values come from OSOYOO's own sample code (picar-basic.py). The driving
# code we build next will copy these exact numbers from this file, so this
# test checks exactly the wiring the real program will use.
IN1_PIN = 23   # physical pin 16 - left motor, direction input A
IN2_PIN = 24   # physical pin 18 - left motor, direction input B
IN3_PIN = 27   # physical pin 13 - right motor, direction input A
IN4_PIN = 22   # physical pin 15 - right motor, direction input B

# --- Speed channels (PWM HAT) -------------------------------------------
# The PCA9685 has 16 numbered outputs ("channels", 0-15). OSOYOO wires the
# motor driver's speed inputs to the first two.
ENA_CHANNEL = 0   # left motor speed  (ENA on the driver board)
ENB_CHANNEL = 1   # right motor speed (ENB on the driver board)

# ASSUMPTION WORTH CHECKING: ENA/IN1/IN2 drive one motor and ENB/IN3/IN4
# drive the other; we assume the first set is the LEFT wheel. OSOYOO's
# turnRight() code agrees with this. If the "left" test below spins the
# wrong wheel, the assumption is backwards: swap the two channel numbers
# AND swap IN1/IN2 with IN3/IN4.

# --- PWM frequency -------------------------------------------------------
# How many times per second the PWM signal flicks on and off.
#
# The PCA9685 has ONE frequency setting shared by all 16 channels, which
# forces a trade-off:
#   * DC motors run smoother and quieter at higher frequencies (~1000 Hz).
#     At low frequencies they can whine and feel jerky at slow speeds.
#   * Hobby servos (like the SG90 camera-pan servo in this kit) REQUIRE
#     about 50-60 Hz and won't work properly at 1000 Hz.
# OSOYOO's sample uses 60 Hz so the servo can share the HAT. This test
# uses 1000 Hz because it's motors-only, and it worked, so the driving code
# will use 1000 Hz too. When we add the camera-pan servo, we'll have to
# choose: drop everything to 50-60 Hz, or drive the servo from a spare
# GPIO pin instead of the HAT.
PWM_FREQUENCY = 1000

# --- Speed ------------------------------------------------------------------
# Fraction of full power, 0.0 (stopped) to 1.0 (full).
# 0.35 is gentle but above the "stall threshold": below roughly 0.25,
# small geared motors often just hum without turning. That looks like a
# fault but isn't - the motor simply doesn't have enough power to start.
SPEED = 0.35

# --- Timing ---------------------------------------------------------------
DURATION = 0.4   # seconds each movement lasts. Short, because it's a test.
PAUSE = 0.6      # seconds of stillness between movements, so you can see
                 # each one separately and the gearboxes aren't slammed
                 # straight from forward into reverse (hard on the gears).


# =============================================================================
# SETUP - claim the hardware. This runs once when the script starts.
# =============================================================================

# Create one OutputDevice per direction pin. Creating it "claims" the pin
# for this program and sets it to OFF, so no motor can start by accident
# before we deliberately tell it to.
in1 = OutputDevice(IN1_PIN)
in2 = OutputDevice(IN2_PIN)
in3 = OutputDevice(IN3_PIN)
in4 = OutputDevice(IN4_PIN)

# Open the I2C bus using the Pi's clock (SCL) and data (SDA) pins.
# If THIS line errors, I2C isn't enabled or the HAT isn't seated: run
# `i2cdetect -y 1` and confirm "40" (the PCA9685's address) is in the grid.
i2c = busio.I2C(board.SCL, board.SDA)

# Connect to the PCA9685 chip over that bus.
pca = PCA9685(i2c)

# Set the shared PWM frequency for all 16 channels (see CONFIG above).
pca.frequency = PWM_FREQUENCY


# =============================================================================
# HELPER FUNCTIONS - small, named building blocks so the test sequence at
# the bottom reads like plain English.
# =============================================================================

def set_speed(channel, fraction):
    """Set one PCA9685 channel to a fraction (0.0-1.0) of full power."""

    # Clamp the value into the safe range 0.0-1.0. If a bug ever passed
    # in 5.0 or -2.0, this turns it into 1.0 or 0.0 instead of sending
    # nonsense to the chip. Cheap insurance, and an important habit once
    # live joystick values from the headset start feeding into this.
    fraction = max(0.0, min(1.0, fraction))

    # The library wants the duty cycle as a 16-bit whole number, where
    # 0 = always off and 65535 (the biggest 16-bit number) = always on.
    # So 0.35 becomes int(0.35 * 65535) = 22937. int() drops the decimal
    # part because the chip only accepts whole numbers.
    pca.channels[channel].duty_cycle = int(fraction * 65535)


def stop():
    """Stop both motors and leave the driver board in a known, idle state."""

    # Speed to zero on both sides. This alone would stop the wheels...
    set_speed(ENA_CHANNEL, 0)
    set_speed(ENB_CHANNEL, 0)

    # ...but we ALSO switch every direction pin off. Doing both means the
    # H-bridge is fully idle rather than "armed in a direction with zero
    # speed", so a stray speed signal later can't make a wheel jump.
    # It's the same thing OSOYOO's own stopcar() function does.
    in1.off()
    in2.off()
    in3.off()
    in4.off()


def drive(left_forward, right_forward, speed=SPEED, duration=DURATION):
    """
    Drive both wheels for a fixed time, then stop.

    left_forward / right_forward: True = that wheel spins "forward",
    False = it spins in reverse. speed and duration default to the CONFIG
    values but can be overridden, e.g. drive(True, True, speed=0.5).

    Every basic movement of a two-wheeled car comes from these two values
    (this is called "differential" or "tank" steering):
      both forward                  -> straight ahead
      both reverse                  -> straight back
      left reverse + right forward  -> spins left on the spot
      left forward + right reverse  -> spins right on the spot
    """

    # IMPORTANT - WHICH PIN PATTERN IS "FORWARD"?
    # This script treats IN1 on / IN2 off as forward. OSOYOO's tutorial
    # text says the same, BUT OSOYOO's actual sample code (picar-basic.py)
    # does the opposite: its forward() turns IN2/IN4 on and IN1/IN3 off,
    # Which is right depends on how the motor wires are physically
    # connected, so this test is how we find out: watch the wheels when it
    # prints "forward", and write the answer in SETUP.md's Test 1 notes.
    #   * Wheels really go forward  -> this pattern is right.
    #   * Wheels go backward        -> OSOYOO's code is right; only this
    #     script's labels are swapped.
    # The driving code we build next will use whichever pattern is right.

    # Left motor direction: exactly one of the two pins is on. Both on at
    # once would make the H-bridge brake rather than drive, so we always
    # turn one off as we turn the other on.
    if left_forward:
        in1.on()
        in2.off()
    else:
        in1.off()
        in2.on()

    # Right motor direction, same pattern with IN3/IN4.
    if right_forward:
        in3.on()
        in4.off()
    else:
        in3.off()
        in4.on()

    # Directions are set FIRST and power applied SECOND, so a wheel never
    # receives power while its direction pins are half-changed.
    set_speed(ENA_CHANNEL, speed)
    set_speed(ENB_CHANNEL, speed)

    # Wait while the wheels turn. The motors keep running during the sleep
    # because the PCA9685 keeps generating the PWM signal on its own
    # internal clock - Python doesn't need to keep "telling" the motors to
    # spin. Offloading that job is the whole point of having the chip.
    time.sleep(duration)

    # Always stop at the end of a movement, so every drive() call leaves
    # the car stationary no matter what comes next.
    stop()


# =============================================================================
# THE TEST SEQUENCE - forward, backward, left, right, each one short.
# =============================================================================

# try/finally guarantees the code in "finally" runs no matter how the
# "try" block ends: normally, because of an error, or because you pressed
# Ctrl+C. Without it, an error in the middle of drive() could leave the
# motors powered and the car running away across the bench.
try:
    print("forward")                                     # say what's about to happen...
    drive(left_forward=True, right_forward=True)         # ...do it...
    time.sleep(PAUSE)                                    # ...then pause so moves don't blur together

    print("backward")
    drive(left_forward=False, right_forward=False)       # both wheels reverse
    time.sleep(PAUSE)

    print("left")
    drive(left_forward=False, right_forward=True)        # left back + right forward = spin left
    time.sleep(PAUSE)

    print("right")
    drive(left_forward=True, right_forward=False)        # left forward + right back = spin right
    time.sleep(PAUSE)

    print("done")

finally:
    # Runs however the script ended. Stop first - safety before tidiness.
    stop()

    # Release the PCA9685 (stops its outputs and frees the I2C bus) so the
    # next program - another test run, or server.py - can claim it cleanly.
    pca.deinit()

    # The four GPIO pins need no manual release: gpiozero automatically
    # closes every OutputDevice when the script exits, returning the pins
    # to a safe, unclaimed state.

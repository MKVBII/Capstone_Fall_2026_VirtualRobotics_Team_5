#!/usr/bin/env python3
"""
pi_status.py - health readings from the Pi itself, for the headset's info panel.

Runs on:   the Raspberry Pi, from ~/robot-car
Test:      python3 hardware/pi_status.py     prints the readings once a second
Used by:   drive_server.py, which calls read_status() once a second and sends
           the result to the headset.

Everything here comes from what Raspberry Pi OS already provides - no extra
installs:

    cpu_temp_c      gpiozero's CPUTemperature (reads the Pi's own sensor).
                    The Pi slows itself down above ~80 C.
    cpu_load_pct    os.getloadavg(): how busy the Pi has been over the last
                    minute, as a % of its cores. Near/over 100% = overloaded
                    (usually the camera at a high frame rate).
    wifi_dbm        /proc/net/wireless: Wi-Fi signal strength.
                    -50 great, -67 fine for video, -75 shaky, -80 dropping.
    power_ok        `vcgencmd get_throttled`: False = the Pi is getting too
    power_warned    little voltage RIGHT NOW (low battery!) / did at some
                    point since boot. This is the Pi's OWN supply, not a
                    reading of the car battery's charge.
    throttled       True = the Pi is slowing itself down (heat or power).

Any reading the Pi can't give (e.g. running on a laptop) comes back as None,
and the headset leaves that line out.
"""

import os
import subprocess
import time

_cpu_temp = None          # the CPUTemperature object, made on first use
_cpu_temp_failed = False  # True once it has failed: don't keep retrying


def cpu_temp_c():
    """The Pi's processor temperature.

    Returns:
        Degrees Celsius (1 decimal), or None if it can't be read (not a Pi).
    """
    global _cpu_temp, _cpu_temp_failed
    if _cpu_temp_failed:
        return None
    try:
        if _cpu_temp is None:
            from gpiozero import CPUTemperature
            _cpu_temp = CPUTemperature()
        return round(_cpu_temp.temperature, 1)
    except Exception:
        _cpu_temp_failed = True          # not a Pi (or no sensor): stop trying
        return None


def cpu_load_pct():
    """How busy the Pi has been over the last minute.

    Returns:
        Percent of all cores (100 = fully busy), or None if unavailable.
    """
    try:
        return round(os.getloadavg()[0] / os.cpu_count() * 100)
    except (OSError, AttributeError):
        return None


def wifi_dbm(interface="wlan0"):
    """Wi-Fi signal level, read from /proc/net/wireless.

    A line there looks like:
        wlan0: 0000   59.  -51.  -256        0      0      0 ...
                      ^qual ^level (dBm)

    Args:
        interface: the Wi-Fi interface name ("wlan0" on a Pi).
    Returns:
        Signal in dBm (e.g. -51; closer to 0 is stronger), or None if the
        interface isn't found (not on Wi-Fi, or not a Pi).
    """
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                if line.strip().startswith(interface + ":"):
                    return int(float(line.split()[3].rstrip(".")))
    except (OSError, ValueError, IndexError):
        pass
    return None


def power_flags():
    """Under-voltage and throttling flags from `vcgencmd get_throttled`.

    It prints e.g. throttled=0x50005. The bits used:
        0x1     under-voltage NOW          0x10000  under-voltage since boot
        0x4     throttled NOW              0x40000  throttled since boot

    Returns:
        (power_ok, power_warned, throttled), or (None, None, None) if
        vcgencmd isn't available.
    """
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                             text=True, timeout=1).stdout
        bits = int(out.strip().split("=")[1], 16)
        return (not bits & 0x1, bool(bits & 0x10000), bool(bits & 0x4))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, None, None


def read_status():
    """All readings at once, as sent to the headset.

    Returns:
        dict with cpu_temp_c, cpu_load_pct, wifi_dbm, power_ok,
        power_warned, throttled (any of them may be None).
    """
    power_ok, power_warned, throttled = power_flags()
    return {
        "cpu_temp_c": cpu_temp_c(),
        "cpu_load_pct": cpu_load_pct(),
        "wifi_dbm": wifi_dbm(),
        "power_ok": power_ok,
        "power_warned": power_warned,
        "throttled": throttled,
    }


# =============================================================================
# TEST MODE: python3 hardware/pi_status.py
# =============================================================================

if __name__ == "__main__":
    try:
        while True:
            print(read_status())
            time.sleep(1)
    except KeyboardInterrupt:
        pass

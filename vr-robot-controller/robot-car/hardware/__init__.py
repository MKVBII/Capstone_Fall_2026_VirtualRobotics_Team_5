"""
hardware - the car's parts, one file each, used by drive_server.py.

    camera_pan.py    the front camera servo (head-look)
    rear_sensor.py   the two rear ultrasonic sensors (obstacles + edges)
    pi_status.py     Pi temperature, load, Wi-Fi and power readings

Each file can also be run by itself as a test, from ~/robot-car, e.g.
    python3 hardware/rear_sensor.py --selftest

(This file makes the folder a Python "package", so drive_server.py can say
`from hardware.rear_sensor import RearSensor`.)
"""

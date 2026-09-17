# Robot -> VR status/telemetry. Every adapter publishes this, even if it
# only fills in a subset of fields (see docs/message_contracts.md — fields
# a robot doesn't support are left at a documented default, not omitted).

std_msgs/Header header

float32 battery_voltage      # volts, 0 if unknown
bool    link_ok               # false if the watchdog considers the link stale

# OSOYOO car specific, but kept generic-named so other robots can reuse:
float32 obstacle_distance_m   # ultrasonic sensor reading, -1 if not available
bool[5] line_tracking_sensors # 5-channel IR line-tracking array, unused=false

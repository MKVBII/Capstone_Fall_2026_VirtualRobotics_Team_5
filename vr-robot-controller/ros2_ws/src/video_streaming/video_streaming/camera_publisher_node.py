"""Captures the OSOYOO car's CSI camera and streams it to the VR client.

Confirmed from OSOYOO's hardware (docs/architecture.md section 5): the
camera is a CSI ribbon camera, not USB — so this uses picamera2/libcamera,
not OpenCV's generic v4l2 capture path.

This is deliberately NOT a rosbridge/ROS topic for the actual video frames
(JSON-over-WebSocket is too slow/heavy for live video) — only status about
the stream (e.g. "streaming"/"stopped") goes through ROS. The frames
themselves go over a separate WebRTC or RTSP channel directly to the
headset.

TODO:
  * Pick WebRTC vs RTSP (see docs/architecture.md open decisions).
  * Implement the picamera2 capture loop and the chosen streaming pipeline.
"""
import rclpy
from rclpy.node import Node


class CameraPublisherNode(Node):
    def __init__(self):
        super().__init__('camera_publisher')
        # TODO: initialize picamera2, start the WebRTC/RTSP pipeline.
        self.get_logger().info('Camera publisher started (stub — see TODOs).')


def main(args=None):
    rclpy.init(args=args)
    node = CameraPublisherNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

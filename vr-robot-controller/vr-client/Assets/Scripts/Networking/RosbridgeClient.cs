using UnityEngine;

namespace VrRobotController.Networking
{
    /// <summary>
    /// WebSocket client implementing the rosbridge v2 protocol (JSON over
    /// WebSocket, default port 9090 — see docs/architecture.md). This is
    /// the ONLY class that should open the socket; everything else in the
    /// VR client talks to this, not to a raw WebSocket.
    ///
    /// TODO: pick a WebSocket library (e.g. NativeWebSocket, works well
    /// with Quest/Android builds), implement Connect/Advertise/Publish/
    /// Subscribe per the rosbridge protocol spec, and surface connection
    /// state for the UI/ConnectionMenu.
    /// </summary>
    public class RosbridgeClient : MonoBehaviour
    {
        [SerializeField] private string rosbridgeHost = "192.168.1.X"; // Pi's IP
        [SerializeField] private int rosbridgePort = 9090;

        public void Connect()
        {
            // TODO
        }

        public void PublishCmdVel(float linearX, float angularZ)
        {
            // TODO: serialize as geometry_msgs/Twist and publish to /cmd_vel
        }

        public void SubscribeToRobotStatus()
        {
            // TODO: subscribe to /robot/status (RobotStatus), forward
            // parsed messages to Telemetry/RobotStatusHUD
        }
    }
}

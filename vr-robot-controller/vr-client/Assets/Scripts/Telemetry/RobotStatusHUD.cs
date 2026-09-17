using UnityEngine;
using VrRobotController.Networking;

namespace VrRobotController.Telemetry
{
    /// <summary>
    /// Displays RobotStatus (battery, link health, ultrasonic distance,
    /// line-tracking state) in the headset UI. Fed by
    /// RosbridgeClient.SubscribeToRobotStatus().
    ///
    /// TODO: build the actual world-space/UI canvas once the UI style is
    /// decided; this is just the data-binding stub for now.
    /// </summary>
    public class RobotStatusHUD : MonoBehaviour
    {
        public void OnStatusReceived(RobotStatusMsg status)
        {
            // TODO: update UI text/gauges from status fields
        }
    }
}

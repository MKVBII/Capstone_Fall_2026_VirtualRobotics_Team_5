using UnityEngine;

namespace VrRobotController.Input
{
    /// <summary>
    /// Reads Quest controller (and eventually hand-tracking) input via the
    /// XR Interaction Toolkit input actions and converts it into outgoing
    /// commands matching the shared ROS 2 contract
    /// (docs/message_contracts.md): linear.x/angular.z for /cmd_vel, plus
    /// whatever extra fields TeleopCommand ends up needing.
    ///
    /// TODO: wire up XR Interaction Toolkit's InputActionReferences for the
    /// thumbstick (drive) and buttons (mode switches), and call into
    /// Networking/RosbridgeClient to publish.
    /// </summary>
    public class ControllerInputMapper : MonoBehaviour
    {
        // TODO: [SerializeField] private InputActionReference driveAxis;

        private void Update()
        {
            // TODO: read thumbstick axis, convert to (linearX, angularZ),
            // and forward to RosbridgeClient.PublishCmdVel(...)
        }
    }
}

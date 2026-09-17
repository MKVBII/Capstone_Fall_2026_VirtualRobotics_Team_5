namespace VrRobotController.UI
{
    /// <summary>
    /// Placeholder for future multi-robot support. With only the OSOYOO car
    /// as a target for now, this can be a no-op / single fixed entry — but
    /// the shared message contract means the VR client itself doesn't need
    /// robot-specific logic when a second robot (adapter_arm, etc.) is
    /// added later, so this stays here as the natural extension point.
    /// </summary>
    public class RobotSelector
    {
        // TODO: implement once there is more than one robot adapter to pick from.
    }
}

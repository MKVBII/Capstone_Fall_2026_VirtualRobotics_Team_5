namespace VrRobotController.Networking
{
    /// <summary>
    /// Plain C# structs mirroring the ROS 2 messages defined in
    /// ros2_ws/src/universal_controller_interface/msg/*.msg, for
    /// JSON (de)serialization over the rosbridge connection.
    ///
    /// TODO: keep these in sync by hand with the .msg files until/unless a
    /// codegen step is set up. This is the most likely source of drift in
    /// the project — check both sides when changing the contract.
    /// </summary>
    [System.Serializable]
    public class TwistMsg
    {
        public Vector3Msg linear;
        public Vector3Msg angular;
    }

    [System.Serializable]
    public class Vector3Msg
    {
        public double x;
        public double y;
        public double z;
    }

    [System.Serializable]
    public class RobotStatusMsg
    {
        public float battery_voltage;
        public bool link_ok;
        public float obstacle_distance_m;
        public bool[] line_tracking_sensors;
    }
}

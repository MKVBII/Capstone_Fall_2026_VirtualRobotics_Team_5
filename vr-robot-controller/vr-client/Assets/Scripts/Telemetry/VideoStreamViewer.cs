using UnityEngine;

namespace VrRobotController.Telemetry
{
    /// <summary>
    /// Renders the robot's CSI camera feed, delivered via WebRTC or RTSP
    /// (NOT through rosbridge — see docs/architecture.md on why video is a
    /// separate channel from control/status).
    ///
    /// TODO: pick a WebRTC-for-Unity plugin (or an RTSP player) once
    /// pi_setup/video_streaming settles on a protocol, and render frames
    /// onto a world-space quad/canvas here.
    /// </summary>
    public class VideoStreamViewer : MonoBehaviour
    {
        // TODO
    }
}

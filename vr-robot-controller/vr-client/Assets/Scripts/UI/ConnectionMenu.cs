using UnityEngine;
using VrRobotController.Networking;

namespace VrRobotController.UI
{
    /// <summary>
    /// Entry-point menu: enter/confirm the Pi's rosbridge address and
    /// connect before driving. Shows connection state from RosbridgeClient.
    ///
    /// TODO: build the actual menu UI; this is the data/logic stub.
    /// </summary>
    public class ConnectionMenu : MonoBehaviour
    {
        [SerializeField] private RosbridgeClient rosbridgeClient;

        public void OnConnectButtonPressed()
        {
            rosbridgeClient?.Connect();
        }
    }
}

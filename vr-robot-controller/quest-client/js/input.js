/**
 * Reads Quest 3 controller thumbstick axes and headset yaw each XR frame.
 * Sends raw values to the Pi — deadzone/curve/mixing happens server-side
 * (pi-server/mapping.py), so this file stays dumb on purpose.
 *
 * Axis layout follows the standard "Mode 2" convention used across radio
 * control and drone flying, since the whole point of this controller is
 * to work for wheeled AND flying robots with the same input scheme:
 *
 *   left stick  X -> yaw   (turn / yaw rate)
 *   left stick  Y -> z     (throttle / vertical)
 *   right stick X -> x     (strafe / roll)
 *   right stick Y -> y     (forward-back / pitch)
 *
 * A wheeled robot's driver only reads y and yaw (see
 * drivers/osoyoo_car_driver.py) and ignores x/z — that's expected.
 */
class ControllerInput {
  constructor() {
    this._initialHeadYawDeg = null;
  }

  /**
   * frame: XRFrame, refSpace: XRReferenceSpace, session: XRSession
   * Returns { x, y, z, yaw, headYaw } or null if not enough data is
   * available yet this frame.
   */
  read(frame, refSpace, session) {
    const pose = frame.getViewerPose(refSpace);
    if (!pose) return null;

    const headYaw = this._extractYawDeg(pose.transform.orientation);

    let x = 0, y = 0, z = 0, yaw = 0;
    for (const source of session.inputSources) {
      if (!source.gamepad) continue;
      const axes = source.gamepad.axes; // Quest Touch: [touchpadX, touchpadY, thumbstickX, thumbstickY]
      const stickX = axes.length >= 4 ? axes[2] : axes[0];
      const stickY = axes.length >= 4 ? axes[3] : axes[1];

      if (source.handedness === "left") {
        yaw = stickX ?? 0;
        z = -(stickY ?? 0); // invert: pushing up should be positive
      } else if (source.handedness === "right") {
        x = stickX ?? 0;
        y = -(stickY ?? 0); // invert: pushing forward should be positive
      }
    }

    return { x, y, z, yaw, headYaw };
  }

  _extractYawDeg(quaternion) {
    // Standard quaternion -> yaw (Y-axis rotation) extraction.
    const { x, y, z, w } = quaternion;
    const siny_cosp = 2 * (w * y + x * z);
    const cosy_cosp = 1 - 2 * (y * y + z * z);
    const yawRad = Math.atan2(siny_cosp, cosy_cosp);
    let yawDeg = (yawRad * 180) / Math.PI;

    if (this._initialHeadYawDeg === null) {
      this._initialHeadYawDeg = yawDeg;
    }
    // Report yaw relative to where the headset was facing when the
    // session started, not absolute world yaw.
    return yawDeg - this._initialHeadYawDeg;
  }
}

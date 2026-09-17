/**
 * Renders the robot's video stream on a quad in front of the user.
 *
 * Uses a plain HTML <video> element pointed at the streaming server's HLS
 * output (see streaming/ — mediamtx serves this with no custom code) as
 * a Three.js VideoTexture. Simple and higher-latency (~2-6s with HLS);
 * see docs/architecture.md for the WebRTC/WHEP upgrade path if that
 * latency turns out to matter for driving by feel.
 */
class VideoPanel {
  constructor(streamUrl, scene) {
    this.videoEl = document.createElement("video");
    this.videoEl.src = streamUrl;
    this.videoEl.crossOrigin = "anonymous";
    this.videoEl.loop = true;
    this.videoEl.muted = true;
    this.videoEl.playsInline = true;

    const texture = new THREE.VideoTexture(this.videoEl);
    texture.colorSpace = THREE.SRGBColorSpace;

    const geometry = new THREE.PlaneGeometry(1.6, 0.9); // 16:9 panel, ~meters
    const material = new THREE.MeshBasicMaterial({ map: texture });
    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.position.set(0, 1.4, -2); // 2m in front, roughly eye height
    scene.add(this.mesh);
  }

  start() {
    // Playback must be started from a user gesture on most browsers —
    // call this from the "Enter VR" button handler, not on page load.
    this.videoEl.play().catch((err) => {
      console.warn("Video autoplay/play() failed, will retry on next gesture:", err);
    });
  }
}

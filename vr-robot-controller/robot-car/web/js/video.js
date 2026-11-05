/*
  video.js - the plain video page (pages/video.html).
  Fills in the link to the headset page, and makes a tap on the video
  toggle full screen.
*/

// Link to the begin / headset page, built from whatever address reached this page.
var xr = document.getElementById("xr");
xr.href = xr.textContent = location.origin + "/begin";

// Tap/click the video: full screen (hides the browser's address bar).
// Tap again to leave. Browsers only allow this after a tap or click.
document.querySelector("img").addEventListener("click", function () {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(function () {});
});

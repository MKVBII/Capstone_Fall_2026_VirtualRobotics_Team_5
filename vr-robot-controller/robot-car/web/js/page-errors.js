/*
  page-errors.js - shows problems ON the headset page.

  The Quest browser has no easy developer console, so if something goes
  wrong (a file fails to load, the 3D code crashes), this writes the reason
  under the Enter button instead of leaving a silent, broken page.

  It's a plain script (not a module) loaded before drive.js, so it still
  runs even if drive.js or the 3D library can't load.
*/

/**
 * Disable the Enter button and show `text` under it.
 * @param {string} text  what went wrong, in plain words
 */
function showProblem(text) {
  var m = document.getElementById("msg"), b = document.getElementById("enter");
  b.textContent = "Problem - see below";
  b.disabled = true;
  m.textContent = "Problem: " + text;
}

// Any uncaught error, including a <script> or module that fails to load.
// (`true` = also catch errors from loading files, not only from running code.)
window.addEventListener("error", function (e) {
  showProblem(e.message || "a file failed to load - most likely the 3D library. " +
              "Copy the whole robot-car folder (including web/) to the Pi again.");
}, true);

// Errors inside async code (e.g. a failed fetch) that nothing else caught.
window.addEventListener("unhandledrejection", function (e) { showProblem(String(e.reason)); });

// If drive.js hasn't replaced "Checking headset..." after 8 seconds, it
// never started - almost always because the 3D library didn't load.
setTimeout(function () {
  if (document.getElementById("enter").textContent === "Checking headset...")
    showProblem("the 3D library (/lib/three.module.min.js) didn't load. " +
                "Check that the web/lib folder was copied to the Pi.");
}, 8000);

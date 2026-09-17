# vr-client_tests

Unity PlayMode/EditMode tests for the VR client — primarily
`Scripts/Input` (controller → command mapping) and `Scripts/Networking`
(rosbridge message serialization).

TODO: this needs to live inside `vr-client/Assets/Tests/` for Unity's Test
Runner to discover it (Unity doesn't run tests from outside the project's
Assets folder). This top-level `tests/vr_client_tests/` is a placeholder —
either move the real tests into `vr-client/Assets/Tests/` once written, or
keep this folder as docs/notes about what's covered and link to that path.

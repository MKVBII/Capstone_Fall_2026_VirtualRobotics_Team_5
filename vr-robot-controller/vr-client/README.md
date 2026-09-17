# vr-client

Unity project for the Meta Quest app. Open this folder with Unity Hub
(Unity 6 LTS or 2022 LTS — see docs/architecture.md for the tech stack).

- `Assets/Scripts/Input/` — maps Quest controller/hand input to outgoing commands
- `Assets/Scripts/Networking/` — rosbridge WebSocket client + JSON (de)serialization
- `Assets/Scripts/Telemetry/` — robot status HUD, video stream viewer
- `Assets/Scripts/UI/` — connection screen, robot selector
- `Assets/XR/` — OpenXR / XR Interaction Toolkit rig setup
- `Assets/Scenes/MainTeleop.unity` — main scene (create in-editor; not included as a text file)

This folder currently only has script skeletons — the actual `.unity` scene,
prefabs, and Unity-generated project files (Library/, Temp/, etc., see
.gitignore) are created by opening the project in the Unity Editor.

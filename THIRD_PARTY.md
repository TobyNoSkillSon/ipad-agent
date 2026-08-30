# Third-party components

The V1 Python runtime has no third-party package dependency. This repository does not vendor Apple, Appium, XCUITest Driver, or WebDriverAgent code.

- [Xcode](https://developer.apple.com/xcode/) supplies CoreDevice, `devicectl`, XCTest, SDKs, signing, device support, Swift, and the system frameworks used by the AirDrop helper. Apple's agreements govern those components; this project does not redistribute them.
- [Appium](https://github.com/appium/appium), Apache-2.0, runs the loopback automation server used for short Settings navigation sessions. Host setup installs the pinned package below project-owned `.runtime/node`.
- [Appium XCUITest Driver](https://github.com/appium/appium-xcuitest-driver), Apache-2.0, supplies physical-device UI automation and WebDriverAgent source. Appium keeps the driver in project-owned `.runtime/appium-home`.
- WebDriverAgent includes upstream BSD-licensed components. This project builds and signs it locally through XCUITest Driver; it neither forks nor bundles WDA.

The project-owned AirDrop helper uses macOS `NSSSharingService`; it adds no external Swift dependency. Safari, Preview, Books, Files, Settings, Clock, App Store, and Apple Maps are Apple applications governed by the applicable Apple terms. Brave is optional third-party software and is neither installed nor redistributed here.

A distributor who bundles npm dependencies must preserve their notices and audit the resulting dependency tree. See [`DEPENDENCIES.md`](DEPENDENCIES.md) for pinned versions and ownership, and [`SECURITY.md`](SECURITY.md) for runtime trust boundaries.

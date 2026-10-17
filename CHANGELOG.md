# Changelog

Versions follow [Semantic Versioning](https://semver.org/): MAJOR = needs another Hotone firmware version or breaks
settings, MINOR = a new feature or option, PATCH = a fix. Builds that are not released carry `-dev`.

## 1.0.0 (2026-10-17)
- Footswitch teal light (preset mode, and the looper's drum-machine slot while the drums play) off or white, chosen
  when the file is made.
- GLOBAL > About shows `V2.2 + Pitik 1.0.0 <build hash>` (off `08dd891c`, white `4f2770aa`). The Ampero Editor still
  sees V2.2.
- Browser page (runs locally, no network) and command line (`node patcher.js`), same code and same output.
- Input: Hotone's zip as downloaded, or the `Ampero Mini_firmware_V2.2.bin` inside it (sha256 `2928e3ca...6f7c`, the
  gate for both). For Hotone firmware V2.2 only.
- Output sha256: off `d78cfe47c8acf35ff7e15a3e56b844ae1ebfe4cd8d42d43f112a0438ebf3fae6`, white
  `60bd65ac01a432b2c2d1777d840aae28f26c03d82ad7c33ed24b2d4e37022bf2` (clang 22.1.8).

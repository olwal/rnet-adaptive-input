# Builds and releases

How the standalone binaries are produced, how to publish one, and how to check
a build on a platform you do not have.

## What a release contains

One executable per platform, each around 8 MB, bundling `rnet`, `scope`, `hid`
and pyserial. No Python installation is needed to run them.

| Platform | Asset |
|---|---|
| Windows | `rnet-windows-x64.exe` |
| macOS, Apple silicon | `rnet-macos-arm64.tar.gz` |
| macOS, Intel | `rnet-macos-x64.tar.gz` |
| Linux | `rnet-linux-x64.tar.gz` |

The marble game is **not** bundled. It needs raylib, numpy and scipy, which
would take the download past 150 MB for something most people will not run, so
`rnet demo` in a packaged build reports that it needs a Python install. Run the
game from a clone instead.

Unix builds ship as tarballs rather than bare binaries because both `zip` and
GitHub's `upload-artifact` drop the executable bit.

## What the binary can and cannot do

Run from a clone of this repository, it behaves exactly like `python
tools/rnet.py`: it finds the project and uses `tools/board.json`.

Run from anywhere else there are no sketch sources, so:

- **Works**: `scope`, `hid`, `monitor`, `boards`, `config`, `doctor`
- **Refuses, with an explanation**: `build`, `upload`, `flash`, `run`

Configuration then lives in the per-user location rather than in the project:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\rnet\board.json` |
| macOS | `~/Library/Application Support/rnet/board.json` |
| Linux | `$XDG_CONFIG_HOME/rnet/board.json`, or `~/.config/rnet/` |

This split exists because a frozen build cannot use `__file__` to locate
anything. PyInstaller unpacks to a temporary directory, so a path derived from
it resolves inside the system temp folder, and any config written there is lost
between runs. The project root is therefore discovered by walking up from the
working directory instead.

## Building locally

```
python -m pip install pyinstaller pyserial
python -m PyInstaller packaging/rnet.spec --distpath packaging/dist
```

`packaging/rnet.spec` names `scope`, `hid` and `rnetport` as hidden imports,
because `rnet` reaches them through `importlib` and static analysis cannot see
them. It excludes numpy, scipy, pygame, raylib and friends. UPX compression is
off deliberately: it saves a couple of megabytes and is a reliable way to get
flagged by antivirus, which is already a problem for unsigned binaries.

## Publishing a release

The workflow is `.github/workflows/release.yml`. It needs no secrets; the
automatic `GITHUB_TOKEN` and the `contents: write` permission declared in the
workflow are enough.

**1. Dry run first.** Actions tab, *release* workflow, *Run workflow*. This
builds all four platforms and uploads them as workflow artifacts, but skips
publishing, because the release job only runs for a tag. Worth doing before a
first release: a failed tagged run means deleting the tag and starting again.

**2. Tag and push.**

```
git tag v0.1.0
git push origin v0.1.0
```

That is the entire trigger. Any tag matching `v*` starts it.

**3. Watch it.** Four build jobs run in parallel, each installing PyInstaller,
building from the spec, and running `rnet doctor` on the result as a smoke
test. `doctor` exercises the pyserial import and port enumeration and returns 0
with no board attached, which catches the failure that matters: a binary that
builds but cannot import anything.

**4. The release appears** under Releases with generated notes and the four
assets attached.

To withdraw one: delete the release in the web UI, then
`git push --delete origin v0.1.0` and `git tag -d v0.1.0`.

Keep `__version__` in `tools/rnet.py` in step with the tag. `rnet --version`
prints it along with the platform, which is what you want at the top of a bug
report.

## Verifying a build on a platform you do not have

The macOS and Linux binaries are built and smoke-tested in CI, but CI has no
joystick attached, so the hardware paths are unverified. If someone else has a
board, this is the sequence worth asking them to run.

```
./rnet --version
./rnet doctor
```

`doctor` should report the platform, find pyserial, and list the serial ports.
With the board plugged in, one of them should show VID `16C0` and be marked as
PJRC, and *resolved port* should name it.

```
./rnet scope --sample 5
```

Five lines of telemetry. If it reports "sending data, but none of it is
joystick telemetry", the port is right and the firmware is not the one it
expects. If it reports nothing received, the port is wrong.

```
./rnet hid get
./rnet hid mode mouse      # cursor should move
./rnet hid park
```

Then the parts CI cannot cover at all:

```
./rnet boards              # should identify the Teensy and its FQBN
./rnet flash --hid         # only from a clone
```

On Linux, `flash` needs PJRC's udev rules installed or the uploader cannot open
the device.

Useful things for a tester to report back: the output of `rnet --version` and
`rnet doctor`, what the serial port is called, and whether Gatekeeper or
SmartScreen blocked the binary.

## Signing

The binaries are unsigned. Windows SmartScreen warns on first run, and macOS
refuses until the quarantine flag is cleared:

```
xattr -d com.apple.quarantine rnet
```

Fixing this properly needs a code-signing certificate on each platform, plus
notarisation on macOS.

---

[Back to the README](../README.md)

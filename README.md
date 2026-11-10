# FitGirlWine

**English** | [Português (Brasil)](README.pt-BR.md)

Extracts FitGirl repacks on Linux without running `setup.exe`.

Point it at the repack folder and it extracts. There is nothing to analyse,
configure, compile or install first.

## How to use it — from scratch

**1. Install Wine** from your distribution. You also need Python 3.12 or
newer, which most current distributions already ship.

**2. Download the project.** Either the GitHub ZIP, or:

```bash
git clone https://github.com/AdaLoveLacer/Easy-FitGirl-Linux-install-x86-x64.git ~/FitGirlWine
```

The trailing `~/FitGirlWine` only gives the folder a short name; without it,
the clone creates a folder named after the long repository name.

> In the commands below, **`~/FitGirlWine` is wherever you downloaded the
> project**. If you already have it somewhere else, use that path instead —
> for example `~/Documents/FitGirlWine/fitgirl`.

**3. Enter the repack folder** — the one holding `setup.exe` next to the
`fg-01.bin`, `fg-02.bin` volumes:

```bash
cd "/mnt/games/Game Name [FitGirl Repack]"
```

**4. Call the extractor:**

```bash
~/FitGirlWine/fitgirl
```

That's it. If you would rather not enter the folder, pass it as an argument:

```bash
~/FitGirlWine/fitgirl "/mnt/games/Game Name [FitGirl Repack]"
```

If it stops midway — power cut, you cancelled, anything — run the same
command again and it continues where it left off.

If something does not work, `~/FitGirlWine/fitgirl doctor` reports what your
system is missing.

### To type just `fitgirl`

Optional, only to avoid repeating the path:

```bash
mkdir -p ~/.local/bin && ln -s ~/FitGirlWine/fitgirl ~/.local/bin/fitgirl
```

If `~/.local/bin` is already on your `PATH` — it is on most distributions —
`fitgirl` then works from any folder.

## What happens when you run it

The tool walks you through everything in the terminal, in this order:

| Question | What Enter does |
|---|---|
| Interface language | picks Portuguese |
| Where to install | accepts the first disk on the list |
| Game languages and optional content | keeps the repack's default for each item |
| Limit CPU and memory manually | answers "no": the tool tunes itself |
| Review and start | **starts extracting** |

So you can go through the whole flow pressing only Enter — bearing in mind
that the last Enter is what starts the work. Until then, nothing is written
to disk.

Two exceptions to "Enter accepts": if no writable disk is detected, or if the
chosen destination fails validation, it asks for a full path instead, and
there is no default to accept.

For scripted runs, `FITGIRL_LANGUAGE=en` or `FITGIRL_LANGUAGE=pt` skips the
language question.

## Requirements

- Linux x86-64 with glibc 2.38 or newer
- Python 3.12 or newer
- Wine or Proton installed on the system

Nothing else needs building: the extraction programs ship with the project in
`libexec/`. To check your system:

```bash
./fitgirl doctor
```

## What it does, and what it does not

It extracts the game files and checks the result against the
`_Redist/fitgirl.md5` manifest FitGirl ships inside the repack. Installation
is resumable: if it stops midway, running it again continues where it left off.

It does **not** run `setup.exe`, create shortcuts, touch the Wine registry or
configure the game to launch. Its job ends at extracted, verified files.

## If a repack is refused

The tool reads the step structure from inside the installer itself. Some
installers do things it cannot yet reproduce safely — in that case it stops
before writing anything to disk and tells you what it found, pointing at a
report.

This is the exception, and it means neither your system nor your download is
broken. When it happens, that report is what helps fix the tool.

## Repository map

To **use** it, only these matter:

| Path | What it is |
|---|---|
| `fitgirl` | the executable; this is what you call |
| `src/` | the tool's code |
| `libexec/` | extraction programs, shipped ready to run |
| `manifests/` | installation plans already reviewed |

Everything else exists to **maintain and audit** the tool, and is not needed
to extract anything:

| Path | What it is |
|---|---|
| `tools/` | build, packaging and installer-analysis scripts |
| `tests/` | automated suite |
| `docs/` | architecture, validation and open-work documentation |
| `evidence/` | records of validations run against real repacks |
| `third_party/` | licenses and corresponding sources of third-party components |
| `legacy/` | preserved older material |

Static installer analysis (`tools/bootstrap-analysis.sh`,
[docs/ANALYSIS_TOOLS.md](docs/ANALYSIS_TOOLS.md), [docs/PLAN_AUDIT.md](docs/PLAN_AUDIT.md))
exists to **build and fix the tool**. Anyone who just wants to extract a
repack needs none of it.

## Build the standalone package

For maintenance, not for use:

```bash
./tools/package-release.sh
```

The ZIP is written to `dist/FitGirlInstaller-Linux-x86_64.zip` with the
launcher, extraction libraries, license notices and corresponding third-party
sources. Wine is not bundled.

## License

Original project material is released under [0BSD](LICENSE). Third-party
components retain their own licenses; see
[third-party notices](docs/THIRD_PARTY.md).

# FitGirlWine

**English** | [Português (Brasil)](README.pt-BR.md)

FitGirlWine is a Linux command-line tool that extracts supported FitGirl repacks without running `setup.exe`. It accepts only repacks with an audited installation plan; unknown or unproven plans are refused.

## Quick start

```bash
./fitgirl "/path/to/repack"
```

Choose the interface language when prompted. For scripted runs, set `FITGIRL_LANGUAGE=en` or `FITGIRL_LANGUAGE=pt`.

## Requirements

- Linux x86-64 with glibc 2.38 or newer
- Python 3.12 or newer
- Wine or compatible Proton installed on the system
- Compatible system libraries and standard Linux command-line tools

Run `./fitgirl doctor` to inspect the current system requirements.

## Build a standalone package

```bash
./tools/package-release.sh
```

The ZIP is written to `dist/FitGirlInstaller-Linux-x86_64.zip`. It includes the launcher, required extraction libraries, license notices, and corresponding third-party source code. Wine is not bundled.

## License

Original project material is released under [0BSD](LICENSE). Third-party components retain their own licenses; see [third-party notices](docs/THIRD_PARTY.md).

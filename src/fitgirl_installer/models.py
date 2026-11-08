"""Types shared by more than one area of the installer."""


class InstallerError(RuntimeError):
    """A refusal or failure the installer reports to the user and stops on."""

import os
import sys


def resource_path(
    relative_path,
):
    """
    Resolve a bundled application resource.

    Works during normal development and from a
    PyInstaller-built executable.
    """

    if hasattr(
        sys,
        "_MEIPASS",
    ):
        base_path = sys._MEIPASS

    else:
        base_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
            )
        )

    return os.path.join(
        base_path,
        relative_path,
    )
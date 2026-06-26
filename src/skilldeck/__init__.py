"""skilldeck: agent-agnostic skills for coding assistants."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("skilldeck")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"

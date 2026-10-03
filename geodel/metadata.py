"""Shared packaged plugin version for requests and lifecycle."""
from configparser import ConfigParser
from pathlib import Path

_metadata = ConfigParser()
_metadata.read(Path(__file__).with_name("metadata.txt"))
PLUGIN_VERSION = _metadata["general"]["version"]

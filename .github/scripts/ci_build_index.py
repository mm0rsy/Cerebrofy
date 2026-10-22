"""Build the index for CLI-gate runs with a stub embedder.

`cerebrofy build` downloads and runs an ONNX embedding model. The CLI gates
only exercise the commands that read the index, so a zero-vector embedder
keeps the job fast and offline. Kept as a file rather than an inline heredoc
so the step runs unchanged on bash and PowerShell.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.embedder.base import Embedder

DIM = 768


class _FakeEmbedder(Embedder):
    @property
    def dim(self) -> int:
        return DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * DIM for _ in texts]


def main_entry() -> int:
    runner = CliRunner()
    with patch(
        "cerebrofy.commands.build.get_embedder", return_value=_FakeEmbedder()
    ):
        result = runner.invoke(main, ["build"])
    if result.exit_code != 0:
        print(result.output, file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main_entry())

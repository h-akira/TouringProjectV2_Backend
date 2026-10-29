"""The layers point one way: handlers use lib, never the reverse."""
import pathlib

LIB = pathlib.Path(__file__).resolve().parent.parent / "src" / "lib"


def test_lib_never_imports_handlers():
    offenders = [
        f"{path.name}:{number}"
        for path in sorted(LIB.rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if line.lstrip().startswith(("from handlers", "import handlers"))
    ]
    assert offenders == []

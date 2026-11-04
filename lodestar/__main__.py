"""Entry point for `python -m lodestar` and for the PyInstaller build, which runs this file as a plain script."""
if __package__:
    from .cli import main
else:  # frozen exe: no package context, import absolutely
    from lodestar.cli import main

if __name__ == "__main__":
    main()

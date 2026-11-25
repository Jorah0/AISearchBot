"""Entry point for `python -m lodestar` and for the PyInstaller build, which runs this file as a plain script."""
if __package__:
    from .cli import main_hidden
else:  # frozen exe: no package context, import absolutely
    from lodestar.cli import main_hidden

if __name__ == "__main__":
    main_hidden()  # = main(); without a console (pythonw, a hidden restart) output goes to logs/console.log

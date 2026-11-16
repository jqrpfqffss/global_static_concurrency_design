import sys

sys.dont_write_bytecode = True

if __name__ == "__main__":
    from ecra.cli import main

    raise SystemExit(main())

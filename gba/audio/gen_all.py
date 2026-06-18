"""Run every audio generator.

Usage:
  python3 -m audio.gen_all
"""
from . import gen_music, gen_sfx


def main() -> None:
    gen_sfx.main()
    gen_music.main()


if __name__ == "__main__":
    main()

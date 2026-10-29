#!/usr/bin/env python3
"""Открыть видео или звук в QuickTime сразу на нужном месте (Роман, 2026-10-29: «открывай на нужном тайменге
когда вопросы задаешь»). Спрашивая Романа о месте в ролике или образце, открывать файл этим скриптом.

    python3 scripts/open_at.py <файл> <время: 13 | 0:13 | 1:02:03> [--play]

Только macOS. Окно выводится вперёд и стоит на паузе на этом месте; --play сразу запускает воспроизведение.
"""
from pathlib import Path
import subprocess
import sys

APPLESCRIPT = '''on run argv
  set f to POSIX file (item 1 of argv)
  set t to (item 2 of argv) as integer
  tell application "QuickTime Player"
    activate
    set d to open f
    delay 0.7
    set current time of d to t
    if (item 3 of argv) is "play" then play d
  end tell
  -- a hidden QuickTime (Cmd-H) keeps the window invisible: Roman, 2026-10-29, «ты его не открыл»
  tell application "System Events" to set visible of process "QuickTime Player" to true
  tell application "QuickTime Player"
    activate
    if (count of windows) is 0 then error "QuickTime не показал окно"
    set miniaturized of window 1 to false
  end tell
end run'''


def seconds(text):
    """«13», «0:13», «1:02:03»; доли секунды отбрасываются (QuickTime получает целые секунды)."""
    parts = text.strip().replace(',', '.').split(':')
    if not 1 <= len(parts) <= 3 or not all(parts):
        raise ValueError(f'время «{text}»: нужно 13, 0:13 или 1:02:03')
    total = 0.0
    for p in parts:
        value = float(p)  # ValueError для «a»
        if value < 0:
            raise ValueError(f'время «{text}» отрицательное')
        total = total*60 + value
    return int(total)


def main(argv):
    args = [a for a in argv if a != '--play']
    if len(args) != 2:
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)
    media = Path(args[0]).expanduser().resolve()
    if not media.is_file():
        raise SystemExit(f'нет файла: {media}')
    subprocess.run(['osascript', '-e', APPLESCRIPT, str(media), str(seconds(args[1])), 'play' if '--play' in argv else 'pause'], check=True)


if __name__ == '__main__':
    main(sys.argv[1:])

#!/usr/bin/env bash
# Demon's Souls native Linux build: the one-click installer window (linux/native/installer.py).
# Gets Tk for Python first when it is missing (one password prompt), then opens the window.
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PY=${PY:-$(command -v python3)}
[ -n "$PY" ] || { echo "Python 3 is needed (python3)."; exit 1; }
if ! "$PY" -c 'import tkinter' 2>/dev/null; then
  . /etc/os-release 2>/dev/null
  case " $ID $ID_LIKE " in
    *" arch "*)                     cmd="pacman -S --needed --noconfirm tk" ;;
    *" debian "*|*" ubuntu "*)      cmd="apt-get install -y python3-tk" ;;
    *" fedora "*|*" rhel "*)        cmd="dnf install -y python3-tkinter" ;;
    *" suse "*|*" opensuse "*)      cmd="zypper install -y python3-tk" ;;
    *) echo "Install Tk for Python (tkinter) with your package manager, then run this again."; exit 1 ;;
  esac
  echo "The installer window needs Tk for Python: sudo $cmd"
  if command -v pkexec >/dev/null; then pkexec $cmd; else sudo $cmd; fi || exit 1
fi
exec "$PY" "$here/installer.py" "$@"

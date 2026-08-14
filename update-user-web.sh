#!/bin/sh

# Keep the per-user static dashboard synchronized at login.
src=/etc/skel/public_html/seff/index.html
dst="$HOME/public_html/seff/index.html"

[ -n "$HOME" ] || exit 0
[ -r "$src" ] || exit 0

mkdir -p "$HOME/public_html/seff" 2>/dev/null || exit 0
chmod 755 "$HOME/public_html" "$HOME/public_html/seff" 2>/dev/null || true

if [ ! -e "$dst" ] || ! cmp -s "$src" "$dst"; then
    cp "$src" "$dst" 2>/dev/null || exit 0
    chmod 644 "$dst" 2>/dev/null || true
fi


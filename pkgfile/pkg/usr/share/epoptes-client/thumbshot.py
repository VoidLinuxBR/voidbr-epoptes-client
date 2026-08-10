#!/usr/bin/python3
# This file is part of Epoptes, https://epoptes.org
# Copyright 2010-2018 the Epoptes team, see AUTHORS.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Create a thumbshot of the current screen.

PATCH (VoidBR): adiciona suporte a Wayland (Hyprland/wlroots, GNOME, KDE
Plasma), mantendo o mesmo protocolo de saida que o epoptes original usa
sobre X11 (cabecalho "rowstride\nWxH\n" + pixels RGB de 8 bits, sem alpha,
linhas alinhadas a 4 bytes) para nao quebrar a compatibilidade com o
servidor (epoptes/ui/gui.py le exatamente esse formato).
"""
import os
import shutil
import subprocess
import sys
import tempfile

from _common import gettext as _

WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY"))


def _which(cmd):
    return shutil.which(cmd) is not None


def _detect_desktop():
    """Melhor palpite sobre o compositor/DE em uso."""
    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        + " "
        + os.environ.get("XDG_SESSION_DESKTOP", "")
        + " "
        + os.environ.get("DESKTOP_SESSION", "")
    ).lower()
    if "gnome" in desktop:
        return "gnome"
    if "kde" in desktop or "plasma" in desktop:
        return "kde"
    # Hyprland, Sway, river, labwc etc. nao usam XDG_CURRENT_DESKTOP
    # de forma consistente; se nao for gnome/kde, tratamos como wlroots.
    return "wlroots"


def _capture_wlroots(png_path):
    """Hyprland, Sway, river, labwc... via wlr-screencopy (protocolo)."""
    if not _which("grim"):
        raise RuntimeError("grim nao encontrado (necessario para wlroots)")
    subprocess.run(["grim", png_path], check=True, timeout=10)


def _capture_gnome(png_path):
    """GNOME/Mutter via a interface D-Bus privada do Shell (sem portal)."""
    if not _which("gdbus"):
        raise RuntimeError("gdbus nao encontrado (necessario para GNOME)")
    subprocess.run(
        [
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell",
            "--object-path", "/org/gnome/Shell/Screenshot",
            "--method", "org.gnome.Shell.Screenshot.Screenshot",
            "true", "false", png_path,
        ],
        check=True, timeout=10, capture_output=True,
    )


def _capture_kde(png_path):
    """KDE Plasma/KWin via spectacle em modo background (sem dialogo)."""
    if not _which("spectacle"):
        raise RuntimeError("spectacle nao encontrado (necessario para KDE)")
    subprocess.run(
        ["spectacle", "-b", "-n", "-o", png_path],
        check=True, timeout=10, capture_output=True,
    )


def _capture_portal_fallback(png_path):
    """
    Ultimo recurso: portal XDG genérico (org.freedesktop.portal.Desktop).
    Pode exibir um dialogo de permissao na primeira vez, dependendo do
    backend de portal instalado. Preferir sempre um dos metodos acima.
    """
    if not _which("gdbus"):
        raise RuntimeError("gdbus nao encontrado")
    subprocess.run(
        [
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.portal.Desktop",
            "--object-path", "/org/freedesktop/portal/desktop",
            "--method", "org.freedesktop.portal.Screenshot.Screenshot",
            "", "{}",
        ],
        check=True, timeout=15, capture_output=True,
    )
    # Nota: essa chamada retorna um "handle" de Request, nao o arquivo
    # diretamente; implementar o loop de resposta via D-Bus signal fica
    # fora do escopo deste fallback simples. Preferir grim/gdbus Shell/
    # spectacle, que escrevem o arquivo direto.
    raise RuntimeError("fallback do portal generico nao implementado")


def _screenshot_wayland_to_png(png_path):
    desktop = _detect_desktop()
    order = {
        "wlroots": [_capture_wlroots, _capture_gnome, _capture_kde],
        "gnome": [_capture_gnome, _capture_wlroots, _capture_kde],
        "kde": [_capture_kde, _capture_wlroots, _capture_gnome],
    }[desktop]

    errors = []
    for method in order:
        try:
            method(png_path)
            if os.path.exists(png_path) and os.path.getsize(png_path) > 0:
                return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{method.__name__}: {exc}")

    raise RuntimeError(
        "Nenhum metodo de captura Wayland funcionou: " + " | ".join(errors)
    )


def thumbshot_wayland(width, height):
    """Captura via Wayland (grim/gdbus/spectacle) e reempacota como o
    epoptes espera (mesmo formato que Gdk.pixbuf_get_from_surface geraria).
    """
    from PIL import Image  # import tardio: so exigido no caminho Wayland

    with tempfile.TemporaryDirectory(prefix="epoptes-thumb-") as tmpdir:
        png_path = os.path.join(tmpdir, "shot.png")
        _screenshot_wayland_to_png(png_path)

        img = Image.open(png_path).convert("RGB")
        img = img.resize((width, height), Image.BILINEAR)

        # GdkPixbuf (Colorspace.RGB, has_alpha=False, 8 bits) alinha cada
        # linha a um multiplo de 4 bytes - replicamos isso manualmente.
        row_bytes = width * 3
        rowstride = (row_bytes + 3) & ~3
        raw = img.tobytes()  # ja vem sem padding, width*height*3 bytes

        if rowstride == row_bytes:
            pixels = raw
        else:
            pad = b"\0" * (rowstride - row_bytes)
            rows = [
                raw[i:i + row_bytes] + pad
                for i in range(0, len(raw), row_bytes)
            ]
            pixels = b"".join(rows)

        return b"%i\n%ix%i\n" % (rowstride, width, height) + pixels


def thumbshot_x11(width, height):
    """Caminho original, inalterado, usado quando WAYLAND_DISPLAY nao
    esta definido (sessao X11/Xorg de verdade)."""
    import cairo
    from gi.repository import Gdk

    root = Gdk.get_default_root_window()
    if root is None:
        raise RuntimeError('Cannot find the root window, is xorg running?')
    geometry = root.get_geometry()
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    ctx = cairo.Context(surface)
    ctx.scale(float(width) / geometry.width, float(height) / geometry.height)
    Gdk.cairo_set_source_window(ctx, root, 0, 0)
    ctx.paint()

    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, width, height)
    rowst = pixbuf.get_rowstride()
    pixels = pixbuf.get_pixels()

    return (b"%i\n%ix%i\n" % (rowst, width, height)
            + pixels
            + b"\0" * (rowst * height - len(pixels)))


def thumbshot(width, height):
    """Return a thumbshot of the current screen as bytes."""
    if WAYLAND:
        return thumbshot_wayland(width, height)
    return thumbshot_x11(width, height)


def main():
    """Run the module from the command line."""
    if len(sys.argv) == 3:
        sys.stdout.buffer.flush()
        sys.stdout.buffer.write(thumbshot(int(sys.argv[1]), int(sys.argv[2])))
        sys.stdout.buffer.flush()
    else:
        print(_("Usage: {} width height").format(
            os.path.basename(__file__)), file=sys.stderr)
        exit(1)


if __name__ == '__main__':
    main()

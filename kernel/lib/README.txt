libfribidi-0.dll
================

GNU FriBiDi 1.0.16, 64-bit Windows build (copied from the GIMP 3 installation).
Pillow needs it on Windows to enable its Raqm text layout (HarfBuzz shaping +
bidi), which image_engine.py uses to render Kurdish/Persian/Arabic headlines.
common.py adds this folder to PATH at startup; on Linux/Termux the system
fribidi library is used instead and this folder is ignored.

License: LGPL-2.1-or-later. Source and license text:
https://github.com/fribidi/fribidi

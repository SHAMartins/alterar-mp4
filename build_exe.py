"""
Gera o executável CompactadorDeVideos.exe (com o FFmpeg embutido).

Uso (uma única vez cria o ambiente de build):
    python -m venv .venv-build
    .venv-build\\Scripts\\python.exe -m pip install pyinstaller imageio-ffmpeg tkinterdnd2
    .venv-build\\Scripts\\python.exe build_exe.py

O resultado fica em dist\\CompactadorDeVideos.exe.
"""

import os
import shutil
import sys
from pathlib import Path

# Python 3.13.0 em venv não encontra o Tcl/Tk sozinho; apontamos para a instalação base.
_tcl = Path(sys.base_prefix) / "tcl"
os.environ.setdefault("TCL_LIBRARY", str(_tcl / "tcl8.6"))
os.environ.setdefault("TK_LIBRARY", str(_tcl / "tk8.6"))

import imageio_ffmpeg
import PyInstaller.__main__

raiz = Path(__file__).resolve().parent
build = raiz / "build"
build.mkdir(exist_ok=True)

# O imageio-ffmpeg traz um FFmpeg estático (com libx264 e AAC); copiamos com o nome padrão.
ffmpeg = build / "ffmpeg.exe"
shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), ffmpeg)

PyInstaller.__main__.run([
    str(raiz / "interface_compactador.py"),
    "--name", "CompactadorDeVideos",
    "--onefile",
    "--windowed",                         # sem janela de console
    "--noconfirm",
    "--clean",
    "--add-binary", f"{ffmpeg};.",        # vai para a raiz do _MEIPASS
    "--collect-all", "tkinterdnd2",       # arrastar e soltar
    "--distpath", str(raiz / "dist"),
    "--workpath", str(build / "pyinstaller"),
    "--specpath", str(build),
])

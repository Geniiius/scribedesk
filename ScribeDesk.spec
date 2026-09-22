# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Recette de l'exécutable Windows autonome.

    pip install pyinstaller
    pyinstaller --noconfirm ScribeDesk.spec

Produit « dist/ScribeDesk.exe » : un fichier unique embarquant Python, Qt et
ScribeDesk, qui fonctionne sur un poste dépourvu de Python. Il n'embarque en
revanche ni modèle, ni clé d'API : la configuration reste dans le profil de
l'utilisateur et le trousseau du système.

Windows uniquement. PyInstaller ne fabrique pas un exécutable pour un autre
système que celui sur lequel il tourne ; sous Linux, l'application s'installe
depuis les sources.
"""

from PyInstaller.utils.hooks import collect_submodules

# Trois familles d'imports qu'une analyse statique ne peut pas voir, parce que
# les bibliothèques concernées choisissent leur implémentation à l'exécution.
# Sans elles l'exécutable se construit sans erreur, mais échoue à l'usage :
# plus de raccourci global, et plus d'enregistrement de clé d'API.
hiddenimports = [
    "win32ctypes.core",  # socle de l'accès au trousseau Windows
    "pynput.keyboard._win32",  # écoute du raccourci global
    "pynput.mouse._win32",
]
hiddenimports += collect_submodules("keyring.backends")

a = Analysis(
    ["scribedesk_gui.py"],
    # Permet de construire depuis une copie fraîche du dépôt, sans installation
    # préalable du paquet.
    pathex=["src"],
    binaries=[],
    # Les actions livrées sont des fichiers Markdown, chargés à l'exécution
    # depuis le paquet. Omises ici, l'application démarre avec une palette vide.
    datas=[("src/scribedesk/prompts/builtin", "scribedesk/prompts/builtin")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ScribeDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # L'application vit dans le plateau système : une console noire s'ouvrirait
    # derrière elle pendant toute la session.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

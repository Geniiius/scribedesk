# SPDX-License-Identifier: MIT
"""Réglages communs à toute la suite.

Une suite de tests ne doit rien laisser derrière elle, et son résultat ne doit
pas dépendre du poste qui l'exécute. Deux effets de bord y contrevenaient :
`Settings.save()` écrasait les préférences réelles de l'utilisateur, et les
actions personnelles présentes sur la machine se mêlaient à celles du dépôt.
Rediriger le profil vers un dossier jetable supprime les deux.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def profil_isole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirige configuration, historique et actions vers un dossier jetable."""
    monkeypatch.setenv("SCRIBEDESK_HOME", str(tmp_path / "profil"))

# SPDX-License-Identifier: MIT
"""Préférences : aller-retour TOML, tolérance aux fichiers abîmés."""

from __future__ import annotations

from pathlib import Path

import pytest

from scribedesk.config import PrivacyConfig, ProviderConfig, Settings, paths


def test_valeurs_par_defaut_prudentes() -> None:
    """Les réglages livrés doivent être les plus protecteurs."""
    settings = Settings()
    assert settings.provider.key == "ollama", "l'inférence locale est le défaut"
    assert settings.privacy.enabled is True
    assert settings.history.store_text is False, "aucun texte d'usager conservé par défaut"
    assert settings.theme == "dark"


def test_aller_retour_complet(tmp_path: Path) -> None:
    original = Settings(
        provider=ProviderConfig(key="groq", model="m", temperature=0.7, max_tokens=512),
        privacy=PrivacyConfig(enabled=False, rules=("EMAIL", "TEL"), extra_stopwords=("GEODE",)),
        hotkey="ctrl+alt+e",
        streaming=False,
    )
    chemin = original.save(tmp_path / "settings.toml")
    relu = Settings.load(chemin)

    assert relu.provider == original.provider
    assert relu.privacy.rules == ("EMAIL", "TEL")
    assert relu.privacy.extra_stopwords == ("GEODE",)
    assert relu.hotkey == "ctrl+alt+e"
    assert relu.streaming is False


def test_fichier_absent_donne_les_defauts(tmp_path: Path) -> None:
    assert Settings.load(tmp_path / "rien.toml") == Settings()


def test_fichier_corrompu_ne_bloque_pas_le_demarrage(tmp_path: Path) -> None:
    """Perdre ses préférences est ennuyeux ; ne plus pouvoir démarrer l'est plus."""
    abime = tmp_path / "settings.toml"
    abime.write_text("ceci n'est ... pas = du [toml", encoding="utf-8")
    assert Settings.load(abime) == Settings()


def test_champs_inconnus_ignores() -> None:
    """Un fichier écrit par une version plus récente doit rester ouvrable."""
    settings = Settings.from_dict(
        {"hotkey": "ctrl+j", "invente": 1, "provider": {"key": "groq", "futur": True}}
    )
    assert settings.hotkey == "ctrl+j"
    assert settings.provider.key == "groq"


def test_section_de_mauvais_type_ignoree() -> None:
    assert Settings.from_dict({"provider": "pas une table"}).provider == ProviderConfig()


def test_ecriture_atomique_sans_residu(tmp_path: Path) -> None:
    cible = tmp_path / "settings.toml"
    Settings().save(cible)
    assert cible.exists()
    assert not list(tmp_path.glob("*.tmp")), "le fichier temporaire doit être renommé"


def test_valeur_nulle_omise_du_toml() -> None:
    """TOML n'a pas de « null » : la clé doit disparaître, pas valoir ''."""
    rendu = Settings(provider=ProviderConfig(max_tokens=None)).to_toml()
    assert "max_tokens" not in rendu


@pytest.mark.parametrize(
    ("fournisseur", "exempt", "actif", "attendu"),
    [
        ("groq", True, True, True),
        ("ollama", True, True, False),  # local : anonymiser n'apporte rien
        ("ollama", False, True, True),  # exemption désactivée par l'utilisateur
        ("groq", True, False, False),  # anonymisation coupée
    ],
)
def test_politique_d_anonymisation(
    fournisseur: str, exempt: bool, actif: bool, attendu: bool
) -> None:
    settings = Settings(
        provider=ProviderConfig(key=fournisseur),
        privacy=PrivacyConfig(enabled=actif, local_providers_exempt=exempt),
    )
    assert settings.redaction_applies() is attendu


def test_repertoire_force_par_variable_d_environnement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCRIBEDESK_HOME", str(tmp_path))
    emplacements = paths().ensure()
    assert emplacements.config_dir == tmp_path
    assert emplacements.actions_dir.is_dir()


def test_with_provider_ne_modifie_pas_l_original() -> None:
    origine = Settings()
    modifie = origine.with_provider(key="groq")
    assert modifie.provider.key == "groq"
    assert origine.provider.key == "ollama"

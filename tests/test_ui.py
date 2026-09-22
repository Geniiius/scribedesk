# SPDX-License-Identifier: MIT
"""Interface : construction des fenêtres et passerelle asyncio ↔ Qt.

Ces tests tournent sans écran grâce au greffon Qt « offscreen ». Ils ne
vérifient pas l'apparence, mais deux choses qui cassent silencieusement : que
les fenêtres se construisent avec les données réelles du projet, et que les
fragments produits dans le fil asyncio parviennent bien au fil Qt.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="interface graphique non installée")

from PySide6.QtWidgets import QApplication

from scribedesk.config import Settings, paths
from scribedesk.prompts import Action, ActionLibrary, load_library
from scribedesk.ui.bridge import AsyncRunner
from scribedesk.ui.desktop import normalise_hotkey
from scribedesk.ui.popup import PopupWindow
from scribedesk.ui.response import ResponseWindow
from scribedesk.ui.settings import SettingsWindow
from scribedesk.ui.theme import DARK, LIGHT, resolve_theme, stylesheet


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield app  # type: ignore[misc]


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """Isole les préférences et l'historique dans un dossier jetable."""
    monkeypatch.setenv("SCRIBEDESK_HOME", str(tmp_path))


def pump(app: QApplication, predicate, timeout: float = 5.0) -> bool:  # type: ignore[no-untyped-def]
    """Fait tourner la boucle Qt jusqu'à ce que `predicate` soit vrai."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --------------------------------------------------------------------------
# Passerelle
# --------------------------------------------------------------------------


def test_les_fragments_asyncio_parviennent_au_fil_qt(qapp: QApplication) -> None:
    async def generer() -> AsyncIterator[str]:
        for morceau in ("Bon", "jour", " !"):
            yield morceau

    runner = AsyncRunner()
    recus: list[str] = []
    complet: list[str] = []

    handle = runner.run_stream(generer)
    handle.chunk.connect(recus.append)
    handle.finished.connect(complet.append)

    assert pump(qapp, lambda: bool(complet)), "la génération n'a jamais abouti"
    assert recus == ["Bon", "jour", " !"]
    assert complet == ["Bonjour !"]
    runner.stop()


def test_une_erreur_asyncio_devient_un_signal_failed(qapp: QApplication) -> None:
    async def generer() -> AsyncIterator[str]:
        yield "début"
        raise RuntimeError("le fournisseur a lâché")

    runner = AsyncRunner()
    erreurs: list[str] = []
    handle = runner.run_stream(generer)
    handle.failed.connect(erreurs.append)

    assert pump(qapp, lambda: bool(erreurs))
    assert "lâché" in erreurs[0]
    runner.stop()


def test_le_runner_survit_a_plusieurs_generations(qapp: QApplication) -> None:
    """Le fil et la boucle sont réutilisés : c'est ce qui garde les connexions."""

    async def generer() -> AsyncIterator[str]:
        yield "x"

    runner = AsyncRunner()
    for tour in range(3):
        fini: list[str] = []
        # Le handle n'est volontairement pas conservé ici : le runner doit le
        # retenir lui-même le temps de la génération.
        runner.run_stream(generer).finished.connect(fini.append)
        assert pump(qapp, lambda recu=fini: bool(recu)), f"tour {tour} sans résultat"
    runner.stop()


def test_arret_sans_demarrage_ne_leve_pas() -> None:
    AsyncRunner().stop()


def test_une_generation_instantanee_ne_perd_aucun_fragment(qapp: QApplication) -> None:
    """Régression : la coroutine ne doit pas démarrer avant les `connect`.

    Un générateur sans `await` se terminait auparavant pendant que l'appelant
    branchait encore ses signaux, et toute la réponse partait à la poubelle.
    Le cas se produit avec un modèle local ou une erreur immédiate.
    """

    async def instantane() -> AsyncIterator[str]:
        yield "tout"
        yield " de suite"

    runner = AsyncRunner()
    runner.start()

    recus: list[str] = []
    complet: list[str] = []
    handle = runner.run_stream(instantane)
    handle.chunk.connect(recus.append)
    handle.finished.connect(complet.append)

    assert pump(qapp, lambda: bool(complet))
    assert recus == ["tout", " de suite"]
    assert complet == ["tout de suite"]
    runner.stop()


# --------------------------------------------------------------------------
# Fenêtres
# --------------------------------------------------------------------------


def test_le_popup_expose_toutes_les_actions(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QPushButton

    library = load_library()
    popup = PopupWindow(library)

    libelles = {b.text().removesuffix(" ▸") for b in popup.findChildren(QPushButton)}
    for action in library:
        assert action.name in libelles


def test_chaque_action_recoit_sa_teinte_et_son_pictogramme(qapp: QApplication) -> None:
    """Couleur et icône viennent des fichiers d'action, pas du thème.

    Ces deux champs ont longtemps été lus puis ignorés : la grille était grise
    alors que les actions déclaraient déjà leurs couleurs.
    """
    from scribedesk.ui.theme import DARK

    popup = PopupWindow(load_library())
    popup.set_palette(DARK)

    assert popup._buttons, "aucun bouton construit"
    for button, action in popup._buttons:
        teinte = DARK.tint(action.color)
        assert teinte.lower() in button.styleSheet().lower() or _rgb_present(
            teinte, button.styleSheet()
        ), f"{action.name} n'utilise pas sa teinte"
        assert not button.icon().isNull(), f"{action.name} n'a pas de pictogramme"


def _rgb_present(hex_color: str, feuille: str) -> bool:
    """La teinte peut apparaître en « rgba(r, g, b, a) » plutôt qu'en hexadécimal."""
    from PySide6.QtGui import QColor

    couleur = QColor(hex_color)
    return f"{couleur.red()}, {couleur.green()}, {couleur.blue()}" in feuille


def test_les_actions_a_parametres_sont_signalees(qapp: QApplication) -> None:
    popup = PopupWindow(load_library())
    for button, action in popup._buttons:
        assert button.text().endswith(" ▸") is bool(action.parameters), action.name


def test_la_barre_d_etat_montre_le_moteur(qapp: QApplication) -> None:
    popup = PopupWindow(load_library())
    popup.set_engine("Groq", "openai/gpt-oss-120b")
    assert "Groq" in popup._engine_label.text()
    assert "gpt-oss-120b" in popup._engine_label.text()

    popup.set_engine("Ollama (local)", "")
    assert popup._engine_label.text() == "Ollama (local)"


def test_les_pictogrammes_couvrent_les_icones_declarees() -> None:
    """Un nom d'icône inconnu doit donner un repli, jamais une icône vide."""
    from scribedesk.ui.glyphs import GLYPHS, action_icon

    for action in load_library():
        assert action.icon in GLYPHS, f"« {action.icon} » n'a pas de glyphe dédié"
    assert not action_icon("nom-inexistant", "#ff0000").isNull()


def test_le_popup_demande_les_parametres_avant_de_lancer(qapp: QApplication) -> None:
    avec = Action(
        name="Avec",
        instruction="i",
        parameters=(
            __import__("scribedesk.prompts", fromlist=["Parameter"]).Parameter(
                name="ton", label="Ton", choices=("A", "B")
            ),
        ),
    )
    popup = PopupWindow(ActionLibrary([avec]))
    envoyes: list[tuple] = []
    popup.submitted.connect(lambda a, c: envoyes.append((a, c)))

    popup._choose(avec)
    assert not envoyes, "l'action ne doit pas partir avant que les choix soient faits"

    popup._emit_pending()
    assert envoyes and envoyes[0][1] == {"ton": "A"}


def test_action_sans_parametre_part_immediatement(qapp: QApplication) -> None:
    sans = Action(name="Sans", instruction="i")
    popup = PopupWindow(ActionLibrary([sans]))
    envoyes: list[tuple] = []
    popup.submitted.connect(lambda a, c: envoyes.append((a, c)))

    popup._choose(sans)
    assert envoyes == [(sans, {})]


def test_la_fenetre_de_reponse_accumule_les_fragments(qapp: QApplication) -> None:
    window = ResponseWindow()
    window.begin("Relecture")
    for morceau in ("Bon", "jour"):
        window.append(morceau)
    window.finish("Rien masqué.")
    assert window.text() == "Bonjour"


def test_un_echec_conserve_le_texte_deja_recu(qapp: QApplication) -> None:
    """Effacer une réponse partielle sur erreur ferait perdre du travail utile."""
    window = ResponseWindow()
    window.begin("Relecture")
    window.append("Début de réponse")
    window.fail("connexion perdue")
    assert window.text() == "Début de réponse"


# --------------------------------------------------------------------------
# Préférences
# --------------------------------------------------------------------------


def test_les_preferences_font_un_aller_retour(qapp: QApplication) -> None:
    window = SettingsWindow(Settings())
    collecte = window.collect()
    assert collecte.provider.key == "ollama"
    assert collecte.privacy.enabled is True


def test_toutes_les_regles_cochees_valent_none(qapp: QApplication) -> None:
    """« Toutes » doit rester ouvert aux règles ajoutées par une version future."""
    window = SettingsWindow(Settings())
    assert window.collect().privacy.rules is None


def test_decocher_une_regle_produit_une_liste_explicite(qapp: QApplication) -> None:
    from PySide6.QtCore import Qt

    window = SettingsWindow(Settings())
    window._rules.item(0).setCheckState(Qt.CheckState.Unchecked)

    regles = window.collect().privacy.rules
    assert regles is not None
    assert len(regles) == window._rules.count() - 1


def test_les_sigles_maison_sont_lus(qapp: QApplication) -> None:
    window = SettingsWindow(Settings())
    window._stopwords.setText("GEODE, ATLAS ,, SIGMA")
    assert window.collect().privacy.extra_stopwords == ("GEODE", "ATLAS", "SIGMA")


# --------------------------------------------------------------------------
# Thème et raccourci
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("preference", "attendu"),
    [("light", LIGHT), ("dark", DARK), ("sombre", DARK), ("clair", LIGHT)],
)
def test_resolution_du_theme(preference: str, attendu, qapp: QApplication) -> None:  # type: ignore[no-untyped-def]
    assert resolve_theme(preference) is attendu


def test_la_feuille_de_style_utilise_les_couleurs_de_la_palette() -> None:
    rendu = stylesheet(DARK)
    assert DARK.accent in rendu
    assert DARK.surface in rendu
    assert DARK.border in rendu
    # `palette.background` n'y figure plus volontairement : le fond des
    # fenêtres est désormais peint par GradientBackground, pas déclaré en CSS.
    assert "{" not in rendu.replace("{{", "").split("QWidget")[0].strip(" \n")


@pytest.mark.parametrize("palette", [LIGHT, DARK])
def test_chaque_palette_declare_un_degrade_complet(palette) -> None:  # type: ignore[no-untyped-def]
    assert len(palette.gradient) == 3
    for couleur in palette.gradient:
        assert couleur.startswith("#") and len(couleur) == 7, couleur


def test_le_fond_degrade_se_peint_sans_lever(qapp: QApplication) -> None:
    """Le rendu est fait hors écran : un `paintEvent` fautif échouerait ici."""
    from PySide6.QtGui import QColor

    from scribedesk.ui.theme import GradientBackground

    widget = GradientBackground(DARK)
    widget.resize(200, 120)
    image = widget.grab().toImage()

    assert image.width() == 200
    # Le centre doit porter la teinte médiane du dégradé, pas du transparent.
    centre = QColor(image.pixel(100, 60))
    attendu = QColor(DARK.gradient[1])
    assert abs(centre.red() - attendu.red()) < 30, f"{centre.name()} vs {attendu.name()}"


def test_changer_de_palette_redessine_le_fond(qapp: QApplication) -> None:
    from PySide6.QtGui import QColor

    from scribedesk.ui.theme import GradientBackground

    widget = GradientBackground(DARK)
    widget.resize(120, 80)
    sombre = QColor(widget.grab().toImage().pixel(60, 40))

    widget.set_palette(LIGHT)
    clair = QColor(widget.grab().toImage().pixel(60, 40))

    assert clair.lightness() > sombre.lightness()


@pytest.mark.parametrize(
    ("saisi", "attendu"),
    [
        ("ctrl+space", "<ctrl>+<space>"),
        ("ctrl+alt+e", "<ctrl>+<alt>+e"),
        ("ctrl+shift+F5", "<ctrl>+<shift>+<f5>"),
        ("win+j", "<cmd>+j"),
        ("ctrl+Return", "<ctrl>+<enter>"),
    ],
)
def test_traduction_du_raccourci_vers_pynput(saisi: str, attendu: str) -> None:
    assert normalise_hotkey(saisi) == attendu


# --------------------------------------------------------------------------
# Diagnostic
# --------------------------------------------------------------------------


def test_le_journal_est_ecrit_sur_disque(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Sans trace fichier, un arrêt inattendu est indiscernable d'un arrêt voulu.

    L'application vit dans le plateau système : lancée depuis un raccourci,
    elle n'a pas de terminal et tout ce qui part sur stderr est perdu.
    """
    import logging

    from scribedesk.config import paths
    from scribedesk.ui.app import _configure_logging

    monkeypatch.setenv("SCRIBEDESK_HOME", str(tmp_path))
    racine = logging.getLogger()
    anciens = racine.handlers[:]
    try:
        racine.handlers = []
        _configure_logging()
        logging.getLogger("scribedesk.test").info("message de contrôle")
        for handler in racine.handlers:
            handler.flush()

        journal = paths().log_file
        assert journal.exists(), "aucun fichier de journal créé"
        assert "message de contrôle" in journal.read_text(encoding="utf-8")
    finally:
        for handler in racine.handlers:
            handler.close()
        racine.handlers = anciens


def test_le_journal_reste_borne(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Un journal qui grossit sans fin poserait son propre problème."""
    import logging

    from scribedesk.ui.app import _configure_logging

    monkeypatch.setenv("SCRIBEDESK_HOME", str(tmp_path))
    racine = logging.getLogger()
    anciens = racine.handlers[:]
    try:
        racine.handlers = []
        _configure_logging()
        fichiers = [h for h in racine.handlers if hasattr(h, "maxBytes")]
        assert fichiers, "aucun gestionnaire cyclique"
        assert fichiers[0].maxBytes > 0
        assert fichiers[0].backupCount > 0
    finally:
        for handler in racine.handlers:
            handler.close()
        racine.handlers = anciens


# --------------------------------------------------------------------------
# Geste unique
# --------------------------------------------------------------------------


def test_l_action_par_defaut_est_celle_configuree(qapp: QApplication) -> None:
    from scribedesk.ui.app import ScribeDeskApp

    application = ScribeDeskApp.__new__(ScribeDeskApp)
    application._settings = Settings(default_action="Résumé")
    application._engine = type("E", (), {"library": load_library()})()

    trouvee = ScribeDeskApp.default_action(application)
    assert trouvee is not None
    assert trouvee.name == "Résumé"


def test_un_nom_d_action_inconnu_retombe_sur_la_premiere(qapp: QApplication) -> None:
    """Renommer ou traduire une action ne doit pas rendre le raccourci muet."""
    from scribedesk.ui.app import ScribeDeskApp

    application = ScribeDeskApp.__new__(ScribeDeskApp)
    application._settings = Settings(default_action="Action Supprimée")
    bibliotheque = load_library()
    application._engine = type("E", (), {"library": bibliotheque})()

    trouvee = ScribeDeskApp.default_action(application)
    assert trouvee is not None
    assert trouvee is bibliotheque[0]


def test_bibliotheque_vide_ne_leve_pas(qapp: QApplication) -> None:
    from scribedesk.ui.app import ScribeDeskApp

    application = ScribeDeskApp.__new__(ScribeDeskApp)
    application._settings = Settings()
    application._engine = type("E", (), {"library": ActionLibrary([])})()

    assert ScribeDeskApp.default_action(application) is None


def test_le_raccourci_rapide_a_ses_reglages_par_defaut() -> None:
    reglages = Settings()
    assert reglages.quick_hotkey == "ctrl+alt+space"
    assert reglages.quick_hotkey != reglages.hotkey, "les deux raccourcis doivent différer"
    # L'action la plus utilisée dans le relevé d'usage réel.
    assert reglages.default_action == "Relecture et correction"


def test_les_deux_raccourcis_survivent_a_un_aller_retour(tmp_path) -> None:  # type: ignore[no-untyped-def]
    origine = Settings(quick_hotkey="ctrl+alt+r", default_action="Résumé")
    relu = Settings.load(origine.save(tmp_path / "settings.toml"))
    assert relu.quick_hotkey == "ctrl+alt+r"
    assert relu.default_action == "Résumé"


def test_la_pastille_change_d_etat_sans_lever(qapp: QApplication) -> None:
    from scribedesk.ui.theme import DARK
    from scribedesk.ui.toast import Toast

    pastille = Toast(DARK)
    pastille.show_busy("Relecture…")
    assert pastille.isVisible()

    pastille.show_done("Appliqué")
    pastille.show_error("Échec réseau")
    pastille.dismiss()
    assert not pastille.isVisible()


def test_la_pastille_ne_capte_pas_les_clics(qapp: QApplication) -> None:
    """Elle apparaît sous le curseur : elle ne doit rien intercepter."""
    from PySide6.QtCore import Qt

    from scribedesk.ui.theme import DARK
    from scribedesk.ui.toast import Toast

    pastille = Toast(DARK)
    assert pastille.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_la_pause_desactive_les_deux_raccourcis(qapp: QApplication) -> None:
    """Suspendre ne doit rien laisser d'actif.

    Oublier le raccourci rapide laisserait l'outil réécrire la sélection alors
    que l'utilisateur le croit désactivé — le cas exact où il vient de le
    suspendre pour taper autre chose.
    """
    from scribedesk.ui.app import ScribeDeskApp

    class _Faux:
        def __init__(self) -> None:
            self.actif = True

        def stop(self) -> None:
            self.actif = False

        def start(self) -> bool:
            self.actif = True
            return True

    class _Bouton:
        def setText(self, _: str) -> None:  # noqa: N802 - imite l'API Qt
            pass

    application = ScribeDeskApp.__new__(ScribeDeskApp)
    application._hotkey = _Faux()
    application._quick_hotkey = _Faux()
    application._pause_action = _Bouton()

    ScribeDeskApp._toggle_pause(application)
    assert not application._hotkey.actif
    assert not application._quick_hotkey.actif, "le raccourci rapide reste armé"

    ScribeDeskApp._toggle_pause(application)
    assert application._hotkey.actif
    assert application._quick_hotkey.actif


def test_la_palette_se_ferme_en_perdant_le_focus(qapp: QApplication) -> None:
    """Régression : `QDialog` était utilisé sans être importé.

    `event()` s'exécute à chaque perte de focus — le principal mode de
    fermeture de la palette. Un NameError s'y déclenchait donc en usage
    normal, sans qu'aucun test ne le voie.
    """
    from PySide6.QtCore import QEvent

    popup = PopupWindow(load_library())
    popup.show()
    qapp.processEvents()

    popup.event(QEvent(QEvent.Type.WindowDeactivate))
    assert not popup.isVisible()


def test_la_palette_reste_ouverte_derriere_une_boite_de_dialogue(qapp: QApplication) -> None:
    """Ouvrir l'éditeur d'action ne doit pas escamoter la palette qui le porte."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QDialog

    popup = PopupWindow(load_library())
    popup.show()
    qapp.processEvents()

    dialogue = QDialog(popup)
    dialogue.show()
    qapp.processEvents()

    popup.event(QEvent(QEvent.Type.WindowDeactivate))
    assert popup.isVisible(), "la palette a disparu en emportant son éditeur"


# --------------------------------------------------------------------------
# Mise en route
# --------------------------------------------------------------------------


def test_une_cle_manquante_ouvre_les_preferences(qapp: QApplication, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Une installation neuve ne doit pas échouer en silence à la première action."""
    from scribedesk.config import ProviderConfig
    from scribedesk.ui import app as module

    monkeypatch.setattr(module, "get_api_key", lambda _: "")

    ouvertures: list[bool] = []
    sondes: list[bool] = []
    notifications: list[tuple[str, str]] = []

    application = module.ScribeDeskApp.__new__(module.ScribeDeskApp)
    application._settings = Settings(provider=ProviderConfig(key="groq"))
    application._open_settings = lambda: ouvertures.append(True)  # type: ignore[method-assign]
    application._probe_provider = lambda: sondes.append(True)  # type: ignore[method-assign]
    application._notify = lambda t, m: notifications.append((t, m))  # type: ignore[method-assign]

    module.ScribeDeskApp._check_configuration(application)

    assert ouvertures == [True], "les préférences doivent s'ouvrir"
    assert sondes == [], "inutile de sonder un moteur sans clé"
    assert "clé" in notifications[0][1]


def test_un_moteur_local_ne_reclame_pas_de_cle(qapp: QApplication, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from scribedesk.config import ProviderConfig
    from scribedesk.ui import app as module

    monkeypatch.setattr(module, "get_api_key", lambda _: "")

    sondes: list[bool] = []
    application = module.ScribeDeskApp.__new__(module.ScribeDeskApp)
    application._settings = Settings(provider=ProviderConfig(key="ollama"))
    application._probe_provider = lambda: sondes.append(True)  # type: ignore[method-assign]

    module.ScribeDeskApp._check_configuration(application)
    assert sondes == [True], "Ollama doit être sondé, pas bloqué sur une clé"


def test_le_conseil_depend_du_fournisseur(qapp: QApplication) -> None:
    """Un message d'échec doit dire quoi faire, pas seulement ce qui a raté."""
    from scribedesk.config import ProviderConfig
    from scribedesk.providers import ProviderUnavailable
    from scribedesk.ui.app import ScribeDeskApp

    application = ScribeDeskApp.__new__(ScribeDeskApp)
    echec = ProviderUnavailable("All connection attempts failed")

    application._settings = Settings(provider=ProviderConfig(key="ollama"))
    local = ScribeDeskApp._conseil(application, echec)
    assert "Démarrez-le" in local

    application._settings = Settings(provider=ProviderConfig(key="groq"))
    distant = ScribeDeskApp._conseil(application, echec)
    assert "préférences" in distant


def test_le_popup_est_deplacable_a_la_souris(qapp: QApplication) -> None:
    """Cliquer-glisser sur l'en-tête ou le fond déplace la palette."""
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    popup = PopupWindow(ActionLibrary([]))
    popup.move(100, 100)
    popup.show()

    # Clic gauche sur le bandeau de titre
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(15, 15),
        QPointF(115, 115),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(popup._drag_grip, press)
    assert popup._user_moved is True

    # Déplacement de 50px vers la droite et 30px vers le bas
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(65, 45),
        QPointF(165, 145),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(popup._drag_grip, move)
    assert popup.pos() == QPoint(150, 130)

    # Relâchement
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(65, 45),
        QPointF(165, 145),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(popup._drag_grip, release)
    assert popup._drag_pos is None
    popup.hide()


def test_la_fenetre_de_reponse_est_deplacable_a_la_souris(qapp: QApplication) -> None:
    """Cliquer-glisser sur le fond de la fenêtre de réponse la déplace."""
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    win = ResponseWindow()
    win.move(200, 200)
    win.show()

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(210, 210),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(win, press)

    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(30, 40),
        QPointF(230, 240),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(win, move)
    assert win.pos() == QPoint(220, 230)

    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(30, 40),
        QPointF(230, 240),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(win, release)
    assert win._drag_pos is None
    win.hide()


def test_settings_visibilite_cle_et_enregistrement(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le bouton œil bascule le mode echo et enregistrer sauvegarde la clé."""
    from PySide6.QtWidgets import QLineEdit

    from scribedesk.ui import settings as settings_ui

    # Le trousseau du système n'a pas sa place dans une suite de tests. Sur un
    # poste de développement, celle-ci y déposait une entrée bien réelle ; sur
    # une machine d'intégration continue, où aucun coffre n'existe,
    # l'enregistrement échouait et le test avec — alors que le code se
    # comportait correctement, en refusant d'écrire un secret ailleurs que dans
    # le trousseau. Un coffre en mémoire exerce le même chemin sans rien
    # laisser derrière lui.
    coffre: dict[str, str] = {}
    monkeypatch.setattr(settings_ui, "get_api_key", lambda cle: coffre.get(cle, ""))
    monkeypatch.setattr(settings_ui, "set_api_key", coffre.__setitem__)
    monkeypatch.setattr(settings_ui, "delete_api_key", lambda cle: coffre.pop(cle, None))

    window = SettingsWindow(Settings())
    window._provider.setCurrentIndex(window._provider.findData("custom"))
    assert window._api_key.echoMode() == QLineEdit.EchoMode.Password

    # Bascule pour afficher la clé
    window._toggle_key_btn.click()
    assert window._api_key.echoMode() == QLineEdit.EchoMode.Normal

    # Bascule pour masquer la clé
    window._toggle_key_btn.click()
    assert window._api_key.echoMode() == QLineEdit.EchoMode.Password

    window._api_key.setText("test_mock_key_123")
    window._save_btn.click()
    assert "succès" in window._status.text()
    assert coffre["custom"] == "test_mock_key_123"


def test_settings_langue_de_l_assistant(qapp: QApplication) -> None:
    """Le choix se relit, se collecte, et désactive le réglage qu'il contredit."""
    window = SettingsWindow(Settings(assistant_language="en"))

    assert window._assistant_language.currentData() == "en"
    assert window.collect().assistant_language == "en"
    assert not window._respect_language.isEnabled(), (
        "imposer une langue rend le suivi du texte source sans objet"
    )

    window._assistant_language.setCurrentIndex(window._assistant_language.findData("auto"))
    assert window._respect_language.isEnabled()
    assert window.collect().assistant_language == "auto"


def test_response_prompt_for_input_et_raccourci_ctrl_entree(qapp: QApplication) -> None:
    """prompt_for_input prépare la fenêtre pour la saisie et Ctrl+Entrée émet regenerate."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    win = ResponseWindow()
    emitted: list[bool] = []
    win.regenerate_requested.connect(lambda: emitted.append(True))

    win.prompt_for_input("Amélioration du texte")
    assert win._title.text() == "Amélioration du texte"
    assert win._output.toPlainText() == ""
    assert win._regenerate.text() == "Lancer"
    assert not win._replace.isEnabled()
    assert not win._copy.isEnabled()

    # Envoi de Ctrl+Entrée dans le QTextEdit
    key_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ControlModifier,
    )
    qapp.sendEvent(win._output, key_event)
    assert emitted == [True], "Ctrl+Entrée doit déclencher le lancement"


def test_run_action_selection_vide_ouvre_prompt_response(qapp: QApplication) -> None:
    """Une sélection vide n'émet pas d'erreur mais ouvre ResponseWindow en mode saisie."""
    from scribedesk.ui.app import ScribeDeskApp
    from scribedesk.ui.popup import PopupWindow

    app = ScribeDeskApp.__new__(ScribeDeskApp)
    app._selection = ""
    app._popup = PopupWindow(ActionLibrary(()))
    app._response = ResponseWindow()

    appels: list[str] = []
    app._response.prompt_for_input = lambda nom: appels.append(nom)  # type: ignore[method-assign]
    notifications: list[tuple[str, str]] = []
    app._notify = lambda t, m: notifications.append((t, m))  # type: ignore[method-assign]

    action = Action(name="Vérifier grammaire", instruction="Corrige le texte.")
    app._run_action(action, {})

    assert notifications == [], "Aucune notification bloquante ne doit être affichée"
    assert appels == ["Vérifier grammaire"], "prompt_for_input doit être appelé"


def test_regenerate_avec_saisie_utilisateur(qapp: QApplication) -> None:
    """Régénérer utilise le texte saisi dans ResponseWindow si la sélection était vide."""
    from scribedesk.ui.app import ScribeDeskApp

    app = ScribeDeskApp.__new__(ScribeDeskApp)
    action = Action(name="Corriger", instruction="Corrige le texte.")
    app._last_request = (action, "", {})
    app._response = ResponseWindow()
    app._response.set_text("Mon texte tapé à la main")

    lancements: list[tuple[Action, str, dict[str, str]]] = []
    app._launch = lambda a, t, c: lancements.append((a, t, c))  # type: ignore[method-assign]

    app._regenerate()
    assert len(lancements) == 1
    assert lancements[0][1] == "Mon texte tapé à la main"


# --------------------------------------------------------------------------
# Instance unique
# --------------------------------------------------------------------------


def test_un_second_lancement_n_acquiert_pas_le_verrou(qapp: QApplication) -> None:
    """Régression : deux instances enregistraient les mêmes raccourcis globaux.

    Le comportement devenait indéterminé — constaté en conditions réelles par
    une session de test entière sans qu'aucune correction ne parte.
    """
    from scribedesk.ui.instance import SingleInstance

    premier = SingleInstance("scribedesk-test-verrou")
    second = SingleInstance("scribedesk-test-verrou")
    try:
        assert premier.try_acquire() is True
        assert second.try_acquire() is False, "le second lancement doit céder"
        assert premier.is_primary and not second.is_primary
    finally:
        premier.release()
        second.release()


def test_le_verrou_est_rendu_a_la_fermeture(qapp: QApplication) -> None:
    """Sans libération, un redémarrage après arrêt propre serait bloqué."""
    from scribedesk.ui.instance import SingleInstance

    premier = SingleInstance("scribedesk-test-liberation")
    assert premier.try_acquire()
    premier.release()

    suivant = SingleInstance("scribedesk-test-liberation")
    try:
        assert suivant.try_acquire() is True, "la socket n'a pas été rendue"
    finally:
        suivant.release()


def test_release_est_idempotent(qapp: QApplication) -> None:
    from scribedesk.ui.instance import SingleInstance

    garde = SingleInstance("scribedesk-test-idempotent")
    garde.try_acquire()
    garde.release()
    garde.release()
    assert not garde.is_primary


def test_le_second_lancement_reveille_le_premier(qapp: QApplication) -> None:
    """Le doublon devient une commodité : il ouvre la palette de l'instance vivante."""
    from scribedesk.ui.instance import SingleInstance

    premier = SingleInstance("scribedesk-test-reveil")
    reveils: list[bool] = []
    premier.activated.connect(lambda: reveils.append(True))

    # La référence au second est conservée volontairement : un objet temporaire
    # serait détruit à la fin de l'expression, emportant son socket avant que le
    # message n'ait été lu. C'est exactement le défaut que ce correctif traite,
    # et le test doit refléter le cas réel — un second processus reste vivant
    # jusqu'à sa sortie.
    second = SingleInstance("scribedesk-test-reveil")
    try:
        assert premier.try_acquire()
        assert second.signal_existing() is True
        assert pump(qapp, lambda: bool(reveils), timeout=3.0), "aucun réveil reçu"
    finally:
        second.release()
        premier.release()


def test_la_socket_est_propre_a_l_utilisateur(qapp: QApplication) -> None:
    """Sur un poste partagé, chaque session doit pouvoir lancer son instance.

    Le nom d'utilisateur est haché : il apparaîtrait sinon dans la liste des
    canaux nommés, visible par les autres sessions.
    """
    import getpass

    from scribedesk.ui.instance import SingleInstance

    nom = SingleInstance("scribedesk").name
    assert nom.startswith("scribedesk-")
    assert getpass.getuser() not in nom


def test_activer_une_fonction_optionnelle_rafraichit_la_palette(qapp: QApplication) -> None:
    """Régression : le moteur voyait la nouvelle action, pas la grille.

    Activer la traduction dans les préférences ajoutait l'action au moteur mais
    laissait la palette à dix boutons. L'utilisateur en concluait que le réglage
    ne fonctionnait pas.
    """
    import scribedesk.ui.app as module

    application = module.ScribeDeskApp(qapp)
    try:
        assert application._popup._library.get("Traduction") is None
        avant = len(application._popup._library)

        reglages = Settings.load()
        reglages.translation_enabled = True
        application._on_settings_applied(reglages)

        assert application._popup._library.get("Traduction") is not None
        assert len(application._popup._library) == avant + 1
        assert len(application._engine.library) == avant + 1, "moteur et palette désynchronisés"
    finally:
        application._runner.stop()


# --------------------------------------------------------------------------
# Retouche et comparaison
# --------------------------------------------------------------------------


def test_la_retouche_porte_sur_le_texte_affiche(qapp: QApplication) -> None:
    """Les passes s'enchaînent : chacune affine la précédente, pas l'original."""
    window = ResponseWindow()
    window.set_text("Texte déjà corrigé.")

    recues: list[tuple[str, str]] = []
    window.adjustment_requested.connect(lambda c, t: recues.append((c, t)))

    window._adjustment.setText("  Rends-le plus formel  ")
    window._emit_adjustment()

    assert recues == [("Rends-le plus formel", "Texte déjà corrigé.")]
    assert window._adjustment.text() == "", "le champ se vide après envoi"


def test_une_retouche_vide_ne_declenche_rien(qapp: QApplication) -> None:
    window = ResponseWindow()
    recues: list[tuple[str, str]] = []
    window.adjustment_requested.connect(lambda c, t: recues.append((c, t)))

    for saisie in ("", "   "):
        window._adjustment.setText(saisie)
        window._emit_adjustment()
    assert recues == []


def test_pas_de_retouche_pendant_une_generation(qapp: QApplication) -> None:
    """Empiler une retouche sur un flux en cours mélangerait deux réponses."""
    window = ResponseWindow()
    recues: list[tuple[str, str]] = []
    window.adjustment_requested.connect(lambda c, t: recues.append((c, t)))

    window.begin("Relecture")
    window._adjustment.setText("Plus court")
    window._emit_adjustment()
    assert recues == []

    window.finish("Rien masqué.")
    window._adjustment.setText("Plus court")
    window._emit_adjustment()
    assert len(recues) == 1


def test_le_volet_de_comparaison_s_ouvre_et_se_replie(qapp: QApplication) -> None:
    window = ResponseWindow()
    assert window.comparing is False

    window.set_comparison("Texte d'origine à comparer")
    assert window.comparing is True
    assert window._source.toPlainText() == "Texte d'origine à comparer"
    assert window.width() >= 900, "la fenêtre s'élargit pour deux colonnes lisibles"

    window.set_comparison(None)
    assert window.comparing is False


def test_la_comparaison_ne_s_active_que_sur_changement_de_langue(qapp: QApplication) -> None:
    """Sans traduction, le volet gauche répéterait la sélection : inutile."""
    import scribedesk.ui.app as module

    application = module.ScribeDeskApp.__new__(module.ScribeDeskApp)
    fenetre = ResponseWindow()

    # Reproduit la décision prise dans `_launch`, sans dépendre du réseau.
    for langue, attendu in (("", False), ("Néerlandais", True)):
        fenetre.set_comparison("MARTIN ne sait plus ouvrir SAP" if langue else None)
        assert fenetre.comparing is attendu
    del application


@pytest.mark.parametrize(
    ("texte", "cible", "choix", "attendu"),
    [
        # Aucune langue imposée : rien à comparer.
        ("L'agent signale que son VPN ne démarre plus", "", None, False),
        # Cible identique à la langue du texte : les deux volets se
        # répéteraient. C'est le cas qui ouvrait la comparaison pour rien.
        ("L'agent signale que son VPN ne démarre plus", "Français", None, False),
        ("The user cannot connect to SAP with his password", "Anglais", None, False),
        # Vraie traduction : la comparaison devient utile.
        ("L'agent signale que son VPN ne démarre plus", "Néerlandais", None, True),
        ("The user cannot connect to SAP with his password", "Français", None, True),
        # La cible peut aussi venir du paramètre de l'action de traduction.
        ("L'agent signale que son VPN ne démarre plus", "", {"langue_cible": "Espagnol"}, True),
    ],
)
def test_la_comparaison_exige_un_vrai_changement_de_langue(
    qapp: QApplication, texte: str, cible: str, choix: dict[str, str] | None, attendu: bool
) -> None:
    """Régression : demander du français sur un texte français ouvrait deux
    volets quasi identiques — la correction à gauche, l'original à droite."""
    import scribedesk.ui.app as module

    application = module.ScribeDeskApp.__new__(module.ScribeDeskApp)
    action = Action(name="Relecture", instruction="i")

    source = module.ScribeDeskApp._comparison_source(application, action, texte, cible, choix)
    assert (source is not None) is attendu


def test_une_langue_indeterminee_ouvre_la_comparaison(qapp: QApplication) -> None:
    """Un volet de trop coûte moins cher qu'une comparaison manquante."""
    import scribedesk.ui.app as module

    application = module.ScribeDeskApp.__new__(module.ScribeDeskApp)
    action = Action(name="Relecture", instruction="i")

    source = module.ScribeDeskApp._comparison_source(application, action, "SAP", "Anglais", None)
    assert source == "SAP"


def test_le_bouton_de_langue_porte_un_pictogramme(qapp: QApplication) -> None:
    popup = PopupWindow(load_library())
    popup.set_palette(DARK)
    popup.set_language_choices(["Anglais", "Néerlandais"])

    assert not popup._language_button.icon().isNull(), "le globe doit être dessiné"
    assert "Langue du texte" in popup._language_button.text()

    popup._set_target_language("Néerlandais")
    assert "Néerlandais" in popup._language_button.text()
    assert not popup._language_button.icon().isNull()


# --------------------------------------------------------------------------
# Éditeur d'actions et historique
#
# Ces panneaux vivaient dans `PopupWindow` sans aucune couverture : treize
# méthodes, trois cent quatre-vingts lignes, et rien pour dire qu'elles
# fonctionnaient encore. Les tests qui suivent verrouillent le comportement
# observé avant leur extraction, de façon à pouvoir la mener sans pari.
# --------------------------------------------------------------------------


def _popup(qapp: QApplication) -> PopupWindow:
    popup = PopupWindow(load_library())
    popup.set_palette(DARK)
    return popup


def _lignes(layout) -> list:  # type: ignore[no-untyped-def]
    """Widgets réels d'une liste, hors ressorts d'espacement."""
    return [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget()]


def test_la_vue_editeur_liste_toutes_les_actions(qapp: QApplication) -> None:
    popup = _popup(qapp)
    popup._switch_view("editor")

    assert len(_lignes(popup._editor_panel._list_layout)) == len(popup._library)
    assert popup._count.text() == f"{len(popup._library)} actions"


def test_les_vues_sont_mutuellement_exclusives(qapp: QApplication) -> None:
    """Une vue oubliée visible superposerait deux panneaux sans erreur."""
    popup = _popup(qapp)
    panneaux = {
        "main": popup._actions_area,
        "params": popup._params_panel,
        "editor": popup._editor_panel,
        "history": popup._history_panel,
    }
    for vue in panneaux:
        popup._switch_view(vue)
        for autre, panneau in panneaux.items():
            assert panneau.isVisibleTo(popup) is (autre == vue), f"vue {vue}, panneau {autre}"


def test_reordonner_une_action_persiste_sur_le_disque(qapp: QApplication) -> None:
    popup = _popup(qapp)
    avant = [a.name for a in popup._library]

    popup._editor_panel._move(popup._library[0], +1)
    apres = [a.name for a in popup._library]

    assert apres[0] == avant[1] and apres[1] == avant[0]
    assert load_library(paths().ensure().actions_dir)[0].name == avant[1], "non relu du disque"

    popup._editor_panel._move(popup._library[1], -1)
    assert [a.name for a in popup._library] == avant, "le mouvement inverse doit rétablir"


def test_reordonner_au_dela_des_bornes_ne_fait_rien(qapp: QApplication) -> None:
    popup = _popup(qapp)
    avant = [a.name for a in popup._library]

    popup._editor_panel._move(popup._library[0], -1)
    popup._editor_panel._move(popup._library[-1], +1)

    assert [a.name for a in popup._library] == avant


def test_supprimer_une_action_puis_restaurer(qapp: QApplication, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from scribedesk.ui import panels as module

    monkeypatch.setattr(
        module.QMessageBox, "question", lambda *a, **k: module.QMessageBox.StandardButton.Yes
    )
    popup = _popup(qapp)
    cible = popup._library[0]
    total = len(popup._library)

    popup._editor_panel._delete(cible)
    assert len(popup._library) == total - 1
    assert popup._library.get(cible.name) is None

    popup._editor_panel._restore()
    assert len(popup._library) == total, "restaurer doit ramener l'action livrée"


def test_exporter_ecrit_un_fichier_par_action(qapp: QApplication, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from scribedesk.ui import panels as module

    cible = tmp_path / "export"
    cible.mkdir()
    monkeypatch.setattr(module.QFileDialog, "getExistingDirectory", lambda *a, **k: str(cible))
    monkeypatch.setattr(module.QMessageBox, "information", lambda *a, **k: None)

    popup = _popup(qapp)
    popup._editor_panel._export()

    assert len(list(cible.glob("*.md"))) == len(popup._library)


def test_importer_un_fichier_ajoute_l_action(qapp: QApplication, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from scribedesk.ui import panels as module

    fichier = tmp_path / "ma-regle.md"
    fichier.write_text(
        '+++\nname = "Action importée"\n+++\n\nTu es un assistant.\n', encoding="utf-8"
    )
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(fichier), ""))

    popup = _popup(qapp)
    popup._editor_panel._import()

    assert popup._library.get("Action importée") is not None


def test_un_import_illisible_previent_sans_planter(
    qapp: QApplication, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Un fichier invalide ne doit pas emporter la fenêtre."""
    from scribedesk.ui import panels as module

    fichier = tmp_path / "casse.md"
    fichier.write_text("ceci n'est pas une action", encoding="utf-8")
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *a, **k: (str(fichier), ""))
    avertissements: list[str] = []
    monkeypatch.setattr(
        module.QMessageBox, "warning", lambda *a, **k: avertissements.append(a[1] if a else "")
    )

    popup = _popup(qapp)
    total = len(popup._library)
    popup._editor_panel._import()

    assert avertissements, "l'échec doit être signalé"
    assert len(popup._library) == total


def test_l_historique_vide_affiche_un_message(qapp: QApplication) -> None:
    popup = _popup(qapp)
    popup._switch_view("history")

    lignes = _lignes(popup._history_panel._list_layout)
    assert len(lignes) == 1
    assert "Aucun historique" in lignes[0].text()


def test_l_historique_liste_une_ligne_par_entree(qapp: QApplication) -> None:
    from scribedesk.history import HistoryEntry

    popup = _popup(qapp)
    for i in range(3):
        popup._history.append(
            HistoryEntry(
                timestamp=f"2026-09-1{i}T09:00:00+00:00",
                action="Relecture et correction",
                provider="Groq",
                output_preview=f"resultat {i}",
            )
        )
    popup._switch_view("history")

    assert len(_lignes(popup._history_panel._list_layout)) == 3
    # L'accent est volontaire : l'ancien code écrivait « 3 entrees » ici et
    # « 0 entrée » après un effacement, selon le chemin emprunté.
    assert popup._count.text() == "3 entrées"


def test_supprimer_une_entree_d_historique(qapp: QApplication) -> None:
    from scribedesk.history import HistoryEntry

    popup = _popup(qapp)
    for i in range(2):
        popup._history.append(
            HistoryEntry(timestamp=f"2026-09-1{i}T09:00:00+00:00", action="A", provider="Groq")
        )
    popup._switch_view("history")
    popup._history_panel.delete_entry(0)

    assert len(popup._history) == 1
    assert len(_lignes(popup._history_panel._list_layout)) == 1


def test_cliquer_une_entree_la_copie(qapp: QApplication) -> None:
    from PySide6.QtGui import QGuiApplication

    popup = _popup(qapp)
    popup._history_panel.copy_entry("texte a recopier")

    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None and clipboard.text() == "texte a recopier"
    assert "presse-papier" in popup._count.text()


def test_un_changement_de_theme_atteint_les_panneaux(qapp: QApplication) -> None:
    """Régression d'extraction : les panneaux détiennent leur propre palette.

    Tant qu'ils lisaient celle de la palette hôte, un changement de thème les
    suivait sans rien faire. Devenus autonomes, ils ont besoin du relais — son
    absence les laisserait aux couleurs de l'ancien thème.
    """
    popup = _popup(qapp)
    popup.set_palette(LIGHT)

    assert popup._editor_panel._palette is LIGHT
    assert popup._history_panel._palette is LIGHT


def test_une_bibliotheque_mise_a_jour_atteint_l_editeur_ferme(qapp: QApplication) -> None:
    """L'éditeur doit suivre même fermé : l'ouvrir ensuite montrerait l'ancienne liste."""
    popup = _popup(qapp)
    reduite = ActionLibrary(tuple(popup._library)[:2])

    popup.set_library(reduite)

    assert popup._current_view != "editor", "le cas intéressant est justement fermé"
    assert popup._editor_panel._library is reduite
    popup._switch_view("editor")
    assert len(_lignes(popup._editor_panel._list_layout)) == 2

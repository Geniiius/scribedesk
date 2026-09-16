# SPDX-License-Identifier: MIT
"""Pictogrammes vectoriels modernes, élégants et sur mesure dessinés à la volée.

Chaque action dispose d'une identité visuelle unique, haute définition,
dessinée en double-ton (translucidité subtile + contours nets aux embouts arrondis).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

__all__ = ["GLYPHS", "action_icon"]


def _pen(painter: QPainter, color: QColor, size: int, width_ratio: float = 0.085) -> QPen:
    pen = QPen(color)
    pen.setWidthF(max(1.6, size * width_ratio))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    return pen


def _tint(color: QColor, alpha: int = 40) -> QBrush:
    c = QColor(color)
    c.setAlpha(alpha)
    return QBrush(c)


# --------------------------------------------------------------------------
# Tracés Spécifiques par Action
# --------------------------------------------------------------------------


def _relecture(painter: QPainter, color: QColor, size: int) -> None:
    """1. Relecture et correction : Loupe optique avec coche de validation."""
    s = float(size)
    cx, cy, r = s * 0.42, s * 0.42, s * 0.28

    # Lentille translucide
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 45))
    painter.drawEllipse(QPointF(cx, cy), r, r)

    # Anneau de la loupe
    _pen(painter, color, size, 0.09)
    painter.drawEllipse(QPointF(cx, cy), r, r)

    # Reflet d'éclat lumineux supérieur gauche
    glint = QPen(color)
    glint.setWidthF(max(1.2, s * 0.06))
    glint.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(glint)
    painter.drawArc(QRectF(cx - r * 0.65, cy - r * 0.65, r * 1.3, r * 1.3), 105 * 16, 65 * 16)

    # Coche de correction à l'intérieur
    chk = QPen(color)
    chk.setWidthF(max(1.5, s * 0.08))
    chk.setCapStyle(Qt.PenCapStyle.RoundCap)
    chk.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(chk)
    c_path = QPainterPath()
    c_path.moveTo(s * 0.33, s * 0.43)
    c_path.lineTo(s * 0.41, s * 0.51)
    c_path.lineTo(s * 0.52, s * 0.35)
    painter.drawPath(c_path)

    # Manche
    handle = QPen(color)
    handle.setWidthF(max(2.4, s * 0.12))
    handle.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(handle)
    painter.drawLine(QPointF(cx + r * 0.72, cy + r * 0.72), QPointF(s * 0.86, s * 0.86))


def _plume(painter: QPainter, color: QColor, size: int) -> None:
    """2. Améliore mon écrit : Plume calligraphique élégante avec fente d'encre."""
    s = float(size)

    path = QPainterPath()
    tip = QPointF(s * 0.20, s * 0.80)
    w_left = QPointF(s * 0.28, s * 0.58)
    t_left = QPointF(s * 0.64, s * 0.22)
    top = QPointF(s * 0.78, s * 0.22)
    t_right = QPointF(s * 0.78, s * 0.36)
    w_right = QPointF(s * 0.42, s * 0.72)

    path.moveTo(tip)
    path.lineTo(w_left)
    path.quadTo(s * 0.44, s * 0.42, t_left.x(), t_left.y())
    path.lineTo(top)
    path.lineTo(t_right)
    path.quadTo(s * 0.58, s * 0.56, w_right.x(), w_right.y())
    path.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 45))
    painter.drawPath(path)

    _pen(painter, color, size, 0.08)
    painter.drawPath(path)

    # Fente d'encre et œil de la plume
    fente = QPen(color)
    fente.setWidthF(max(1.2, s * 0.06))
    fente.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(fente)
    painter.drawLine(tip, QPointF(s * 0.48, s * 0.52))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawEllipse(QPointF(s * 0.48, s * 0.52), s * 0.045, s * 0.045)


def _mail(painter: QPainter, color: QColor, size: int) -> None:
    """3. Analyseur de tickets mail : Enveloppe mail avec onde d'analyse."""
    s = float(size)
    env = QRectF(s * 0.16, s * 0.28, s * 0.68, s * 0.48)
    r = s * 0.08

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 40))
    painter.drawRoundedRect(env, r, r)

    _pen(painter, color, size, 0.08)
    painter.drawRoundedRect(env, r, r)

    # Rabat triangulaire en V
    v_pen = QPen(color)
    v_pen.setWidthF(max(1.4, s * 0.07))
    v_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    v_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(v_pen)

    v_path = QPainterPath()
    v_path.moveTo(s * 0.18, s * 0.32)
    v_path.lineTo(s * 0.50, s * 0.56)
    v_path.lineTo(s * 0.82, s * 0.32)
    painter.drawPath(v_path)

    # Petite étincelle / radar en bas à droite
    spark = QPen(color)
    spark.setWidthF(max(1.2, s * 0.06))
    painter.setPen(spark)
    painter.drawArc(QRectF(s * 0.60, s * 0.52, s * 0.20, s * 0.20), 0, 180 * 16)


def _resume(painter: QPainter, color: QColor, size: int) -> None:
    """4. Résumé : Document plié avec flèches de compression / synthèse."""
    s = float(size)

    doc = QPainterPath()
    doc.moveTo(s * 0.24, s * 0.18)
    doc.lineTo(s * 0.58, s * 0.18)
    doc.lineTo(s * 0.76, s * 0.36)
    doc.lineTo(s * 0.76, s * 0.82)
    doc.lineTo(s * 0.24, s * 0.82)
    doc.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 40))
    painter.drawPath(doc)

    _pen(painter, color, size, 0.08)
    painter.drawPath(doc)

    # Pliure supérieure droite
    f_pen = QPen(color)
    f_pen.setWidthF(max(1.2, s * 0.06))
    painter.setPen(f_pen)
    painter.drawLine(QPointF(s * 0.58, s * 0.18), QPointF(s * 0.58, s * 0.36))
    painter.drawLine(QPointF(s * 0.58, s * 0.36), QPointF(s * 0.76, s * 0.36))

    # Lignes décroissantes de synthèse
    l_pen = QPen(color)
    l_pen.setWidthF(max(1.8, s * 0.09))
    l_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(l_pen)
    painter.drawLine(QPointF(s * 0.36, s * 0.48), QPointF(s * 0.64, s * 0.48))
    painter.drawLine(QPointF(s * 0.36, s * 0.60), QPointF(s * 0.56, s * 0.60))
    painter.drawLine(QPointF(s * 0.36, s * 0.72), QPointF(s * 0.46, s * 0.72))


def _shield_check(painter: QPainter, color: QColor, size: int) -> None:
    """5. Vérification qualité description : Bouclier de contrôle avec coche."""
    s = float(size)

    shield = QPainterPath()
    shield.moveTo(s * 0.50, s * 0.18)
    shield.lineTo(s * 0.78, s * 0.28)
    shield.quadTo(s * 0.78, s * 0.62, s * 0.50, s * 0.82)
    shield.quadTo(s * 0.22, s * 0.62, s * 0.22, s * 0.28)
    shield.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 40))
    painter.drawPath(shield)

    _pen(painter, color, size, 0.08)
    painter.drawPath(shield)

    # Coche à l'intérieur
    chk = QPen(color)
    chk.setWidthF(max(2.0, s * 0.10))
    chk.setCapStyle(Qt.PenCapStyle.RoundCap)
    chk.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(chk)
    cp = QPainterPath()
    cp.moveTo(s * 0.36, s * 0.48)
    cp.lineTo(s * 0.47, s * 0.59)
    cp.lineTo(s * 0.65, s * 0.39)
    painter.drawPath(cp)


def _badge_check(painter: QPainter, color: QColor, size: int) -> None:
    """6. Vérification qualité résolution : Badge sceau de certification avec rubans."""
    s = float(size)
    cx, cy, r = s * 0.50, s * 0.44, s * 0.28

    # Sceau circulaire translucide
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 45))
    painter.drawEllipse(QPointF(cx, cy), r, r)

    _pen(painter, color, size, 0.085)
    painter.drawEllipse(QPointF(cx, cy), r, r)

    # Coche centrale
    chk = QPen(color)
    chk.setWidthF(max(1.8, s * 0.09))
    chk.setCapStyle(Qt.PenCapStyle.RoundCap)
    chk.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(chk)
    cp = QPainterPath()
    cp.moveTo(s * 0.38, s * 0.44)
    cp.lineTo(s * 0.48, s * 0.54)
    cp.lineTo(s * 0.62, s * 0.36)
    painter.drawPath(cp)

    # Rubans inférieurs de décoration
    ribbon = QPen(color)
    ribbon.setWidthF(max(1.4, s * 0.07))
    ribbon.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(ribbon)
    painter.drawLine(QPointF(s * 0.40, s * 0.70), QPointF(s * 0.32, s * 0.84))
    painter.drawLine(QPointF(s * 0.60, s * 0.70), QPointF(s * 0.68, s * 0.84))


def _diagnostic(painter: QPainter, color: QColor, size: int) -> None:
    """7. Aide au diagnostic : Mallette avec onde ECG / pouls système."""
    s = float(size)

    body = QRectF(s * 0.16, s * 0.36, s * 0.68, s * 0.46)
    r = s * 0.09

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 40))
    painter.drawRoundedRect(body, r, r)

    _pen(painter, color, size, 0.08)
    painter.drawRoundedRect(body, r, r)

    # Poignée
    h_pen = QPen(color)
    h_pen.setWidthF(max(1.8, s * 0.09))
    h_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(h_pen)
    hp = QPainterPath()
    hp.moveTo(s * 0.35, s * 0.36)
    hp.lineTo(s * 0.35, s * 0.24)
    hp.quadTo(s * 0.50, s * 0.20, s * 0.65, s * 0.24)
    hp.lineTo(s * 0.65, s * 0.36)
    painter.drawPath(hp)

    # Onde ECG / battement de cœur au centre
    ecg = QPen(color)
    ecg.setWidthF(max(1.4, s * 0.07))
    ecg.setCapStyle(Qt.PenCapStyle.RoundCap)
    ecg.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(ecg)
    pulse = QPainterPath()
    pulse.moveTo(s * 0.22, s * 0.58)
    pulse.lineTo(s * 0.38, s * 0.58)
    pulse.lineTo(s * 0.45, s * 0.46)
    pulse.lineTo(s * 0.54, s * 0.70)
    pulse.lineTo(s * 0.61, s * 0.58)
    pulse.lineTo(s * 0.78, s * 0.58)
    painter.drawPath(pulse)


def _ticket_detail(painter: QPainter, color: QColor, size: int) -> None:
    """8. Description : Fiche d'incident avec avatar utilisateur et lignes."""
    s = float(size)

    card = QRectF(s * 0.20, s * 0.20, s * 0.60, s * 0.64)
    r = s * 0.08
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 40))
    painter.drawRoundedRect(card, r, r)

    _pen(painter, color, size, 0.08)
    painter.drawRoundedRect(card, r, r)

    # Pastille avatar utilisateur
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawEllipse(QPointF(s * 0.34, s * 0.36), s * 0.065, s * 0.065)

    # Ligne d'en-tête à côté de l'avatar
    h_pen = QPen(color)
    h_pen.setWidthF(max(1.8, s * 0.09))
    h_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(h_pen)
    painter.drawLine(QPointF(s * 0.46, s * 0.36), QPointF(s * 0.68, s * 0.36))

    # Lignes de description structurée
    l_pen = QPen(color)
    l_pen.setWidthF(max(1.3, s * 0.065))
    l_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(l_pen)
    painter.drawLine(QPointF(s * 0.30, s * 0.52), QPointF(s * 0.70, s * 0.52))
    painter.drawLine(QPointF(s * 0.30, s * 0.64), QPointF(s * 0.70, s * 0.64))
    painter.drawLine(QPointF(s * 0.30, s * 0.74), QPointF(s * 0.54, s * 0.74))


def _bolt(painter: QPainter, color: QColor, size: int) -> None:
    """9. Brève Génération : Éclair dynamique à facettes angulaires."""
    s = float(size)

    path = QPainterPath()
    path.moveTo(s * 0.56, s * 0.14)
    path.lineTo(s * 0.28, s * 0.52)
    path.lineTo(s * 0.48, s * 0.52)
    path.lineTo(s * 0.40, s * 0.86)
    path.lineTo(s * 0.72, s * 0.46)
    path.lineTo(s * 0.52, s * 0.46)
    path.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPath(path)

    _pen(painter, color, size, 0.07)
    painter.drawPath(path)


def _flag(painter: QPainter, color: QColor, size: int) -> None:
    """10. Note de résolution : Drapeau de succès / clôture de ticket."""
    s = float(size)

    # Drapeau flottant avec courbure
    flag = QPainterPath()
    flag.moveTo(s * 0.32, s * 0.24)
    flag.quadTo(s * 0.52, s * 0.20, s * 0.74, s * 0.28)
    flag.lineTo(s * 0.74, s * 0.54)
    flag.quadTo(s * 0.52, s * 0.46, s * 0.32, s * 0.50)
    flag.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 55))
    painter.drawPath(flag)

    _pen(painter, color, size, 0.08)
    painter.drawPath(flag)

    # Mât du drapeau avec pommeau
    mast = QPen(color)
    mast.setWidthF(max(1.8, s * 0.09))
    mast.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(mast)
    painter.drawLine(QPointF(s * 0.32, s * 0.20), QPointF(s * 0.32, s * 0.82))

    # Socle inférieur
    base = QPen(color)
    base.setWidthF(max(1.6, s * 0.08))
    base.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(base)
    painter.drawLine(QPointF(s * 0.24, s * 0.82), QPointF(s * 0.42, s * 0.82))


# --------------------------------------------------------------------------
# Icônes Outils (Bandeau Supérieur)
# --------------------------------------------------------------------------


def _refresh_tool(painter: QPainter, color: QColor, size: int) -> None:
    """Outil bandeau : Deux flèches circulaires formant une boucle épurée."""
    s = float(size)
    cx, cy, r = s * 0.50, s * 0.50, s * 0.30

    _pen(painter, color, size, 0.10)
    # Arc supérieur
    painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 30 * 16, 120 * 16)
    # Arc inférieur
    painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 210 * 16, 120 * 16)

    # Pointe de flèche 1
    p1 = QPainterPath()
    p1.moveTo(s * 0.72, s * 0.34)
    p1.lineTo(s * 0.76, s * 0.48)
    p1.lineTo(s * 0.62, s * 0.48)
    painter.drawPolyline(
        [QPointF(s * 0.72, s * 0.34), QPointF(s * 0.76, s * 0.48), QPointF(s * 0.62, s * 0.48)]
    )

    # Pointe de flèche 2
    painter.drawPolyline(
        [QPointF(s * 0.28, s * 0.66), QPointF(s * 0.24, s * 0.52), QPointF(s * 0.38, s * 0.52)]
    )


def _edit_tool(painter: QPainter, color: QColor, size: int) -> None:
    """Outil bandeau : Crayon minimaliste vectoriel net."""
    s = float(size)
    pen = _pen(painter, color, size, 0.09)
    painter.setPen(pen)

    # Corps du crayon
    body = QPainterPath()
    body.moveTo(s * 0.24, s * 0.76)
    body.lineTo(s * 0.24, s * 0.62)
    body.lineTo(s * 0.64, s * 0.22)
    body.lineTo(s * 0.78, s * 0.36)
    body.lineTo(s * 0.38, s * 0.76)
    body.closeSubpath()
    painter.drawPath(body)
    painter.drawLine(QPointF(s * 0.24, s * 0.76), QPointF(s * 0.38, s * 0.76))


def _trash_tool(painter: QPainter, color: QColor, size: int) -> None:
    """Outil bandeau : Corbeille minimaliste avec couvercle et lignes de cuve."""
    s = float(size)
    _pen(painter, color, size, 0.09)

    # Cuve de la corbeille
    bin_path = QPainterPath()
    bin_path.moveTo(s * 0.30, s * 0.38)
    bin_path.lineTo(s * 0.34, s * 0.80)
    bin_path.lineTo(s * 0.66, s * 0.80)
    bin_path.lineTo(s * 0.70, s * 0.38)
    painter.drawPath(bin_path)

    # Couvercle
    painter.drawLine(QPointF(s * 0.24, s * 0.38), QPointF(s * 0.76, s * 0.38))
    # Poignée supérieure
    painter.drawPolyline(
        [
            QPointF(s * 0.42, s * 0.38),
            QPointF(s * 0.42, s * 0.26),
            QPointF(s * 0.58, s * 0.26),
            QPointF(s * 0.58, s * 0.38),
        ]
    )

    # Lignes verticales intérieures
    inner = QPen(color)
    inner.setWidthF(max(1.2, s * 0.065))
    inner.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(inner)
    painter.drawLine(QPointF(s * 0.44, s * 0.46), QPointF(s * 0.44, s * 0.72))
    painter.drawLine(QPointF(s * 0.56, s * 0.46), QPointF(s * 0.56, s * 0.72))


def _plus_circle(painter: QPainter, color: QColor, size: int) -> None:
    """Bouton Ajouter (+) avec cercle."""
    s = float(size)
    cx, cy, r = s * 0.50, s * 0.50, s * 0.36
    _pen(painter, color, size, 0.09)
    painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.drawLine(QPointF(cx - s * 0.18, cy), QPointF(cx + s * 0.18, cy))
    painter.drawLine(QPointF(cx, cy - s * 0.18), QPointF(cx, cy + s * 0.18))


def _download_tool(painter: QPainter, color: QColor, size: int) -> None:
    """Importer : flèche vers le bas dans un bac."""
    s = float(size)
    _pen(painter, color, size, 0.09)
    painter.drawPolyline(
        [
            QPointF(s * 0.22, s * 0.62),
            QPointF(s * 0.22, s * 0.78),
            QPointF(s * 0.78, s * 0.78),
            QPointF(s * 0.78, s * 0.62),
        ]
    )
    painter.drawLine(QPointF(s * 0.50, s * 0.22), QPointF(s * 0.50, s * 0.58))
    painter.drawPolyline(
        [
            QPointF(s * 0.36, s * 0.44),
            QPointF(s * 0.50, s * 0.58),
            QPointF(s * 0.64, s * 0.44),
        ]
    )


def _upload_tool(painter: QPainter, color: QColor, size: int) -> None:
    """Exporter : flèche vers le haut sortant du bac."""
    s = float(size)
    _pen(painter, color, size, 0.09)
    painter.drawPolyline(
        [
            QPointF(s * 0.22, s * 0.62),
            QPointF(s * 0.22, s * 0.78),
            QPointF(s * 0.78, s * 0.78),
            QPointF(s * 0.78, s * 0.62),
        ]
    )
    painter.drawLine(QPointF(s * 0.50, s * 0.60), QPointF(s * 0.50, s * 0.24))
    painter.drawPolyline(
        [
            QPointF(s * 0.36, s * 0.38),
            QPointF(s * 0.50, s * 0.24),
            QPointF(s * 0.64, s * 0.38),
        ]
    )


def _restore_tool(painter: QPainter, color: QColor, size: int) -> None:
    """Restaurer : flèche circulaire antihoraire / retour arrière."""
    s = float(size)
    cx, cy, r = s * 0.50, s * 0.50, s * 0.30
    _pen(painter, color, size, 0.09)
    painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 40 * 16, 280 * 16)
    painter.drawPolyline(
        [
            QPointF(s * 0.52, s * 0.10),
            QPointF(s * 0.70, s * 0.20),
            QPointF(s * 0.54, s * 0.32),
        ]
    )


def _drag_handle(painter: QPainter, color: QColor, size: int) -> None:
    """Poignée de déplacement : 3 lignes horizontales ≡."""
    s = float(size)
    _pen(painter, color, size, 0.10)
    for y_fac in (0.34, 0.50, 0.66):
        painter.drawLine(QPointF(s * 0.25, s * y_fac), QPointF(s * 0.75, s * y_fac))


def _check_circle(painter: QPainter, color: QColor, size: int) -> None:
    """Coche de validation dans un cercle ✔."""
    s = float(size)
    cx, cy, r = s * 0.50, s * 0.50, s * 0.36
    _pen(painter, color, size, 0.09)
    painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.drawPolyline(
        [
            QPointF(s * 0.34, s * 0.52),
            QPointF(s * 0.46, s * 0.64),
            QPointF(s * 0.68, s * 0.38),
        ]
    )


def _history_tool(painter: QPainter, color: QColor, size: int) -> None:
    """Historique : cadran d'horloge stylisé avec aiguilles."""
    s = float(size)
    cx, cy, r = s * 0.50, s * 0.50, s * 0.32
    _pen(painter, color, size, 0.09)
    painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.drawPolyline(
        [
            QPointF(cx, cy - s * 0.18),
            QPointF(cx, cy),
            QPointF(cx + s * 0.14, cy),
        ]
    )


def _globe(painter: QPainter, color: QColor, size: int) -> None:
    """Globe : sélecteur de la langue de sortie."""
    s = float(size)
    cx, cy, r = s * 0.5, s * 0.5, s * 0.34

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_tint(color, 35))
    painter.drawEllipse(QPointF(cx, cy), r, r)

    _pen(painter, color, size, 0.085)
    painter.drawEllipse(QPointF(cx, cy), r, r)

    # Méridien central : une ellipse aplatie suffit à évoquer la sphère.
    painter.drawEllipse(QPointF(cx, cy), r * 0.42, r)
    # Deux parallèles.
    painter.drawLine(QPointF(cx - r * 0.92, cy - r * 0.36), QPointF(cx + r * 0.92, cy - r * 0.36))
    painter.drawLine(QPointF(cx - r * 0.92, cy + r * 0.36), QPointF(cx + r * 0.92, cy + r * 0.36))


def _dot(painter: QPainter, color: QColor, size: int) -> None:
    """Repli neutre pour un nom d'icône inconnu."""
    s = float(size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.18, s * 0.18)


#: Registre complet associant les noms d'icônes à leur tracé élégant
GLYPHS: Final[dict[str, Callable[[QPainter, QColor, int], None]]] = {
    "globe": _globe,
    # 1. Relecture
    "relecture": _relecture,
    "magnifying-glass": _relecture,
    "magnifier": _relecture,
    "search": _relecture,
    # 2. Améliore mon écrit
    "plume": _plume,
    "pencil": _plume,
    "rewrite": _plume,
    "edit": _plume,
    # 3. Analyseur mail
    "mail": _mail,
    "custom": _mail,
    "ticket": _mail,
    # 4. Résumé
    "resume": _resume,
    "summary": _resume,
    "keypoints": _resume,
    "list": _resume,
    # 5. Contrôle qualité description
    "qualite-description": _shield_check,
    "shield-check": _shield_check,
    "shield": _shield_check,
    # 6. Contrôle qualité résolution
    "qualite-resolution": _badge_check,
    "badge-check": _badge_check,
    "badge": _badge_check,
    # 7. Diagnostic
    "diagnostic": _diagnostic,
    "briefcase": _diagnostic,
    # 8. Description
    "description": _ticket_detail,
    "ticket-detail": _ticket_detail,
    "table": _ticket_detail,
    "document": _ticket_detail,
    # 9. Brève génération
    "flash": _bolt,
    "bolt": _bolt,
    "breve": _bolt,
    # 10. Note de résolution
    "resolution": _flag,
    "flag": _flag,
    "check": _flag,
    "checklist": _flag,
    "concise": _flag,
    # Outils bandeau supérieur et éditeur
    "refresh": _refresh_tool,
    "history": _history_tool,
    "clock": _history_tool,
    "edit-tool": _edit_tool,
    "trash": _trash_tool,
    "plus": _plus_circle,
    "add": _plus_circle,
    "download": _download_tool,
    "import": _download_tool,
    "upload": _upload_tool,
    "export": _upload_tool,
    "restore": _restore_tool,
    "reset": _restore_tool,
    "drag": _drag_handle,
    "handle": _drag_handle,
    "check-circle": _check_circle,
}


def action_icon(name: str, color: str, size: int = 20) -> QIcon:
    """Génère une icône vectorielle haute fidélité (2x supersampling pour netteté absolue)."""
    render_size = size * 2
    pixmap = QPixmap(render_size, render_size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.scale(2.0, 2.0)

    draw_fn = GLYPHS.get(name.strip().lower(), _dot)
    draw_fn(painter, QColor(color), size)
    painter.end()

    return QIcon(pixmap)

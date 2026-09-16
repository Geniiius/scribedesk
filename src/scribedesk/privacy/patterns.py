# SPDX-License-Identifier: MIT
"""Règles de détection des données à caractère personnel (français / belge).

Chaque règle associe une expression régulière compilée à un *validateur*
optionnel. La regex sert de filtre grossier et rapide ; le validateur tranche
les cas ambigus avec la vraie règle métier (clé de contrôle mod 97, Luhn…).
Ce découpage évite d'écrire des regex illisibles et supprime l'essentiel des
faux positifs : un numéro à 11 chiffres n'est un registre national que si sa
clé de contrôle tombe juste.

Les règles sont ordonnées par `priority` décroissante. Le moteur applique les
plus spécifiques en premier et interdit tout chevauchement, de sorte que le
`04` d'un IBAN ne soit jamais réinterprété comme un préfixe téléphonique.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "ACRONYM_STOPWORDS",
    "DEFAULT_RULES",
    "RULE_DESCRIPTIONS",
    "Rule",
    "build_rules",
    "looks_like_login",
    "looks_like_surname",
    "luhn_ok",
    "mod97_ok",
    "nir_ok",
    "nrn_ok",
]


# --------------------------------------------------------------------------
# Validateurs
# --------------------------------------------------------------------------

_ALNUM_RE: Final = re.compile(r"[^A-Za-z0-9]")


def mod97_ok(iban: str) -> bool:
    """Valide un IBAN par la clé de contrôle ISO 7064 mod 97-10."""
    cleaned = _ALNUM_RE.sub("", iban).upper()
    if not 15 <= len(cleaned) <= 34:
        return False
    rearranged = cleaned[4:] + cleaned[:4]
    try:
        numeric = "".join(str(int(ch, 36)) if ch.isalpha() else ch for ch in rearranged)
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def nrn_ok(value: str) -> bool:
    """Valide un numéro de registre national belge (11 chiffres).

    La clé est ``97 - (base % 97)``. Pour les personnes nées à partir de 2000
    on préfixe la base par un ``2`` — les deux variantes sont acceptées.
    """
    digits = _ALNUM_RE.sub("", value)
    if len(digits) != 11 or not digits.isdigit():
        return False
    base, key = int(digits[:9]), int(digits[9:])
    return key in (97 - base % 97, 97 - (2_000_000_000 + base) % 97)


def luhn_ok(value: str) -> bool:
    """Valide un numéro de carte bancaire par l'algorithme de Luhn."""
    digits = [int(c) for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def nir_ok(value: str) -> bool:
    """Valide un NIR français (sécurité sociale) : clé = 97 - (numéro % 97)."""
    digits = _ALNUM_RE.sub("", value).upper()
    if len(digits) != 15:
        return False
    body, key = digits[:13], digits[13:]
    # La Corse utilise 2A / 2B en positions 6-7, remplacés par 19 / 18.
    body = body.replace("2A", "19").replace("2B", "18")
    if not body.isdigit() or not key.isdigit():
        return False
    return int(key) == 97 - int(body) % 97


# --------------------------------------------------------------------------
# Anti-faux-positifs pour l'heuristique « nom en capitales »
# --------------------------------------------------------------------------

#: Sigles techniques et métier fréquents dans un ticket de Service Desk. Un mot
#: en capitales présent ici n'est jamais traité comme un patronyme.
#: Le formatage automatique est suspendu ici : c'est une donnée, et l'étaler à
#: raison d'un sigle par ligne la rendrait illisible et impossible à relire.
# fmt: off
ACRONYM_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        # Systèmes et applications
        "SAP", "ERP", "CRM", "SIRH", "GLPI", "ITSM", "LDAP", "SSO", "MFA", "VPN", "RDP", "SMTP",
        "IMAP", "POP3", "DNS", "DHCP", "NAS", "SAN", "SQL", "API", "URL", "URI", "HTTP",
        "HTTPS", "FTP", "SFTP", "SSH", "TLS", "SSL", "PDF", "CSV", "XLS", "XLSX", "DOCX", "ZIP",
        "PST", "OST", "AD", "GPO", "OU", "TEAMS", "OUTLOOK", "EXCEL", "WORD", "WINDOWS",
        "LINUX", "OFFICE", "EDGE", "CHROME", "FIREFOX", "CITRIX", "VMWARE", "AZURE", "INTUNE",
        "SCCM",
        # Matériel et réseau
        "PABX", "TOIP", "VOIP", "WIFI", "LAN", "WAN", "VLAN", "ADSL", "NTP", "SMB", "CIFS",
        "NFS", "IIS", "ESXI", "VDI", "MDM", "EDR", "XDR", "PKI", "USB", "HDMI", "RAM", "SSD",
        "HDD", "CPU", "GPU", "BIOS", "UEFI", "IMEI",
        # Identifiants bancaires et administratifs (le libellé, pas la valeur)
        "IBAN", "BIC", "SWIFT", "NISS", "TVA", "SIRET", "SIREN", "OTP", "PIN", "PUK", "SIM",
        # Organisation et procédures
        "BSOD", "JIRA", "SNOW", "OTRS", "ZENDESK", "ITOP", "KB", "FAQ",
        "RGPD", "GDPR", "SLA", "OLA", "KPI", "RSSI", "DSI", "DPO", "SIEM", "SOC", "INC", "REQ",
        "CHG", "PRB", "TODO", "FYI", "ASAP", "NOK", "OK", "KO", "ITIL", "CMDB", "CAB", "RFC",
        "MEP", "PRA", "PCA", "DRP",
        # Mots français courants susceptibles d'être écrits en capitales
        "BONJOUR", "MERCI", "CORDIALEMENT", "URGENT", "ATTENTION", "IMPORTANT", "REMARQUE",
        "NOTE", "OBJET", "RESOLU", "RÉSOLU", "CLOTURE", "CLÔTURE", "OUVERT", "FERME", "FERMÉ",
        "TEST", "TESTS", "PROD", "PREPROD", "DEV", "RAS", "PJ", "CC", "BCC", "REF", "SUIVI",
        "RELANCE", "RAPPEL", "INFO", "INFOS", "DEMANDE", "PROBLEME", "PROBLÈME", "INCIDENT",
        "TICKET", "AGENT", "USAGER", "SERVICE", "DESK", "SUPPORT", "HELPDESK", "CLIENT",
        "CONTACT", "ADRESSE", "TELEPHONE", "TÉLÉPHONE", "MAIL", "EMAIL", "COURRIEL", "COMPTE",
        "ACCES", "ACCÈS", "ERREUR", "ALERTE", "PANNE", "VALIDE", "VALIDÉ", "ATTENTE",
        "PRIORITE", "PRIORITÉ", "HAUTE", "BASSE", "NORMALE", "CRITIQUE", "MAJEUR", "MINEUR",
        "POSTE", "SESSION",
    }
)
# fmt: on

#: Civilités déclenchant la capture du mot capitalisé qui suit.
_CIVILITY: Final = r"(?:M\.|MM\.|Mme|Mmes|Mlle|Monsieur|Madame|Mademoiselle|Dr|Me)"

#: Séparateurs internes d'un patronyme composé (« JEAN-PIERRE », « DE VRIES »).
_NAME_SPLIT_RE: Final = re.compile(r"[ '’\-]+")


def looks_like_surname(candidate: str, stopwords: frozenset[str] = ACRONYM_STOPWORDS) -> bool:
    """Filtre l'heuristique « suite de mots en capitales ».

    Une correspondance est rejetée dès qu'*un* de ses mots est un sigle connu ou
    un mot français courant. Sans cette vérification mot à mot, une salutation
    comme ``BONJOUR MERCI`` formerait une seule correspondance dont la chaîne
    complète est absente de la liste d'exclusion, et serait donc masquée à tort.
    """
    tokens = [tok for tok in _NAME_SPLIT_RE.split(candidate) if tok]
    return bool(tokens) and all(tok.upper() not in stopwords for tok in tokens)


#: Préfixes de nommage d'infrastructure. Un identifiant qui commence par l'un
#: d'eux désigne une machine, pas une personne.
_INFRA_PREFIXES: Final[tuple[str, ...]] = (
    "srv",
    "svr",
    "serv",
    "host",
    "node",
    "vm",
    "esx",
    "clu",
    "cluster",
    "pc",
    "ws",
    "wks",
    "lap",
    "post",
    "term",
    "thin",
    "app",
    "web",
    "www",
    "api",
    "front",
    "back",
    "db",
    "sql",
    "ora",
    "pg",
    "maria",
    "mongo",
    "redis",
    "dc",
    "ad",
    "ldap",
    "exch",
    "mail",
    "smtp",
    "imap",
    "fs",
    "nas",
    "san",
    "bkp",
    "backup",
    "archive",
    "gw",
    "fw",
    "rtr",
    "sw",
    "proxy",
    "vpn",
    "dns",
    "dhcp",
    "ntp",
    "prt",
    "print",
    "scan",
    "cam",
    "tel",
    "voip",
    "pabx",
    "test",
    "dev",
    "rec",
    "prod",
    "preprod",
    "qual",
    "form",
)

#: Noms de produits fréquemment suffixés d'un numéro d'instance.
# fmt: off
_PRODUCT_NAMES: Final[frozenset[str]] = frozenset(
    """citrix sap oracle vmware nginx apache tomcat jboss iis kibana grafana
    jenkins gitlab jira confluence glpi zabbix nagios veeam sophos fortinet
    windows linux ubuntu debian centos redhat office teams outlook exchange
    sharepoint onedrive azure aws gcp docker kube kubernetes""".split()  # noqa: SIM905 - donnee, plus lisible en texte
)
# fmt: on

#: Sépare la partie alphabétique de la partie numérique d'un identifiant.
_LOGIN_SPLIT_RE: Final = re.compile(r"^([a-z]+)(\d+)$")


def looks_like_login(candidate: str, stopwords: frozenset[str] = ACRONYM_STOPWORDS) -> bool:
    """Distingue un identifiant de connexion d'un nom de machine.

    ``dupontj01`` et ``srvapp01`` ont exactement la même forme : des lettres
    suivies de chiffres. Sans arbitrage, la règle masquait les deux — et un
    modèle qui reçoit ``[[UID_1]]`` à la place d'un nom de serveur ne peut plus
    diagnostiquer quoi que ce soit.

    L'arbitrage penche volontairement du côté de la préservation. Masquer un
    nom de machine casse l'outil à chaque usage ; laisser passer un identifiant
    au motif d'infrastructure est plus rare et moins grave — un login n'est pas
    un patronyme.
    """
    match = _LOGIN_SPLIT_RE.match(candidate.lower())
    if match is None:
        return True

    lettres, chiffres = match.groups()

    if candidate.upper() in stopwords or lettres.upper() in stopwords:
        return False
    # Recherche en sous-chaîne, et non en égalité : les noms de machines sont
    # souvent composés — « sapprod02 », « citrixweb01 », « exchmail03 ». Un
    # patronyme ne contient pas de nom de produit, la contrepartie est donc
    # faible au regard du gain.
    if any(produit in lettres for produit in _PRODUCT_NAMES):
        return False
    if lettres.startswith(_INFRA_PREFIXES):
        return False
    # Un millésime en suffixe désigne une version de produit — « exch2019 »,
    # « office2021 » — jamais un numéro d'employé.
    return not (len(chiffres) == 4 and 1990 <= int(chiffres) <= 2099)


# --------------------------------------------------------------------------
# Définition d'une règle
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rule:
    """Une règle de détection.

    Attributes:
        name: identifiant stable, sert aussi de préfixe au jeton de
            remplacement (``TEL`` produit ``[[TEL_1]]``).
        pattern: regex compilée. Si elle définit un groupe nommé ``target``,
            seul ce groupe est masqué — utile pour « Monsieur Dupont », où la
            civilité doit rester visible et seul le patronyme être remplacé.
        priority: les règles de priorité haute sont appliquées en premier et
            réservent leurs positions dans le texte.
        validator: filtre optionnel appliqué à la correspondance ; renvoyer
            ``False`` rejette la détection.
        description: texte affiché dans les préférences.
    """

    name: str
    pattern: re.Pattern[str]
    priority: int = 50
    validator: Callable[[str], bool] | None = field(default=None, compare=False)
    description: str = ""

    def matches(self, text: str) -> list[re.Match[str]]:
        """Renvoie les correspondances retenues après validation."""
        if self.validator is None:
            return list(self.pattern.finditer(text))
        return [m for m in self.pattern.finditer(text) if self.validator(self.target(m))]

    @staticmethod
    def _has_target(match: re.Match[str]) -> bool:
        """Indique si la regex définit un groupe ``target`` effectivement capturé."""
        # `group("target")` lève LookupError si le groupe n'existe pas dans le
        # motif, et renvoie None s'il existe mais n'a rien capturé.
        try:
            return match.group("target") is not None
        except LookupError:
            return False

    def target(self, match: re.Match[str]) -> str:
        """Extrait la portion réellement sensible d'une correspondance."""
        return match.group("target") if self._has_target(match) else match.group(0)

    def span(self, match: re.Match[str]) -> tuple[int, int]:
        """Renvoie les bornes de la portion à masquer."""
        return match.span("target") if self._has_target(match) else match.span(0)


# --------------------------------------------------------------------------
# Catalogue par défaut
# --------------------------------------------------------------------------

DEFAULT_RULES: Final[tuple[Rule, ...]] = (
    Rule(
        name="EMAIL",
        pattern=re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
        priority=100,
        description="Adresses de courrier électronique",
    ),
    Rule(
        name="IBAN",
        pattern=re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}[ ]?[A-Z0-9]{1,4}\b"),
        priority=95,
        validator=mod97_ok,
        description="Numéros de compte bancaire (clé mod 97 vérifiée)",
    ),
    Rule(
        name="NRN",
        pattern=re.compile(r"\b\d{2}[.\-]?\d{2}[.\-]?\d{2}[-\s]?\d{3}[.\-]?\d{2}\b"),
        priority=94,
        validator=nrn_ok,
        description="Registre national belge (clé de contrôle vérifiée)",
    ),
    Rule(
        name="NIR",
        pattern=re.compile(r"\b[12]\s?\d{2}\s?\d{2}\s?(?:\d{2}|2[AB])\s?\d{3}\s?\d{3}\s?\d{2}\b"),
        priority=93,
        validator=nir_ok,
        description="Sécurité sociale française (clé de contrôle vérifiée)",
    ),
    Rule(
        name="CB",
        pattern=re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        priority=92,
        validator=luhn_ok,
        description="Cartes bancaires (algorithme de Luhn vérifié)",
    ),
    Rule(
        name="URL",
        pattern=re.compile(r"\bhttps?://[^\s<>\"'()]+", re.IGNORECASE),
        priority=90,
        description="Adresses web, susceptibles de contenir des jetons",
    ),
    Rule(
        name="IP",
        pattern=re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
        ),
        priority=85,
        description="Adresses IPv4",
    ),
    Rule(
        name="MAC",
        pattern=re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
        priority=85,
        description="Adresses MAC",
    ),
    Rule(
        name="TEL",
        pattern=re.compile(
            r"""(?<![\w.])(?:
                  \+ (?:32|33|352) [\s.\-]? (?:\(0\))? [\s.\-]? \d (?:[\s.\-]?\d){7,9}
                | 0 \d (?:[\s.\-]?\d){7,9}
            )(?![\w.])""",
            re.VERBOSE,
        ),
        priority=80,
        description="Numéros de téléphone belges, français et luxembourgeois",
    ),
    Rule(
        name="LOGIN",
        pattern=re.compile(r"(?<![\w\\])[A-Za-z]{2,}[\\][A-Za-z][\w.\-]{2,}\b"),
        priority=75,
        description="Identifiants au format DOMAINE\\utilisateur",
    ),
    Rule(
        name="UID",
        pattern=re.compile(r"\b[a-z]{4,10}\d{2,4}\b"),
        priority=60,
        validator=looks_like_login,
        description="Identifiants de connexion type « dupontj01 » (heuristique)",
    ),
    Rule(
        name="NOM",
        pattern=re.compile(rf"\b{_CIVILITY}\s+(?P<target>[A-ZÀ-ÖØ-Þ][\w'’\-]+)"),
        priority=55,
        description="Patronymes précédés d'une civilité",
    ),
    Rule(
        name="NOM",
        pattern=re.compile(r"\b[A-ZÀ-ÖØ-Þ]{4,}(?:[ '’\-][A-ZÀ-ÖØ-Þ]{2,})*\b"),
        priority=40,
        validator=looks_like_surname,
        description="Patronymes écrits en capitales (heuristique)",
    ),
)


#: Table `nom de règle -> description`, pour l'écran de préférences.
RULE_DESCRIPTIONS: Final[dict[str, str]] = {
    rule.name: rule.description for rule in reversed(DEFAULT_RULES)
}


def build_rules(extra_stopwords: Iterable[str] = ()) -> tuple[Rule, ...]:
    """Reconstruit le catalogue avec une liste d'exclusion enrichie.

    Chaque organisation a ses propres sigles — noms d'applications internes,
    codes de service — qu'une heuristique générique masquerait à tort. Plutôt
    que d'imposer un patch du code source, les préférences alimentent cette
    fonction, qui réinjecte un validateur fermé sur la liste étendue.
    """
    extras = {word.strip().upper() for word in extra_stopwords if word.strip()}
    if not extras:
        return DEFAULT_RULES

    merged = ACRONYM_STOPWORDS | extras

    # Les sigles maison valent pour les deux heuristiques : un utilisateur qui
    # déclare « GEODE » veut le préserver aussi bien en capitales (« GEODE »)
    # qu'en nom d'instance (« geode02 »).
    def surname_validator(candidate: str) -> bool:
        return looks_like_surname(candidate, merged)

    def login_validator(candidate: str) -> bool:
        return looks_like_login(candidate, merged)

    remplacants = {
        looks_like_surname: surname_validator,
        looks_like_login: login_validator,
    }

    return tuple(
        Rule(
            name=rule.name,
            pattern=rule.pattern,
            priority=rule.priority,
            validator=remplacants[rule.validator],
            description=rule.description,
        )
        if rule.validator in remplacants
        else rule
        for rule in DEFAULT_RULES
    )

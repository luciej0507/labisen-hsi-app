"""
user_import.py : Logique d'import de comptes utilisateurs depuis un CSV.

Fonctions pures : aucun appel à Streamlit ni à MongoDB ici, ce qui permet
de les tester facilement. La page admin s'occupe de l'affichage et de
l'insertion en base.

Format du CSV attendu (séparateur ";" ou ",", encodage UTF-8 ou Excel) :
    nom;prenom;email;username;role;datasets_access
Colonnes obligatoires : nom, prenom, username.
Le mot de passe n'est volontairement pas dans le CSV : des mots de passe
temporaires sont générés à l'import.
"""

import csv
import io
import re
import secrets
import unicodedata
from typing import Optional

import pandas as pd

ROLES = ("user", "admin")

CSV_COLUMNS = ["nom", "prenom", "email", "username", "role", "datasets_access"]
CSV_REQUIRED_COLUMNS = ["nom", "prenom", "username"]

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Alphabet sans caractères ambigus (pas de 0/O, 1/l/I) pour faciliter la
# communication des mots de passe temporaires.
_TEMP_PASSWORD_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def parse_datasets(text: Optional[str]) -> list:
    """Transforme "a, b;c" en ["a", "b", "c"] (virgule ou point-virgule)."""
    if not text:
        return []
    return [d.strip() for d in re.split(r"[;,]", text) if d.strip()]


def generate_temp_password(length: int = 12) -> str:
    """Génère un mot de passe temporaire aléatoire (module secrets)."""
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))


def _normalize_column_name(name) -> str:
    """"Prénom " -> "prenom" (sans accent, minuscules, sans espaces)."""
    text = unicodedata.normalize("NFKD", str(name))
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.strip().lower()


def _decode(raw: bytes) -> str:
    """Décode en UTF-8 (avec ou sans BOM), sinon en cp1252 (Excel français)."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ne garde que les colonnes connues (dans l'ordre), remplace les valeurs
    vides par "", retire les espaces autour des valeurs et supprime les
    lignes entièrement vides. L'index d'origine est conservé.
    """
    out = df.reindex(columns=CSV_COLUMNS).fillna("")
    for col in CSV_COLUMNS:
        out[col] = out[col].astype(str).str.strip()
    return out[(out != "").any(axis=1)]


def parse_csv(raw: bytes) -> pd.DataFrame:
    """
    Lit le contenu brut d'un CSV et retourne un DataFrame propre, indexé à
    partir de 1 (numéro de ligne). Lève ValueError avec un message lisible
    si le fichier est inutilisable.

    La lecture est volontairement stricte (module csv plutôt que
    pandas.read_csv) : une ligne qui a plus de valeurs que l'en-tête est
    signalée, au lieu de décaler silencieusement les colonnes.
    """
    text = _decode(raw)
    if not text.strip():
        raise ValueError("Le fichier est vide.")

    first_line = text.splitlines()[0]
    sep = ";" if first_line.count(";") > first_line.count(",") else ","

    reader = csv.reader(io.StringIO(text), delimiter=sep)
    try:
        header_row = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise ValueError("Le fichier n'a pas pu être lu comme un CSV valide.") from exc

    header = [_normalize_column_name(c) for c in header_row]

    missing = [c for c in CSV_REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(
            "Colonnes obligatoires manquantes : "
            + ", ".join(missing)
            + ". Colonnes attendues : "
            + ", ".join(CSV_COLUMNS)
            + "."
        )

    data = []
    try:
        for row in reader:
            if not row:
                continue
            if len(row) > len(header):
                extra = row[len(header):]
                if any(cell.strip() for cell in extra):
                    raise ValueError(
                        f"Ligne {reader.line_num} du fichier : trop de valeurs "
                        f"par rapport à l'en-tête. Si une cellule contient le "
                        f"séparateur (par exemple plusieurs datasets), mettez-la "
                        f"entre guillemets ou séparez ses valeurs par une virgule."
                    )
                row = row[: len(header)]
            data.append(row + [""] * (len(header) - len(row)))
    except csv.Error as exc:
        raise ValueError("Le fichier n'a pas pu être lu comme un CSV valide.") from exc

    df = pd.DataFrame(data, columns=header, dtype=str)
    # En cas de colonnes en double, on garde la première.
    df = df.loc[:, ~df.columns.duplicated()]

    df = clean_dataframe(df)
    if df.empty:
        raise ValueError("Le fichier ne contient aucune ligne exploitable.")

    df.index = range(1, len(df) + 1)
    return df


def validate_rows(df: pd.DataFrame, existing_usernames: set) -> tuple:
    """
    Valide chaque ligne du DataFrame (déjà passé dans clean_dataframe).

    Retourne (valid, rejected) :
    - valid : liste de dicts prêts à être insérés (role et datasets_access
      normalisés)
    - rejected : liste de dicts {"ligne", "username", "motif"}
    """
    valid = []
    rejected = []
    seen = set()

    for line, row in df.iterrows():
        problems = []
        nom = row["nom"]
        prenom = row["prenom"]
        username = row["username"]
        email = row["email"]
        role = row["role"].lower() or "user"

        if not nom:
            problems.append("nom manquant")
        if not prenom:
            problems.append("prénom manquant")

        if not username:
            problems.append("identifiant manquant")
        elif username in existing_usernames:
            problems.append("identifiant déjà utilisé")
        elif username in seen:
            problems.append("identifiant en doublon dans le fichier")

        if email and not _EMAIL_PATTERN.match(email):
            problems.append("email invalide")

        if role not in ROLES:
            problems.append("rôle invalide (attendu : user ou admin)")

        if problems:
            rejected.append(
                {
                    "ligne": int(line),
                    "username": username,
                    "motif": " ; ".join(problems),
                }
            )
        else:
            seen.add(username)
            valid.append(
                {
                    "ligne": int(line),
                    "nom": nom,
                    "prenom": prenom,
                    "email": email or None,
                    "username": username,
                    "role": role,
                    "datasets_access": parse_datasets(row["datasets_access"]),
                }
            )

    return valid, rejected


def build_template_csv() -> bytes:
    """Modèle CSV téléchargeable (séparateur ";" et BOM pour Excel)."""
    example = pd.DataFrame(
        [
            {
                "nom": "Dupont",
                "prenom": "Marie",
                "email": "marie.dupont@exemple.fr",
                "username": "mdupont",
                "role": "user",
                "datasets_access": "dataset_a,dataset_b",
            }
        ],
        columns=CSV_COLUMNS,
    )
    return example.to_csv(sep=";", index=False).encode("utf-8-sig")


def build_recap_csv(created: list) -> bytes:
    """
    CSV récapitulatif des comptes créés, avec les mots de passe temporaires
    en clair. Chaque élément de created est un dict avec les clés nom,
    prenom, username, role, mot_de_passe_temporaire.
    """
    columns = ["nom", "prenom", "username", "role", "mot_de_passe_temporaire"]
    df = pd.DataFrame(created, columns=columns)
    return df.to_csv(sep=";", index=False).encode("utf-8-sig")
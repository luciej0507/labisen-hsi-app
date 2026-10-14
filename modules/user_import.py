"""
user_import.py : logique d'import de comptes utilisateurs depuis un CSV.

Fonctions pures : aucun appel à Streamlit ni à MongoDB ici, ce qui permet
de les tester facilement. La page admin s'occupe de l'affichage et de
l'écriture en base.

Format du CSV attendu (séparateur ";" ou ",", encodage UTF-8 ou Excel) :
    nom;prenom;email;username
Colonnes obligatoires : nom, prenom, username. La colonne email est
optionnelle. Toute autre colonne présente dans le fichier est ignorée.

Les comptes importés sont toujours créés avec le rôle "user", sans mot de
passe et sans dataset. L'admin complète ensuite chaque compte depuis la
page Comptes utilisateurs.
"""

import csv
import io
import re
import unicodedata

import pandas as pd

# Rôles possibles (utilisé par le formulaire d'ajout d'un seul compte)
ROLES = ("user", "admin")

CSV_COLUMNS = ["nom", "prenom", "email", "username"]
CSV_REQUIRED_COLUMNS = ["nom", "prenom", "username"]

# Email : pas d'espace, de virgule ni de point-virgule, et un point après le @
_EMAIL_PATTERN = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

# Statut d'une ligne après analyse
STATUS_CREATE = "create"        # nouveau compte
STATUS_EXISTING = "existing"    # le username existe déjà en base
STATUS_DUPLICATE = "duplicate"  # username déjà présent plus haut dans le fichier
STATUS_INVALID = "invalid"      # ligne à corriger dans le tableau
STATUS_EMPTY = "empty"          # ligne entièrement vide (ignorée)

# Actions possibles pour une ligne (texte affiché à l'admin)
ACTION_CREATE = "Créer"
ACTION_UPDATE = "Mettre à jour"
ACTION_IGNORE = "Ignorer"
ACTION_FIX = "À corriger"

# Actions autorisées selon le statut. La première est l'action par défaut.
ALLOWED_ACTIONS = {
    STATUS_CREATE: (ACTION_CREATE, ACTION_IGNORE),
    STATUS_EXISTING: (ACTION_IGNORE, ACTION_UPDATE),
    STATUS_DUPLICATE: (ACTION_IGNORE,),
    STATUS_INVALID: (ACTION_FIX,),
    STATUS_EMPTY: (ACTION_IGNORE,),
}


def _normalize_column_name(name) -> str:
    """Transforme "Prénom " en "prenom" (sans accent, minuscules, sans espaces)."""
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

    # Le séparateur est celui qui apparaît le plus dans l'en-tête
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
            # Une ligne plus longue que l'en-tête est signalée à l'admin
            if len(row) > len(header):
                extra = row[len(header):]
                if any(cell.strip() for cell in extra):
                    raise ValueError(
                        f"Ligne {reader.line_num} du fichier : trop de valeurs "
                        f"par rapport à l'en-tête. Si une cellule contient le "
                        f"séparateur, mettez-la entre guillemets."
                    )
                row = row[: len(header)]
            # Une ligne plus courte est complétée avec des valeurs vides
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


def classify_rows(df: pd.DataFrame, existing_users: list) -> list:
    """
    Analyse chaque ligne du DataFrame (déjà passé dans clean_dataframe).

    existing_users : liste de dicts avec les clés "username" et "email"
    (les comptes déjà présents en base).

    Retourne une liste de dicts, un par ligne, avec les clés :
    ligne, nom, prenom, email, username, statut, motif, action.
    - statut : STATUS_CREATE, STATUS_EXISTING, STATUS_DUPLICATE,
      STATUS_INVALID ou STATUS_EMPTY
    - motif : texte expliquant le statut, affiché à l'admin
    - action : action proposée par défaut (modifiable par l'admin)

    Règles :
    - un username déjà en base donne une ligne "existant" (mise à jour possible)
    - un username déjà vu plus haut dans le fichier donne un "doublon"
    - un email pris par un autre compte (en base ou dans le fichier) est
      une erreur à corriger : on ne l'écrase jamais
    """
    # Comptes en base : usernames connus et propriétaire de chaque email
    usernames_db = set()
    email_owner_db = {}
    for user in existing_users:
        if user.get("username"):
            usernames_db.add(user["username"])
        email = (user.get("email") or "").lower()
        if email:
            email_owner_db[email] = user.get("username")

    # Valeurs déjà rencontrées dans le fichier (lignes non rejetées)
    seen_usernames = set()
    seen_emails = {}

    rows = []
    for line, row in df.iterrows():
        nom = row["nom"]
        prenom = row["prenom"]
        username = row["username"]
        email = row["email"]
        email_key = email.lower()

        # Contrôles de base sur les champs
        problems = []
        if not nom:
            problems.append("nom manquant")
        if not prenom:
            problems.append("prénom manquant")
        if not username:
            problems.append("identifiant manquant")
        if email and not _EMAIL_PATTERN.match(email):
            problems.append("email invalide")

        status = STATUS_INVALID
        motif = ""

        if not (nom or prenom or username or email):
            # Ligne entièrement vide (par exemple tout juste ajoutée) : ignorée
            status = STATUS_EMPTY
            motif = "ligne vide"
        elif problems:
            motif = " ; ".join(problems)
        elif username in seen_usernames:
            # Doublon dans le fichier : la première occurrence est conservée
            status = STATUS_DUPLICATE
            motif = "identifiant en doublon dans le fichier"
        else:
            # Conflits d'email avec un autre compte (base ou fichier)
            owner_db = email_owner_db.get(email_key)
            if email and email_key in email_owner_db and owner_db != username:
                problems.append("email déjà utilisé par un autre compte")
            if email and email_key in seen_emails and seen_emails[email_key] != username:
                problems.append("email en doublon dans le fichier")

            if problems:
                motif = " ; ".join(problems)
            else:
                seen_usernames.add(username)
                if email:
                    seen_emails[email_key] = username
                if username in usernames_db:
                    status = STATUS_EXISTING
                    motif = "compte existant : mise à jour possible"
                else:
                    status = STATUS_CREATE
                    motif = "nouveau compte"

        rows.append(
            {
                "ligne": int(line),
                "nom": nom,
                "prenom": prenom,
                "email": email or None,
                "username": username,
                "statut": status,
                "motif": motif,
                "action": ALLOWED_ACTIONS[status][0],
            }
        )

    return rows


def resolve_action(status: str, chosen) -> str:
    """
    Retourne l'action à appliquer à une ligne : celle choisie par l'admin
    si elle est autorisée pour ce statut, sinon l'action par défaut
    (par exemple, un doublon ne peut qu'être ignoré).
    """
    allowed = ALLOWED_ACTIONS[status]
    return chosen if chosen in allowed else allowed[0]


def apply_actions(rows: list, chosen_actions: dict) -> tuple:
    """
    Applique les actions choisies par l'admin.

    chosen_actions : dict {numéro de ligne: action}. Voir resolve_action
    pour les actions absentes ou non autorisées. Les lignes entièrement
    vides sont écartées.

    Retourne (to_create, to_update, ignored, to_fix) : quatre listes de lignes.
    """
    to_create, to_update, ignored, to_fix = [], [], [], []

    for row in rows:
        if row["statut"] == STATUS_EMPTY:
            continue

        action = resolve_action(row["statut"], chosen_actions.get(row["ligne"]))

        if action == ACTION_CREATE:
            to_create.append(row)
        elif action == ACTION_UPDATE:
            to_update.append(row)
        elif action == ACTION_IGNORE:
            ignored.append(row)
        else:
            to_fix.append(row)

    return to_create, to_update, ignored, to_fix


def build_template_csv() -> bytes:
    """Modèle CSV téléchargeable (séparateur ";" et BOM pour Excel)."""
    example = pd.DataFrame(
        [
            {
                "nom": "Dupont",
                "prenom": "Marie",
                "email": "marie.dupont@exemple.fr",
                "username": "mdupont",
            }
        ],
        columns=CSV_COLUMNS,
    )
    return example.to_csv(sep=";", index=False).encode("utf-8-sig")
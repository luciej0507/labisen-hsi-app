"""
Page "Mode d'emploi" - accessible sans connexion.
"""

import streamlit as st

st.set_page_config(page_title="Mode d'emploi")

from modules.topnav import render_topnav
render_topnav()



st.title("Mode d'emploi")

st.markdown(
    """
    Cette page décrit les prérequis à respecter avant d'utiliser l'application,
    notamment le format attendu des fichiers et les règles de validation des données.
    """
)

st.header("1. Format des fichiers attendus")

st.markdown(
    """
    Chaque jeu de données doit respecter l'arborescence suivante, pour chacun des
    sous-dossiers **Train**, **Test** et **Val** :

    ```
    Train/
    ├── Annotation/
    │   ├── JSON/   → 1 fichier .json par cube (métadonnées d'annotation)
    │   └── PNG/    → 1 masque .png par cube (fond noir, anomalies en blanc)
    ├── HSI/
    │   └── 2 fichiers par cube : un .bil + un .bil.hdr
    └── RGB/
        ├── PNG/    → 1 fichier .png par cube
        └── TIFF/   → 1 fichier .tiff par cube
    ```

    ⚠️ **Règle essentielle** : tous les fichiers correspondant à un même cube doivent
    partager exactement le même nom de base (seule l'extension change).

    Exemple pour un cube du jeu de test nommé
    `testUseCase_1(Avoine1)_Anomaly_Easy` :

    | Dossier | Fichier attendu |
    |---|---|
    | Annotation/JSON | `testUseCase_1(Avoine1)_Anomaly_Easy.json` |
    | Annotation/PNG | `testUseCase_1(Avoine1)_Anomaly_Easy.png` |
    | HSI | `testUseCase_1(Avoine1)_Anomaly_Easy.bil` + `.bil.hdr` |
    | RGB/PNG | `testUseCase_1(Avoine1)_Anomaly_Easy.png` |
    | RGB/TIFF | `testUseCase_1(Avoine1)_Anomaly_Easy.tiff` |
    """
)

st.header("2. Complétude des données et inférence")

st.markdown(
    """
    L'inférence **n'est pas disponible** tant que le jeu de données n'est pas complet.

    Concrètement, un jeu de données est considéré comme complet quand, pour **chaque cube HSI** :

    - le fichier `.bil` et son `.bil.hdr` sont présents dans le dossier `HSI/` ;
    - l'image RGB du cube `.png` et le fichier `.tiff` correspondants sont présents dans le dossier `RGB/` ;
    - le masque d'annotation `.png` et le fichier `.json` associé sont présents dans le dossier 
      `Annotation/`.

    > 🚧 **À définir** : l'inférence nécessite-t-elle que les 3 splits
    > (Train / Test / Val) soient complets, ou seulement le split concerné (ex : Test) ?
    """
)

st.header("3. Accès à l'application")

st.markdown(
    """
    - La consultation des menu **Accueil** et **Mode d'emploi** ne nécessite aucune
      connexion.
    - L'accès aux données et aux fonctionnalités de gestion nécessite de se connecter via
      l'onglet **Connexion**, en tant qu'Administrateur ou Utilisateur.
    """
)
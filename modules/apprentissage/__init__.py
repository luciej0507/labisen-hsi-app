"""
modules/apprentissage

Logique de la page Apprentissage : étapes du parcours, règles de
verrouillage de la frise, lecture des datasets utilisables et préparation
des patches.

Le package est découpé par rôle :
  - frise.py : étapes du parcours et règles de verrouillage
  - formats.py : mises en forme du texte affiché
  - etape_dataset.py : étape 1, choix du dataset
  - etape_patching.py : étape 2, patching

Ce package n'importe jamais Streamlit, comme datasets et patches : la
page ne fait que l'affichage et appelle ces fonctions.
"""
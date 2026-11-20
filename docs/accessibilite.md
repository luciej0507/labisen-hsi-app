# Note d'accessibilité

Projet : application SpectraVision (LabISEN, imagerie hyperspectrale).
Dernière mise à jour : 20/11/2026.

## 1. Objectif

Cette note décrit le référentiel d'accessibilité retenu pour l'application, les points déjà vérifiés, les limites connues et la procédure de contrôle manuelle à rejouer avant chaque livraison. Elle sert aussi de base aux critères d'acceptation des user stories (voir le cahier des charges).

## 2. Référentiel retenu

Le référentiel retenu est les **WCAG 2.2 (Web Content Accessibility Guidelines), niveau AA**, publiées par le W3C.

Le **RGAA 4.1.2** (Référentiel général d'amélioration de l'accessibilité), adaptation française des WCAG, sert de grille de contrôle complémentaire : ses critères et ses tests sont une traduction opérationnelle des critères de succès des WCAG.

Justification :

- un seul référentiel à citer partout, plus simple à appliquer et à vérifier ;
- le niveau AA est la cible habituelle des référentiels publics, le niveau AAA n'étant pas réaliste avec le framework Streamlit ;
- les WCAG 2.2 sont la version la plus récente et englobent les versions 2.0 et 2.1, sur lesquelles repose le RGAA 4.1.2.

Les documents livrés (cahier des charges, documentation technique, README) suivent les mêmes principes : titres structurés, tableaux simples avec ligne d'en-tête, pas d'information donnée par la couleur seule, texte alternatif ou description pour chaque figure.

## 3. Périmètre

| Élément | Concerné |
|---|---|
| Application Streamlit (pages, menus, formulaires, tableaux) | Oui |
| Illustrations de la page Apprentissage | Oui |
| Documents livrés (Markdown, PDF ou HTML) | Oui |
| Interface MLflow | Non, outil tiers non modifié |
| Documentation OpenAPI générée par FastAPI (`/docs`) | Non, outil tiers non modifié |

## 4. Points corrigés

Le tableau indique le critère WCAG concerné et la correction apportée dans le code.

| Critère WCAG | Problème constaté | Correction | Fichier |
|---|---|---|---|
| 1.4.3 Contraste minimum | Titres colorés des blocs Paramétrage et Récapitulatif sous 4,5:1 sur fond blanc (de 2,5 à 4,5) | Couleurs foncées, toutes à 4,5:1 ou plus | `ui/apprentissage/styles.py` |
| 1.4.3 Contraste minimum | Texte blanc sur les boutons verts de la frise à 3,4:1 | Vert foncé, 5,3:1 | `ui/apprentissage/styles.py` |
| 1.4.3 Contraste minimum | Légendes en gris clair par défaut | Gris foncé `#595959`, 7:1 | `ui/topnav.py` |
| 1.4.3 Contraste minimum | Libellés du récapitulatif en gris clair | Texte normal | `ui/apprentissage/etape4_lancement.py` |
| 1.4.1 Utilisation de la couleur | Lignes du tableau des splits colorées sans texte | Colonne « État » (Complet, Incomplet, Manquant) | `pages/4b_gestion_bdd.py` |
| 1.4.1 Utilisation de la couleur | Légende de l'import CSV basée sur les couleurs | Légende qui décrit la colonne Statut en texte | `pages/3a_ajout_utilisateur.py` |
| 1.1.1 Contenu non textuel | Illustrations sans équivalent textuel | Description visible sous chaque illustration | `ui/apprentissage/etape2_patching.py` |
| 2.4.7 Focus visible | Indicateur de focus clavier non garanti | Contour rouge de 3 px au focus | `ui/topnav.py` |

Points déjà conformes avant la revue :

- le logo a un attribut `alt` ;
- les étapes validées de la frise portent la mention « (validé) » en plus de la couleur ;
- les badges d'état des cartes contiennent le libellé de l'état ;
- les champs de formulaire ont un libellé ;
- le menu indique la page courante par le gras et le soulignement, en plus de la couleur ;
- les barres de progression ont un texte (par exemple « Époque 3 sur 10 »).

## 5. Limites connues

| Limite | Critère concerné | Raison | Piste |
|---|---|---|---|
| La langue de la page est déclarée en anglais (`lang="en"`) | 3.1.1 Langue de la page | Streamlit ne permet pas de la modifier simplement | Aucune correction propre, limite du framework |
| Les tableaux `st.dataframe` sont peu lisibles avec un lecteur d'écran | 1.3.1 Informations et relations | Streamlit les dessine dans un canvas | Résumé textuel à côté, ou `st.table` pour les petits tableaux |
| Le suivi du patching et de l'entraînement se rafraîchit toutes les 2 secondes | 2.2.2 Pause, arrêt, masquage | Mise à jour automatique par `st.fragment` | Ajouter un bouton pour suspendre l'actualisation |
| Les badges (`st.badge`) ont des couleurs imposées par Streamlit | 1.4.3 Contraste minimum | Couleurs non réglables | Le libellé reste lisible, l'état est donné en texte |
| Un seul thème (clair) | Aucun, non exigé par les WCAG | Choix assumé : thème clair unique, contrastes vérifiés | Mode sombre prévu comme évolution |
| Le message « Connexion réussie » disparaît tout de suite après la redirection | 4.1.3 Messages d'état | Redirection immédiate vers la page suivante | À étudier |

## 6. Grille de contrôle manuelle

À rejouer avant chaque livraison, sur chaque page : Connexion, Mode d'emploi, Accueil, Ajout utilisateur, Comptes utilisateurs, Reporting, Gestion des BDD, Apprentissage (4 étapes), Acquisition.

Pour chaque contrôle, noter dans la colonne « Résultat » : Conforme, Non conforme ou Non applicable, avec la date et, si besoin, une remarque. Le contrôle est réussi si le résultat attendu est observé.

### 6.1 Navigation au clavier

Outil : le clavier seul (touches Tab, Maj+Tab, Entrée, Espace, flèches, Échap). Ne pas utiliser la souris.

| N° | Contrôle | Résultat attendu | Critère WCAG | Résultat |
|---|---|---|---|---|
| C1 | Parcourir toute la page avec Tab | Tous les liens, boutons et champs sont atteints, dans un ordre logique | 2.1.1, 2.4.3 | |
| C2 | Repérer le focus à chaque étape | Un contour rouge est visible sur l'élément ciblé | 2.4.7 | |
| C3 | Activer chaque bouton avec Entrée ou Espace | L'action se déclenche | 2.1.1 | |
| C4 | Remplir et envoyer le formulaire de connexion sans souris | La connexion fonctionne | 2.1.1 | |
| C5 | Ouvrir et refermer un expander avec le clavier | Le contenu se déplie et se replie | 2.1.1 | |
| C6 | Chercher un piège au clavier | On peut toujours quitter chaque zone avec Tab ou Échap | 2.1.2 | |
| C7 | Parcourir le tableau d'import CSV et le tableau des comptes | Chaque cellule modifiable est atteignable, sinon une alternative existe | 2.1.1 | |

### 6.2 Affichage et zoom

Outil : le navigateur (zoom avec Ctrl et +).

| N° | Contrôle | Résultat attendu | Critère WCAG | Résultat |
|---|---|---|---|---|
| Z1 | Zoom à 200 % | Aucun contenu coupé ni masqué, lecture possible | 1.4.4 | |
| Z2 | Zoom à 400 % (fenêtre de 1280 px de large) | Pas de défilement horizontal pour le texte courant | 1.4.10 | |
| Z3 | Agrandir seulement le texte dans les réglages du navigateur | Le texte grossit, rien ne se chevauche | 1.4.4 | |
| Z4 | Réduire la fenêtre à la largeur d'un téléphone | Le contenu reste utilisable | 1.4.10 | |

### 6.3 Couleurs et contrastes

Outil : un vérificateur de contraste, par exemple « Colour Contrast Analyser » ou l'inspecteur de couleur des outils de développement du navigateur.

| N° | Contrôle | Résultat attendu | Critère WCAG | Résultat |
|---|---|---|---|---|
| K1 | Mesurer le contraste du texte normal (titres de blocs, légendes, menus, boutons) | 4,5:1 ou plus | 1.4.3 | |
| K2 | Mesurer le contraste du texte de grande taille (24 px, ou 19 px en gras) | 3:1 ou plus | 1.4.3 | |
| K3 | Mesurer le contraste des contours de champs, boutons et indicateur de focus | 3:1 ou plus | 1.4.11 | |
| K4 | Afficher la page en niveaux de gris (réglage du système ou extension) | Chaque état reste compréhensible : le texte suffit sans couleur | 1.4.1 | |
| K5 | Vérifier chaque information colorée (états, statuts, étapes, compteurs) | Un texte ou un symbole porte aussi l'information | 1.4.1 | |

### 6.4 Lecteur d'écran

Outil : NVDA (Windows, gratuit) ou VoiceOver (macOS, intégré).

| N° | Contrôle | Résultat attendu | Critère WCAG | Résultat |
|---|---|---|---|---|
| L1 | Écouter le titre de la page à l'ouverture | Le titre de la page est annoncé et correspond au contenu | 2.4.2 | |
| L2 | Naviguer de titre en titre | La hiérarchie des titres est logique, sans saut de niveau | 1.3.1, 2.4.6 | |
| L3 | Se placer sur chaque champ de formulaire | Le libellé du champ est annoncé | 1.3.1, 3.3.2 | |
| L4 | Provoquer une erreur (mauvais mot de passe, import invalide) | Le message d'erreur est lu et explique le problème | 3.3.1, 4.1.3 | |
| L5 | Se placer sur une illustration | Sa description est lue, ou on atteint le texte qui la décrit | 1.1.1 | |
| L6 | Se placer sur le logo | « Logo LabISEN » est annoncé | 1.1.1 | |
| L7 | Se placer sur un lien du menu | L'intitulé est clair hors contexte, la page courante est identifiable | 2.4.4 | |
| L8 | Lire le tableau des splits | Les en-têtes sont associés aux cellules, la colonne État est lue | 1.3.1 | |

### 6.5 Contenus et messages

| N° | Contrôle | Résultat attendu | Critère WCAG | Résultat |
|---|---|---|---|---|
| T1 | Lire chaque message d'erreur | Il dit ce qui ne va pas et comment le corriger | 3.3.1, 3.3.3 | |
| T2 | Lire les intitulés des boutons et des liens | Ils sont compréhensibles seuls, sans le contexte visuel | 2.4.4 | |
| T3 | Vérifier la langue du contenu | Tout le texte est en français, avec ses accents | 3.1.2 | |
| T4 | Observer les zones qui se mettent à jour toute seules (suivi du patching, de l'entraînement) | Voir la limite connue du paragraphe 5 | 2.2.2 | |
| T5 | Vérifier qu'aucun contenu ne clignote plus de 3 fois par seconde | Aucun clignotement | 2.3.1 | |

### 6.6 Documents livrés

| N° | Contrôle | Résultat attendu | Critère WCAG | Résultat |
|---|---|---|---|---|
| D1 | Vérifier la structure des titres | Un seul titre de niveau 1, pas de saut de niveau | 1.3.1 | |
| D2 | Vérifier les figures et schémas | Chacun a un texte alternatif ou une description | 1.1.1 | |
| D3 | Vérifier les tableaux | Une ligne d'en-tête, pas de cellules fusionnées | 1.3.1 | |
| D4 | Vérifier les couleurs | Aucune information donnée par la couleur seule, contraste suffisant | 1.4.1, 1.4.3 | |
| D5 | Vérifier le format | HTML ou PDF balisé, jamais une image de texte | 1.4.5 | |
| D6 | Vérifier les liens | Leur intitulé décrit la destination | 2.4.4 | |

## 7. Outils utiles

| Outil | Usage |
|---|---|
| Colour Contrast Analyser | Mesure des contrastes |
| NVDA ou VoiceOver | Test avec un lecteur d'écran |
| Extension de navigateur WAVE ou axe DevTools | Détection automatique d'une partie des problèmes (elle ne remplace pas le contrôle manuel) |
| Recommandations de l'association Valentin Haüy et de Microsoft | Rédaction de documents accessibles |

## 8. Suivi

À chaque livraison, recopier la grille du paragraphe 6 avec la date du contrôle, remplir la colonne « Résultat » et ouvrir une issue GitHub pour chaque point non conforme. Les limites du paragraphe 5 sont à mettre à jour quand une correction est apportée.

## 9. Références

- WCAG 2.2, traduction française autorisée du W3C : https://www.w3.org/Translations/WCAG22-fr-20250317/
- RGAA 4.1.2 : https://accessibilite.numerique.gouv.fr/doc/RGAA-v4.1.2.odt
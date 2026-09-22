# 📅 Échéancier d'emprunt à déblocages multiples — format Pennylane

Application [Streamlit](https://streamlit.io) qui reproduit l'échéancier bancaire d'un prêt débloqué en
plusieurs fois et génère le fichier d'import **Pennylane** (même structure que `modeles/Echeancier_type.xlsx`).

## Utilisation

L'écran se remplit en trois étapes ; l'échéancier se génère dès que les informations obligatoires sont saisies.

1. **Le prêt** (offre de prêt) : montant emprunté, taux, date de la 1re échéance, nombre total
   d'échéances, dont échéances de différé, et — facultatif — le montant de l'échéance indiqué par la
   banque. Si un différé est saisi : intérêts ajoutés au capital ou prélevés.
2. **Les déblocages** : import du grand livre du compte 164 exporté de Pennylane (recommandé : les
   remboursements comptabilisés servent aussi de contrôle), saisie manuelle, ou fonds versés en une fois.
3. **Le tableau de la banque** (si les intérêts du différé sont ajoutés au capital) : recopier le
   capital amorti et le capital restant dû d'une ligne de situation du tableau.

Les options (assurance, frais, périodicité, type de remboursement, intérêts en jours exacts) sont
regroupées dans un volet repliable. Le bouton **Télécharger l'échéancier Pennylane** produit le fichier
d'import (même structure que `modeles/Echeancier_type.xlsx`, dates au format jj/mm/aaaa).

### Exemple : prêt n°141

| Champ | Valeur |
|---|---|
| Montant emprunté / taux | 24 000,00 € / 4,170 % |
| Date de la 1re échéance | 05/01/2026 |
| Échéance hors assurance | 468,45 € |
| Nombre total d'échéances / dont différé | 60 / 3 (intérêts ajoutés au capital) |
| Déblocages | grand livre `tests/grand_livre_exemple.xlsx` |
| Capital amorti / capital restant dû | 2 326,56 € / 21 859,20 € |

## Règles de calcul

Règles déduites du grand livre d'un prêt Crédit Agricole à déblocages successifs (reproduit au centime) :

- **Différé** : pendant les premières échéances, pas de remboursement de capital. Les intérêts courent
  sur les fonds réellement débloqués : **période pleine (taux / 12)** pour les fonds déjà versés au
  début de la période, **jours exacts / 365** du versement à l'échéance pour ceux versés en cours de
  période. Si le capital de départ du tableau bancaire est saisi, le total est calé dessus et l'écart
  est réparti au prorata de chaque mois. Ils sont soit **capitalisés** (ajoutés au capital, rien n'est
  prélevé), soit payés à chaque échéance.
- **Amortissement** : à la fin du différé, le capital total + intérêts capitalisés est remboursé par
  échéances constantes, comme un prêt classique, même si des fonds sont encore débloqués ensuite.
  Les intérêts de chaque échéance valent capital restant dû × taux / 12, comme sur le tableau
  bancaire. Une option (réglages avancés) calcule à la place en jours exacts / 365.
- **Réglages avancés** pour coller au tableau de la banque :
  - *Échéance de l'offre de prêt* : fixe l'échéance constante ;
  - *Capital à amortir en fin de différé* : capital restant dû + capital déjà amorti lus sur le
    tableau bancaire. À défaut, il est déduit de l'échéance et calé sur le grand livre importé.
  - Exemple du prêt n°141 : échéance 468,45 €, capital 24 185,76 € (21 859,20 + 2 326,56) →
    tableau bancaire reproduit au centime.
- Dans le fichier Pennylane, les intérêts capitalisés apparaissent en **amortissement négatif**
  (échéance à 0, le solde augmente), ce qui garde un solde cohérent depuis le capital de l'en-tête.
- Dates au format français (jj/mm/aaaa) dans l'application et dans le fichier exporté.
- Arrondis au centime ligne par ligne ; la dernière échéance solde le capital.
- Assurance et autres frais sont répartis également sur toutes les échéances.

## Lancer en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Tests

```bash
pip install pytest
pytest
```

Les tests vérifient notamment que, sans déblocages multiples, l'application reproduit **à l'identique**
le fichier type généré par Pennylane.

## Mise en ligne sur Streamlit Community Cloud

Sur [share.streamlit.io](https://share.streamlit.io) → **Create app** : dépôt `Leo198822/app_emprunt`,
branche de travail, fichier principal `app.py`. Chaque `git push` met l'application à jour.

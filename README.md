# 📅 Échéancier d'emprunt à déblocages multiples — format Pennylane

Application [Streamlit](https://streamlit.io) qui reproduit l'échéancier bancaire d'un prêt débloqué en
plusieurs fois et génère le fichier d'import **Pennylane** (même structure que `modeles/Echeancier_type.xlsx`).

## Utilisation

L'écran se remplit en deux étapes ; l'échéancier se génère dès que les informations obligatoires sont saisies.

1. **Le prêt** (offre de prêt) : montant emprunté, taux, date de la 1re échéance, **périodicité**
   (mensuelle, trimestrielle, semestrielle, annuelle), type de remboursement, nombre total
   d'échéances, dont échéances de différé, et — facultatif — le montant de l'échéance indiqué par la
   banque. Si un différé est saisi : intérêts ajoutés au capital ou prélevés.
   **Emprunt débloqué en totalité ou partiellement** : en partiel, l'échéancier porte sur le montant
   réellement débloqué, au choix
   - *échéance du prêt complet maintenue* : le capital est soldé plus tôt (ex. prêt de 10 000 € sur
     80 mois à 4 %, 7 500 € débloqués → capital soldé à la 58e échéance de 142,61 €) ; l'échéancier
     garde la durée saisie, les échéances suivantes restant à 0 € hors assurance et frais ;
   - *durée maintenue* : l'échéance est recalculée sur le montant débloqué (→ 80 échéances de 106,96 €).
   Si l'échéance de la banque est saisie, c'est elle qui détermine quand le capital est soldé.
   Des déblocages supérieurs au montant emprunté, ou un 1er déblocage postérieur à la 1re échéance,
   bloquent la génération de l'échéancier.
2. **Les déblocages** : import du grand livre du compte 164 exporté de Pennylane (recommandé : les
   remboursements comptabilisés servent aussi de contrôle), saisie manuelle, ou fonds versés en une fois
   (en déblocage partiel, saisir alors le montant débloqué). Le total des déblocages est affiché.
3. **Ajustement (facultatif)** : sous l'échéancier, saisir une date et le capital restant dû connu à
   cette date (tableau de la banque, relevé…). L'échéancier est recalculé pour retomber exactement
   dessus : l'application ajuste les intérêts ajoutés au capital pendant le différé ou, sans différé,
   l'échéance.

Le volet **Options**, placé entre l'étape 1 et l'étape 2, regroupe l'assurance (coût mensuel fixe en € ou % du
capital restant dû), les autres frais et le calcul des intérêts en jours exacts ; il est replié par défaut.
Le bouton **Télécharger l'échéancier Pennylane** produit le fichier
d'import (même structure que `modeles/Echeancier_type.xlsx`, dates au format jj/mm/aaaa).

### Exemple : prêt n°141

| Champ | Valeur |
|---|---|
| Montant emprunté / taux | 24 000,00 € / 4,170 % |
| Date de la 1re échéance | 05/01/2026 |
| Échéance hors assurance | 468,45 € |
| Nombre total d'échéances / dont différé | 60 / 3 (intérêts ajoutés au capital) |
| Déblocages | grand livre `tests/grand_livre_exemple.xlsx` |
| Ajustement : date / capital restant dû | 08/09/2026 / 21 859,20 € |

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
  bancaire. Une option (volet « Options ») calcule à la place en jours exacts / 365.
- **Pour coller au tableau de la banque** :
  - *Échéance de l'offre de prêt* : fixe l'échéance constante ;
  - *Ajustement sur un capital restant dû connu* : l'application recherche au centime les intérêts
    capitalisés (ou l'échéance) qui redonnent ce solde. À défaut, le capital est déduit de
    l'échéance et calé sur le grand livre importé.
  - Exemple du prêt n°141 : échéance 468,45 €, capital restant dû de 21 859,20 € au 08/09/2026 →
    185,76 € d'intérêts capitalisés, tableau bancaire reproduit au centime.
- Dans le fichier Pennylane, les intérêts capitalisés apparaissent en **amortissement négatif**
  (échéance à 0, le solde augmente), ce qui garde un solde cohérent depuis le capital de l'en-tête.
- Dates au format français (jj/mm/aaaa) dans l'application et dans le fichier exporté.
- Arrondis au centime ligne par ligne ; la dernière échéance solde le capital.
- Assurance, au choix :
  - *montant fixe* : coût mensuel saisi, multiplié par le nombre de mois de la période (× 3 en
    trimestriel…), prélevé à chaque échéance jusqu'au terme du prêt, y compris après le solde du capital ;
  - *% du capital restant dû* : taux annuel appliqué au capital restant dû en début de période
    (× nombre de mois / 12) ; l'assurance diminue avec le capital et s'arrête quand il est soldé.
- Autres frais : répartis également sur toutes les échéances.

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

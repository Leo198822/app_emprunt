# 📅 Échéancier d'emprunt à déblocages multiples — format Pennylane

Application [Streamlit](https://streamlit.io) qui reproduit l'échéancier bancaire d'un prêt débloqué en
plusieurs fois et génère le fichier d'import **Pennylane** (même structure que `modeles/Echeancier_type.xlsx`).

## Ce que fait l'application

1. **Conditions de l'emprunt** : capital, taux, assurance et autres frais (en € ou en %).
2. **Déblocages** : saisie des dates et montants, ou import direct du *grand livre* du compte 164 exporté
   de Pennylane (les crédits deviennent les déblocages, les débits servent au calage et au contrôle).
3. **Amortissement** : type de remboursement, périodicité, nombre d'échéances, échéances de différé
   (intérêts capitalisés ou payés), jour de prélèvement, date du premier paiement.
4. **Export** du fichier Pennylane rempli (en-tête lignes 1-2, échéances à partir de la ligne 6).
5. **Contrôle** : si un grand livre est importé, le capital remboursé en comptabilité est comparé à
   l'échéancier calculé.

## Règles de calcul

Règles déduites du grand livre d'un prêt Crédit Agricole à déblocages successifs (reproduit au centime) :

- **Différé** : pendant les premières échéances, pas de remboursement de capital. Les intérêts courent
  sur les fonds réellement débloqués, en **jours exacts sur 365 jours**, du versement (ou de l'échéance
  précédente) jusqu'à l'échéance. Ils sont soit **capitalisés** (ajoutés au capital, rien n'est
  prélevé), soit payés à chaque échéance.
- **Amortissement** : à la fin du différé, le capital total + intérêts capitalisés est remboursé par
  échéances constantes, comme un prêt classique, même si des fonds sont encore débloqués ensuite.
  Les intérêts de chaque échéance sont calculés en **jours exacts sur 365 jours** (capital restant dû ×
  taux × nombre de jours depuis l'échéance précédente / 365) ; l'amortissement du capital varie donc
  légèrement selon la longueur des mois et la dernière échéance absorbe l'écart. Une option
  (réglages avancés) applique à la place taux / 12, comme le tableau Pennylane.
- **Échéance de l'offre de prêt** (réglages avancés) : si elle est saisie, le capital à amortir en est
  déduit ; si le grand livre est importé, il est calé pour reproduire exactement le capital remboursé.
  Exemple du prêt n°141 : échéance 468,45 € → 185,69 € d'intérêts capitalisés, 24 185,69 € amortis.
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

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

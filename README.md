# 📅 Échéancier d'emprunt à déblocages multiples — format Pennylane

Application [Streamlit](https://streamlit.io) qui reproduit l'échéancier bancaire d'un prêt débloqué en
plusieurs fois et génère le fichier d'import **Pennylane** (même structure que `modeles/Echeancier_type.xlsx`).

## Ce que fait l'application

1. **Conditions de l'emprunt** : capital, taux, assurance et autres frais (en € ou en %).
2. **Déblocages** : saisie des dates et montants, ou import direct du *grand livre* du compte 164 exporté
   de Pennylane (les crédits deviennent les déblocages).
3. **Amortissement** : type de remboursement, périodicité, nombre d'échéances, échéances de différé
   (intérêts seuls), jour de prélèvement, date du premier paiement.
4. **Export** du fichier Pennylane rempli (en-tête lignes 1-2, échéances à partir de la ligne 6).
5. **Contrôle** : si un grand livre est importé, le capital remboursé en comptabilité est comparé à
   l'échéancier calculé.

## Règles de calcul

- Le **capital amorti** suit le tableau théorique du capital total, quelles que soient les dates de
  déblocage (c'est ce que montre le grand livre : les déblocages tardifs ne modifient pas l'amortissement).
- Les **intérêts** portent sur le capital réellement débloqué et non remboursé : période pleine
  (taux / 12) pour les fonds déjà débloqués, prorata des jours (base 365 ou 360) pour les fonds
  débloqués en cours de période, et intérêts intercalaires depuis le déblocage pour la 1re échéance.
- Le **solde** est le capital restant dû réel (fonds débloqués − capital remboursé).
- Arrondis au centime ligne par ligne ; la dernière échéance absorbe l'écart (convention Pennylane).
- Assurance et autres frais sont répartis également sur toutes les échéances.
- Si l'échéance de l'offre de prêt diffère du calcul standard, saisissez-la dans **Réglages avancés** :
  l'amortissement suit alors exactement celui de la banque.

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

# 🏠 Simulateur d'emprunt

Application web [Streamlit](https://streamlit.io) pour simuler un prêt immobilier ou à la consommation.

## Fonctionnalités

- **Simulation de prêt** : mensualité (avec et sans assurance), coût des intérêts, coût de l'assurance, montant total remboursé.
- **Graphiques** : répartition annuelle capital / intérêts / assurance et évolution du capital restant dû.
- **Tableau d'amortissement** par mois ou par année, exportable en CSV (compatible Excel).
- **Capacité d'emprunt** : montant empruntable selon les revenus, les crédits en cours et le taux d'endettement maximal.

## Lancer l'application en local

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre sur http://localhost:8501.

## Tests

```bash
pip install pytest
pytest
```

## Mise en ligne sur Streamlit Community Cloud (gratuit)

1. Connectez-vous sur [share.streamlit.io](https://share.streamlit.io) avec votre compte GitHub.
2. Cliquez sur **Create app** → **Deploy a public app from GitHub**.
3. Renseignez :
   - **Repository** : `leo198822/app_emprunt`
   - **Branch** : `main` (ou la branche à publier)
   - **Main file path** : `app.py`
4. Cliquez sur **Deploy**. L'application reçoit une URL publique du type `https://<nom>.streamlit.app`.

À chaque `git push` sur la branche choisie, l'application en ligne est mise à jour automatiquement.

## Structure

```
app.py              # Interface Streamlit
emprunt.py          # Fonctions de calcul (mensualité, amortissement, capacité)
tests/              # Tests unitaires (pytest)
requirements.txt    # Dépendances installées par Streamlit Cloud
.streamlit/         # Configuration du thème
```

> Simulation indicative, non contractuelle.

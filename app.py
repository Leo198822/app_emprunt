"""Simulateur d'emprunt — application Streamlit."""

import plotly.graph_objects as go
import streamlit as st

from emprunt import Pret, capacite_emprunt, synthese, tableau_amortissement

st.set_page_config(page_title="Simulateur d'emprunt", page_icon="🏠", layout="wide")


def euros(valeur: float) -> str:
    return f"{valeur:,.2f} €".replace(",", " ").replace(".", ",")


st.title("🏠 Simulateur d'emprunt")

with st.sidebar:
    st.header("Paramètres du prêt")
    montant = st.number_input("Montant emprunté (€)", min_value=1_000, max_value=5_000_000, value=200_000, step=5_000)
    taux = st.number_input("Taux nominal annuel (%)", min_value=0.0, max_value=20.0, value=3.5, step=0.05, format="%.2f")
    duree = st.slider("Durée (années)", min_value=1, max_value=30, value=20)
    taux_assurance = st.number_input(
        "Taux d'assurance annuel (%)", min_value=0.0, max_value=2.0, value=0.30, step=0.01, format="%.2f"
    )

onglet_simulation, onglet_capacite = st.tabs(["Simulation de prêt", "Capacité d'emprunt"])

# --- Simulation de prêt -------------------------------------------------------
with onglet_simulation:
    pret = Pret(montant=montant, taux_annuel=taux, duree_annees=duree, taux_assurance=taux_assurance)
    resultats = synthese(pret)
    tableau = tableau_amortissement(pret)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Mensualité (assurance incluse)", euros(resultats["mensualite_totale"]))
    col2.metric("Mensualité hors assurance", euros(resultats["mensualite_hors_assurance"]))
    col3.metric("Coût total du crédit", euros(resultats["cout_total"]))
    col4.metric("Montant total remboursé", euros(resultats["montant_total_rembourse"]))

    st.caption(
        f"Dont intérêts : {euros(resultats['cout_interets'])} — "
        f"dont assurance : {euros(resultats['cout_assurance'])}"
    )

    par_annee = tableau.groupby("Année")[["Capital", "Intérêts", "Assurance"]].sum().reset_index()
    restant_fin_annee = tableau.groupby("Année")["Capital restant dû"].last().reset_index()

    graph1, graph2 = st.columns(2)
    with graph1:
        st.subheader("Répartition annuelle des remboursements")
        fig = go.Figure()
        for colonne in ["Capital", "Intérêts", "Assurance"]:
            fig.add_bar(x=par_annee["Année"], y=par_annee[colonne], name=colonne)
        fig.update_layout(barmode="stack", xaxis_title="Année", yaxis_title="€", legend_orientation="h")
        st.plotly_chart(fig, width="stretch")
    with graph2:
        st.subheader("Capital restant dû")
        fig = go.Figure(go.Scatter(x=restant_fin_annee["Année"], y=restant_fin_annee["Capital restant dû"], fill="tozeroy"))
        fig.update_layout(xaxis_title="Année", yaxis_title="€")
        st.plotly_chart(fig, width="stretch")

    st.subheader("Tableau d'amortissement")
    vue = st.radio("Affichage", ["Par année", "Par mois"], horizontal=True)
    if vue == "Par année":
        affiche = par_annee.merge(restant_fin_annee, on="Année")
    else:
        affiche = tableau
    colonnes_euros = [c for c in affiche.columns if c not in ("Mois", "Année")]
    st.dataframe(
        affiche.style.format({c: euros for c in colonnes_euros}),
        width="stretch",
        hide_index=True,
    )
    st.download_button(
        "📥 Télécharger le tableau (CSV)",
        data=tableau.round(2).to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name="tableau_amortissement.csv",
        mime="text/csv",
    )

# --- Capacité d'emprunt -------------------------------------------------------
with onglet_capacite:
    st.write("Estimez le montant que vous pouvez emprunter selon vos revenus et votre taux d'endettement.")
    c1, c2 = st.columns(2)
    with c1:
        revenus = st.number_input("Revenus nets mensuels du foyer (€)", min_value=0, value=4_000, step=100)
        charges = st.number_input("Crédits en cours (mensualités, €)", min_value=0, value=0, step=50)
        endettement = st.slider("Taux d'endettement maximal (%)", min_value=20, max_value=50, value=35)
    with c2:
        taux_cap = st.number_input("Taux nominal annuel (%)", min_value=0.0, max_value=20.0, value=3.5, step=0.05, format="%.2f", key="taux_cap")
        duree_cap = st.slider("Durée (années)", min_value=1, max_value=30, value=20, key="duree_cap")

    mensualite_max, capital_max = capacite_emprunt(revenus, charges, taux_cap, duree_cap, endettement)
    m1, m2 = st.columns(2)
    m1.metric("Mensualité maximale", euros(mensualite_max))
    m2.metric("Capital empruntable (hors assurance)", euros(capital_max))

st.divider()
st.caption("Simulation indicative, non contractuelle. Les conditions réelles dépendent de votre établissement prêteur.")

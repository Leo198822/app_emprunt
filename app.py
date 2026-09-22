"""Échéancier d'emprunt à déblocages multiples — export au format Pennylane."""

from datetime import date

import pandas as pd
import streamlit as st

from echeancier import (
    PERIODICITES,
    Deblocage,
    ParametresPret,
    calculer,
    comparer,
    exporter_pennylane,
    lire_grand_livre,
)

st.set_page_config(page_title="Échéancier Pennylane", page_icon="📅", layout="wide")


def euros(valeur: float) -> str:
    return f"{valeur:,.2f} €".replace(",", " ").replace(".", ",")


st.title("📅 Échéancier d'emprunt à déblocages multiples")
st.caption("Reproduit l'échéancier bancaire et génère le fichier d'import Pennylane.")

# --- Conditions de l'emprunt -----------------------------------------------------------
st.header("Conditions de l'emprunt")
c1, c2 = st.columns(2)
capital = c1.number_input("Capital emprunté (€)", min_value=0.0, value=24_000.0, step=1_000.0, format="%.2f")
taux = c2.number_input("Taux d'intérêt (%)", min_value=0.0, max_value=30.0, value=4.17, step=0.01, format="%.3f")

c1, c2 = st.columns(2)
with c1:
    a1, a2 = st.columns([3, 1])
    assurance = a1.number_input("Assurance", min_value=0.0, value=0.0, step=0.01, format="%.2f")
    unite_assurance = a2.selectbox("Unité", ["€", "%"], key="unite_assurance", help="€ : montant total — % : taux annuel sur le capital")
with c2:
    f1, f2 = st.columns([3, 1])
    autres_frais = f1.number_input("Autres frais", min_value=0.0, value=0.0, step=0.01, format="%.2f")
    unite_frais = f2.selectbox("Unité", ["€", "%"], key="unite_frais", help="€ : montant total — % : pourcentage du capital")

# --- Déblocages ------------------------------------------------------------------------
st.header("Déblocages des fonds")
grand_livre = st.file_uploader(
    "Importer le grand livre du compte d'emprunt (export Pennylane .xlsx) — facultatif",
    type=["xlsx"],
    help="Les crédits sont repris comme déblocages, les débits servent au contrôle du capital remboursé.",
)
remboursements = None
if grand_livre is not None:
    try:
        deblocages_importes, remboursements = lire_grand_livre(grand_livre)
        initial = pd.DataFrame([{"Date": d.date, "Montant (€)": d.montant} for d in deblocages_importes])
        st.success(f"{len(deblocages_importes)} déblocage(s) et {len(remboursements)} remboursement(s) importés.")
    except Exception as erreur:  # fichier inattendu : on reste sur la saisie manuelle
        st.error(f"Lecture du grand livre impossible : {erreur}")
        initial = pd.DataFrame([{"Date": date(2025, 12, 10), "Montant (€)": capital}])
else:
    initial = pd.DataFrame([{"Date": date(2025, 12, 10), "Montant (€)": capital}])

saisie = st.data_editor(
    initial,
    num_rows="dynamic",
    width="stretch",
    column_config={
        "Date": st.column_config.DateColumn("Date de déblocage", format="DD/MM/YYYY", required=True),
        "Montant (€)": st.column_config.NumberColumn("Montant (€)", min_value=0.0, format="%.2f", required=True),
    },
    key=f"deblocages_{grand_livre.name if grand_livre else 'manuel'}",
)
saisie = saisie.dropna()
deblocages = [Deblocage(pd.Timestamp(r["Date"]).date(), float(r["Montant (€)"])) for _, r in saisie.iterrows()]
total_debloque = round(sum(d.montant for d in deblocages), 2)
if deblocages and abs(total_debloque - capital) > 0.005:
    st.warning(f"Total des déblocages : {euros(total_debloque)} — différent du capital emprunté ({euros(capital)}).")

# --- Amortissement ---------------------------------------------------------------------
st.header("Amortissement")
c1, c2 = st.columns(2)
type_remboursement = c1.selectbox("Type de remboursement", ["Échéances constantes", "Amortissement constant"])
periodicite = c2.selectbox("Périodicité", list(PERIODICITES))

c1, c2 = st.columns(2)
nb_echeances = c1.number_input("Nombre d'échéances (différé inclus)", min_value=1, max_value=600, value=60)
nb_differe = c2.number_input(
    "Dont échéances de différé (intérêts seuls)",
    min_value=0,
    max_value=int(nb_echeances) - 1,
    value=0,
    help="Échéances de préfinancement pendant la mise à disposition des fonds : pas de remboursement de capital.",
)
interets_capitalises = (
    st.radio(
        "Intérêts pendant le différé",
        ["Capitalisés (ajoutés au capital)", "Payés à chaque échéance"],
        horizontal=True,
        disabled=nb_differe == 0,
        help="Capitalisés : rien n'est prélevé pendant le différé, les intérêts s'ajoutent au capital à amortir.",
    ).startswith("Capitalisés")
)

c1, c2 = st.columns(2)
jour = c1.selectbox("Jour de prélèvement", list(range(1, 32)), index=9, format_func=lambda j: f"Le {j} du mois")
premier_paiement = c2.date_input("Date du premier paiement", value=date(2026, 1, 5), format="DD/MM/YYYY")

with st.expander("Réglages avancés (pour coller exactement au tableau de la banque)", expanded=True):
    c1, c2 = st.columns(2)
    echeance_imposee = c1.number_input(
        "Échéance hors assurance de l'offre de prêt (€)",
        min_value=0.0,
        value=0.0,
        step=0.01,
        format="%.2f",
        help="Laisser à 0 pour la calculer. Si elle est saisie, le capital à amortir (et donc les intérêts "
        "capitalisés) est déduit de cette échéance, et calé sur le grand livre s'il a été importé.",
    )
    interets_capitalises_imposes = c2.number_input(
        "Intérêts capitalisés du tableau bancaire (€)",
        min_value=0.0,
        value=0.0,
        step=0.01,
        format="%.2f",
        disabled=not (nb_differe and interets_capitalises),
        help="Laisser à 0 pour les calculer (ou les déduire de l'échéance saisie).",
    )
    base_jours = st.selectbox("Base de calcul des intérêts au prorata", [365, 360], help="Pour les fonds débloqués en cours de période.")

params = ParametresPret(
    capital=capital,
    taux=taux,
    nb_echeances=int(nb_echeances),
    nb_echeances_differe=int(nb_differe),
    date_premier_paiement=premier_paiement,
    jour_prelevement=jour,
    deblocages=deblocages,
    periodicite=periodicite,
    type_remboursement=type_remboursement,
    interets_differe_capitalises=interets_capitalises,
    interets_capitalises_imposes=interets_capitalises_imposes or None,
    echeance_imposee=echeance_imposee or None,
    remboursements_constates=[] if remboursements is None else remboursements["Capital remboursé (€)"].tolist(),
    assurance=assurance,
    assurance_en_pourcentage=unite_assurance == "%",
    autres_frais=autres_frais,
    autres_frais_en_pourcentage=unite_frais == "%",
    base_jours=base_jours,
)

if capital <= 0:
    st.stop()

resultat = calculer(params)
echeancier = export = resultat.echeancier

# --- Résultats -------------------------------------------------------------------------
st.header("Échéancier")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Échéance d'amortissement", euros(echeancier["Échéance (€)"].iloc[params.nb_echeances_differe]))
m2.metric("Capital à amortir", euros(resultat.capital_amorti))
m3.metric("Total des intérêts", euros(echeancier["Intérêt (€)"].sum()))
m4.metric("Coût total", euros(echeancier[["Intérêt (€)", "Assurance (€)", "Autres frais (€)"]].sum().sum()))

if params.nb_echeances_differe and interets_capitalises:
    note = f"Intérêts capitalisés pendant le différé : {euros(resultat.interets_capitalises_retenus)}"
    ecart = round(resultat.interets_capitalises_retenus - resultat.interets_capitalises_calcules, 2)
    if ecart:
        note += (
            f" (calcul sur les déblocages : {euros(resultat.interets_capitalises_calcules)} ; "
            f"l'écart de {euros(ecart)} est porté sur la dernière échéance de différé)"
        )
    st.info(note)

derniere = echeancier["Échéance (€)"].iloc[-1]
if resultat.echeance_constante and abs(derniere - resultat.echeance_constante) > 1:
    st.warning(
        f"La dernière échéance ({euros(derniere)}) s'écarte de l'échéance constante : "
        "vérifiez l'échéance, la durée et le différé saisis."
    )

affiche = export.copy()
affiche["Date"] = pd.to_datetime(affiche["Date"]).dt.strftime("%d/%m/%Y")
st.dataframe(
    affiche.style.format({c: "{:,.2f}" for c in affiche.columns if c != "Date"}),
    width="stretch",
    hide_index=True,
    height=420,
)

st.download_button(
    "📥 Télécharger l'échéancier Pennylane (.xlsx)",
    data=exporter_pennylane(params, export),
    file_name="Echeancier_pennylane.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)

# --- Contrôle avec la comptabilité -----------------------------------------------------
if remboursements is not None and not remboursements.empty:
    st.header("Contrôle avec le grand livre")
    controle = comparer(echeancier, remboursements)
    ecart_max = controle["Écart (€)"].abs().max()
    if ecart_max <= 0.02:
        st.success("Le capital remboursé en comptabilité correspond à l'échéancier calculé.")
    else:
        st.warning(
            f"Écart maximal de {euros(ecart_max)} sur le capital remboursé. Si l'écart est régulier, saisissez "
            "l'échéance de l'offre de prêt dans « Réglages avancés » : le capital sera calé sur le grand livre."
        )
    controle["Date"] = pd.to_datetime(controle["Date"]).dt.strftime("%d/%m/%Y")
    st.dataframe(controle.style.format({c: "{:,.2f}" for c in controle.columns if c != "Date"}), hide_index=True)

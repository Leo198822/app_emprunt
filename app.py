"""Échéancier d'emprunt à déblocages multiples — export au format Pennylane."""

import pandas as pd
import streamlit as st

from echeancier import PERIODICITES, Deblocage, ParametresPret, calculer, comparer, exporter_pennylane, lire_grand_livre

st.set_page_config(page_title="Échéancier Pennylane", page_icon="📅", layout="centered")


def nombre(valeur: float) -> str:
    return f"{valeur:,.2f}".replace(",", "\u202f").replace(".", ",")


def euros(valeur: float) -> str:
    return f"{nombre(valeur)} €"


def cle(nom: str) -> str:
    """Clé de widget : change à chaque remise à zéro, ce qui recrée les champs vides."""
    return f"{nom}_{st.session_state.get('reinitialisations', 0)}"


def remettre_a_zero() -> None:
    st.session_state["reinitialisations"] = st.session_state.get("reinitialisations", 0) + 1


def tableau_euros(df: pd.DataFrame):
    affiche = df.copy()
    affiche["Date"] = pd.to_datetime(affiche["Date"]).dt.strftime("%d/%m/%Y")
    return affiche.style.format({c: nombre for c in affiche.columns if c != "Date"})


titre, bouton = st.columns([4, 1], vertical_alignment="center")
titre.title("📅 Échéancier d'emprunt pour Pennylane")
bouton.button("🔄 Remettre à zéro", on_click=remettre_a_zero, help="Efface toutes les informations saisies.", width="stretch")
st.write(
    "Renseignez les informations de votre **offre de prêt**, les **déblocages** et, si vous l'avez, le "
    "**tableau d'amortissement de la banque**. L'échéancier au format d'import Pennylane est généré en bas de page."
)

# --- Étape 1 : le prêt -------------------------------------------------------------------
st.header("1. Le prêt", divider="gray")
st.caption("Informations figurant sur l'offre de prêt.")

c1, c2 = st.columns(2)
capital = c1.number_input("Montant emprunté (€)", key=cle("capital"), min_value=0.0, value=None, step=1_000.0, format="%.2f", placeholder="ex. 24 000,00")
taux = c2.number_input("Taux nominal annuel (%)", key=cle("taux"), min_value=0.0, max_value=30.0, value=None, step=0.01, format="%.3f", placeholder="ex. 4,170")

c1, c2 = st.columns(2)
premier_paiement = c1.date_input(
    "Date de la 1re échéance", key=cle("premier_paiement"),
    value=None,
    format="DD/MM/YYYY",
    help="Date du premier prélèvement, différé compris. Les échéances suivantes tombent le même jour du mois.",
)
echeance_banque = c2.number_input(
    "Montant de l'échéance hors assurance (€)", key=cle("echeance_banque"),
    min_value=0.0,
    value=None,
    step=0.01,
    format="%.2f",
    placeholder="facultatif — ex. 468,45",
    help="Échéance constante indiquée par la banque. Si vous la laissez vide, elle est calculée.",
)

c1, c2 = st.columns(2)
nb_echeances = c1.number_input("Nombre total d'échéances", key=cle("nb_echeances"), min_value=1, max_value=600, value=None, placeholder="ex. 60", help="Différé compris.")
nb_differe = c2.number_input(
    "Dont échéances de différé", key=cle("nb_differe"),
    min_value=0,
    max_value=max(int(nb_echeances or 1) - 1, 0),
    value=0,
    help="Premières échéances sans remboursement de capital, pendant le déblocage des fonds.",
)

interets_capitalises = True
if nb_differe:
    interets_capitalises = st.radio(
        "Pendant le différé, les intérêts sont…",
        ["ajoutés au capital (rien n'est prélevé)", "prélevés à chaque échéance"],
        key=cle("interets_capitalises"),
        horizontal=True,
    ).startswith("ajoutés")

# --- Étape 2 : les déblocages ------------------------------------------------------------
st.header("2. Les déblocages", divider="gray")
source = st.radio(
    "Comment renseigner les déblocages ?",
    ["Importer le grand livre du compte d'emprunt", "Saisir les déblocages", "Fonds versés en une fois"],
    key=cle("source"),
    horizontal=True,
)
deblocages, remboursements = [], None
if source.startswith("Importer"):
    grand_livre = st.file_uploader(
        "Grand livre du compte 164 exporté de Pennylane (.xlsx)", key=cle("grand_livre"),
        type=["xlsx"],
        help="Les crédits sont repris comme déblocages ; les débits (capital remboursé) servent au contrôle.",
    )
    if grand_livre is not None:
        try:
            deblocages, remboursements = lire_grand_livre(grand_livre)
            st.dataframe(
                pd.DataFrame([{"Date": d.date.strftime("%d/%m/%Y"), "Montant (€)": d.montant} for d in deblocages]).style.format(
                    {"Montant (€)": nombre}
                ),
                hide_index=True,
            )
        except Exception as erreur:  # fichier inattendu
            st.error(f"Lecture du grand livre impossible : {erreur}")
elif source.startswith("Saisir"):
    saisie = st.data_editor(
        pd.DataFrame({"Date": pd.Series(dtype="datetime64[ns]"), "Montant (€)": pd.Series(dtype="float")}), key=cle("saisie"),
        num_rows="dynamic",
        width="stretch",
        column_config={
            "Date": st.column_config.DateColumn("Date du déblocage", format="DD/MM/YYYY", required=True),
            "Montant (€)": st.column_config.NumberColumn("Montant (€)", min_value=0.0, format="%.2f", required=True),
        },
    )
    deblocages = [Deblocage(pd.Timestamp(r["Date"]).date(), float(r["Montant (€)"])) for _, r in saisie.dropna().iterrows()]
else:
    st.caption("Le capital est considéré comme versé en totalité un mois avant la 1re échéance.")

if deblocages:
    total = round(sum(d.montant for d in deblocages), 2)
    libelle = f"**Total des déblocages : {euros(total)}** ({len(deblocages)} déblocage{'s' if len(deblocages) > 1 else ''})"
    if not capital:
        st.info(libelle)
    elif abs(total - capital) <= 0.005:
        st.success(f"{libelle} — égal au montant emprunté.")
    else:
        st.warning(f"{libelle} — écart de {euros(total - capital)} avec le montant emprunté ({euros(capital)}).")

# --- Étape 3 : le tableau de la banque ---------------------------------------------------
capital_depart = None
if nb_differe and interets_capitalises:
    st.header("3. Le tableau d'amortissement de la banque", divider="gray")
    st.caption(
        "Facultatif mais recommandé : permet de reprendre au centime les intérêts ajoutés au capital par la banque. "
        "Recopiez une ligne de situation du tableau (ex. « 08/09/2026 — capital amorti 2 326,56 — capital restant dû 21 859,20 »)."
    )
    c1, c2 = st.columns(2)
    deja_amorti = c1.number_input("Capital amorti (€)", key=cle("deja_amorti"), min_value=0.0, value=None, step=0.01, format="%.2f", placeholder="ex. 2 326,56")
    restant_du = c2.number_input("Capital restant dû (€)", key=cle("restant_du"), min_value=0.0, value=None, step=0.01, format="%.2f", placeholder="ex. 21 859,20")
    if restant_du:
        capital_depart = round(restant_du + (deja_amorti or 0), 2)
        st.caption(f"Capital à rembourser après le différé : **{euros(capital_depart)}**")

# --- Options -----------------------------------------------------------------------------
with st.expander("Options (assurance, frais, périodicité…)"):
    c1, c2 = st.columns(2)
    periodicite = c1.selectbox("Périodicité", list(PERIODICITES), key=cle("periodicite"))
    type_remboursement = c2.selectbox(
        "Type de remboursement", ["Échéances constantes", "Amortissement constant"], key=cle("type_remboursement")
    )
    c1, c2, c3, c4 = st.columns([3, 1, 3, 1])
    assurance = c1.number_input("Assurance", key=cle("assurance"), min_value=0.0, value=0.0, step=0.01, format="%.2f")
    unite_assurance = c2.selectbox("Unité", ["€", "%"], key=cle("unite_assurance"), help="€ : montant total — % : taux annuel sur le capital")
    autres_frais = c3.number_input("Autres frais", key=cle("autres_frais"), min_value=0.0, value=0.0, step=0.01, format="%.2f")
    unite_frais = c4.selectbox("Unité", ["€", "%"], key=cle("unite_frais"), help="€ : montant total — % : pourcentage du capital")
    jours_exacts = st.checkbox(
        "Calculer les intérêts d'amortissement en jours exacts / 365 (au lieu de taux / 12)", key=cle("jours_exacts"),
        help="Les banques appliquent en général taux / 12 aux échéances d'amortissement.",
    )

# --- Résultat ----------------------------------------------------------------------------
st.header("Échéancier", divider="gray")
manquants = [
    libelle
    for libelle, valeur in [
        ("le montant emprunté", capital),
        ("le taux", taux),
        ("la date de la 1re échéance", premier_paiement),
        ("le nombre d'échéances", nb_echeances),
    ]
    if valeur is None or (libelle == "le montant emprunté" and valeur == 0)
]
if source.startswith("Importer") and not deblocages:
    manquants.append("le grand livre (ou choisissez une autre façon de renseigner les déblocages)")
if manquants:
    st.info("Pour générer l'échéancier, renseignez : " + ", ".join(manquants) + ".")
    st.stop()

params = ParametresPret(
    capital=capital,
    taux=taux,
    nb_echeances=int(nb_echeances),
    nb_echeances_differe=int(nb_differe),
    date_premier_paiement=premier_paiement,
    jour_prelevement=premier_paiement.day,
    deblocages=deblocages,
    interets_differe_capitalises=interets_capitalises,
    interets_capitalises_imposes=round(capital_depart - capital, 2) if capital_depart else None,
    echeance_imposee=echeance_banque or None,
    remboursements_constates=[] if remboursements is None else remboursements["Capital remboursé (€)"].tolist(),
    periodicite=periodicite,
    type_remboursement=type_remboursement,
    interets_jours_exacts=jours_exacts,
    assurance=assurance,
    assurance_en_pourcentage=unite_assurance == "%",
    autres_frais=autres_frais,
    autres_frais_en_pourcentage=unite_frais == "%",
)
resultat = calculer(params)
echeancier = resultat.echeancier

m1, m2, m3 = st.columns(3)
m1.metric("Échéance", euros(echeancier["Échéance (€)"].iloc[params.nb_echeances_differe]))
m2.metric("Capital remboursé", euros(resultat.capital_amorti))
m3.metric("Total des intérêts", euros(echeancier["Intérêt (€)"].sum()))

if params.nb_echeances_differe and interets_capitalises:
    st.caption(
        f"Intérêts ajoutés au capital pendant le différé : {euros(resultat.interets_capitalises_retenus)} — "
        f"dernière échéance : {euros(echeancier['Échéance (€)'].iloc[-1])}."
    )

if remboursements is not None and not remboursements.empty:
    controle = comparer(echeancier, remboursements)
    if controle["Écart (€)"].abs().max() <= 0.02:
        st.success(f"✅ Contrôle : les {len(controle)} remboursements de capital du grand livre sont retrouvés au centime.")
    else:
        st.warning("⚠️ Le capital remboursé en comptabilité diffère de l'échéancier : vérifiez l'échéance et le tableau de la banque.")
        st.dataframe(tableau_euros(controle), hide_index=True)

st.download_button(
    "📥 Télécharger l'échéancier Pennylane (.xlsx)",
    data=exporter_pennylane(params, echeancier),
    file_name="Echeancier_pennylane.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    width="stretch",
)
st.dataframe(tableau_euros(echeancier), width="stretch", hide_index=True, height=420)

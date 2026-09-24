"""Échéancier d'emprunt à déblocages multiples — export au format Pennylane."""

import pandas as pd
import streamlit as st

from echeancier import (
    PERIODICITES,
    Deblocage,
    ParametresPret,
    ajouter_mois,
    ajuster_sur_solde,
    calculer,
    comparer,
    diagnostic_controle,
    exporter_pennylane,
    lire_grand_livre,
)

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


def editer_deblocages(initial: pd.DataFrame, cle_tableau: str, annulable: bool = False) -> list[Deblocage]:
    """Tableau modifiable des déblocages : correction des cellules, ajout de lignes, et suppression des lignes
    cochées (colonne « Sélection ») par le bouton 🗑️. Les corrections et ajouts déjà faits sont conservés."""
    donnees, version = f"{cle_tableau}_donnees", f"{cle_tableau}_version"
    if donnees not in st.session_state:
        st.session_state[donnees], st.session_state[version] = initial.reset_index(drop=True), 0

    barre = st.container()  # consignes et bouton 🗑️, affichés au-dessus du tableau
    saisie = st.data_editor(
        st.session_state[donnees].assign(Sélection=False),
        key=f"{cle_tableau}_{st.session_state[version]}",
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_order=["Sélection", "Date", "Montant (€)"],
        column_config={
            "Sélection": st.column_config.CheckboxColumn("☑", default=False, width="small", help="Sélectionner la ligne"),
            "Date": st.column_config.DateColumn("Date du déblocage", format="DD/MM/YYYY", required=True),
            "Montant (€)": st.column_config.NumberColumn("Montant (€)", min_value=0.0, format="%.2f", required=True),
        },
    )
    selection = saisie["Sélection"].fillna(False).astype(bool)
    nb = int(selection.sum())
    with barre:
        consignes, bouton = st.columns([3, 1], vertical_alignment="bottom")
        consignes.caption(
            "✏️ **Corriger** : double-cliquez sur une date ou un montant.  \n"
            "🗑️ **Supprimer** : cochez la ou les lignes (colonne ☑), puis cliquez sur « 🗑️ Supprimer ».  \n"
            "➕ **Ajouter** : remplissez la ligne vide en bas du tableau."
            + ("  \n↺ **Annuler** revient aux déblocages du grand livre." if annulable else "")
        )
        if bouton.button(
            f"🗑️ Supprimer ({nb})" if nb else "🗑️ Supprimer",
            key=f"{cle_tableau}_supprimer",
            disabled=nb == 0,
            help="Supprime les lignes cochées" if nb else "Cochez d'abord une ou plusieurs lignes",
            width="stretch",
        ):
            st.session_state[donnees] = saisie[~selection].drop(columns="Sélection").reset_index(drop=True)
            st.session_state[version] += 1
            st.rerun()

    saisie = saisie.dropna(subset=["Date", "Montant (€)"])
    return sorted(
        (Deblocage(pd.Timestamp(r["Date"]).date(), round(float(r["Montant (€)"]), 2)) for _, r in saisie.iterrows()),
        key=lambda d: d.date,
    )


def tableau_euros(df: pd.DataFrame):
    affiche = df.copy()
    affiche["Date"] = pd.to_datetime(affiche["Date"]).dt.strftime("%d/%m/%Y")
    return affiche.style.format({c: nombre for c in affiche.columns if c != "Date"})


titre, bouton = st.columns([3, 1], vertical_alignment="center")
titre.title("📅 Échéancier d'emprunt pour Pennylane")
bouton.button("🔄 Remettre à zéro", on_click=remettre_a_zero, help="Efface toutes les informations saisies.", width="stretch")
st.write(
    "Renseignez les informations de votre **offre de prêt** et les **déblocages** : l'échéancier au format "
    "d'import Pennylane est généré en bas de page. Vous pourrez ensuite le caler sur un capital restant dû connu."
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
periodicite = c2.selectbox("Périodicité des échéances", list(PERIODICITES), key=cle("periodicite"))

c1, c2 = st.columns(2)
echeance_banque = c1.number_input(
    "Montant de l'échéance assurance comprise (€)", key=cle("echeance_banque"),
    min_value=0.0,
    value=None,
    step=0.01,
    format="%.2f",
    placeholder="facultatif — ex. 480,95",
    help="Échéance prélevée par la banque, assurance comprise (renseignez l'assurance dans les Options). "
    "L'application en déduit l'échéance hors assurance. Si vous la laissez vide, elle est calculée.",
)
type_remboursement = c2.selectbox(
    "Type de remboursement", ["Échéances constantes", "Amortissement constant"], key=cle("type_remboursement")
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

partiel = st.radio(
    "L'emprunt est débloqué…",
    ["en totalité", "partiellement (une partie des fonds ne sera pas versée)"],
    key=cle("partiel"),
    horizontal=True,
    help="Par exemple un prêt de 10 000 € dont seuls 7 500 € ont été débloqués.",
) != "en totalité"
duree_reduite = True
if partiel:
    if echeance_banque:
        st.caption(
            "L'échéance de la banque étant saisie, elle détermine quand le capital est soldé : si elle est celle du "
            "prêt complet, avant le terme (échéances à 0 ensuite) ; si elle a été recalculée, au terme."
        )
    elif type_remboursement == "Échéances constantes":
        duree_reduite = st.radio(
            "Sur le montant débloqué, la banque…",
            [
                "garde l'échéance du prêt complet : le capital est soldé plus tôt (échéances à 0 ensuite)",
                "garde la durée : l'échéance est réduite et étalée sur toute la durée",
            ],
            key=cle("duree_reduite"),
        ).startswith("garde l'échéance")

# --- Options -----------------------------------------------------------------------------
with st.expander("Options (assurance, frais, calcul des intérêts)"):
    c1, c2 = st.columns(2)
    mode_assurance = c1.selectbox(
        "Assurance",
        ["Aucune", "Montant fixe (€ par mois)", "% du capital restant dû (taux annuel)"],
        key=cle("mode_assurance"),
    )
    assurance_en_taux = mode_assurance.startswith("%")
    valeur_assurance = None
    if mode_assurance != "Aucune":
        valeur_assurance = c2.number_input(
            "Taux annuel de l'assurance (%)" if assurance_en_taux else "Coût mensuel de l'assurance (€)",
            key=cle("assurance_taux" if assurance_en_taux else "assurance_mensuelle"),
            min_value=0.0,
            value=None,
            step=0.01,
            format="%.3f" if assurance_en_taux else "%.2f",
            placeholder="ex. 0,300" if assurance_en_taux else "ex. 12,50",
            help=(
                "Taux annuel appliqué au capital restant dû en début de chaque période : l'assurance diminue au fil des "
                "remboursements et s'arrête quand le capital est soldé."
                if assurance_en_taux
                else "Montant prélevé chaque mois. En périodicité trimestrielle, semestrielle ou annuelle, il est multiplié "
                "par le nombre de mois de la période. L'assurance court jusqu'au terme du prêt."
            ),
        )

    c1, c2 = st.columns(2)
    mode_frais = c1.selectbox(
        "Autres frais", ["Aucun", "Montant total (€)", "% du montant emprunté"], key=cle("mode_frais"),
        help="Frais répartis également sur toutes les échéances.",
    )
    autres_frais = 0.0
    if mode_frais != "Aucun":
        autres_frais = c2.number_input(
            "Montant total des frais (€)" if mode_frais.startswith("Montant") else "Pourcentage du montant emprunté (%)",
            key=cle("frais_montant" if mode_frais.startswith("Montant") else "frais_taux"),
            min_value=0.0,
            value=None,
            step=0.01,
            format="%.2f",
        ) or 0.0

    jours_exacts = st.checkbox(
        "Calculer les intérêts d'amortissement en jours exacts / 365 (au lieu de taux / 12)", key=cle("jours_exacts"),
        help="Les banques appliquent en général taux / 12 aux échéances d'amortissement.",
    )

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
            importes, remboursements = lire_grand_livre(grand_livre)
        except Exception as erreur:  # fichier inattendu
            st.error(f"Lecture du grand livre impossible : {erreur}")
        else:
            texte, bouton_annuler = st.columns([3, 1], vertical_alignment="center")
            texte.markdown(f"**{len(importes)} déblocage(s) repéré(s) dans le grand livre**, modifiables ci-dessous :")
            if bouton_annuler.button(
                "↺ Annuler", help="Annule vos modifications et revient aux déblocages repérés dans le grand livre.", width="stretch"
            ):
                st.session_state["versions_deblocages"] = st.session_state.get("versions_deblocages", 0) + 1
            deblocages = editer_deblocages(
                pd.DataFrame({"Date": pd.to_datetime([d.date for d in importes]), "Montant (€)": [d.montant for d in importes]}),
                # Nouvelle clé pour chaque fichier importé (ou retour au grand livre) : le tableau repart des lignes repérées.
                cle(f"deblocages_{grand_livre.name}_{grand_livre.size}_{st.session_state.get('versions_deblocages', 0)}"),
                annulable=True,
            )
elif source.startswith("Saisir"):
    deblocages = editer_deblocages(
        pd.DataFrame({"Date": pd.Series(dtype="datetime64[ns]"), "Montant (€)": pd.Series(dtype="float")}), cle("saisie")
    )
elif partiel:
    montant_unique = st.number_input(
        "Montant débloqué (€)", key=cle("montant_unique"), min_value=0.0, value=None, step=100.0, format="%.2f", placeholder="ex. 7 500,00"
    )
    st.caption("Ce montant est considéré comme versé une période avant la 1re échéance.")
else:
    st.caption("Le capital est considéré comme versé en totalité une période avant la 1re échéance.")

montant_debloque = None
if partiel:
    montant_debloque = round(sum(d.montant for d in deblocages), 2) if deblocages else (montant_unique if not source.startswith(("Importer", "Saisir")) else None)

deblocage_tardif = None
if deblocages and premier_paiement:
    premier_deblocage = min(d.date for d in deblocages)
    if premier_deblocage > premier_paiement:
        deblocage_tardif = premier_deblocage
        st.error(
            f"⛔ Le 1er déblocage ({premier_deblocage.strftime('%d/%m/%Y')}) intervient après la date de la 1re "
            f"échéance ({premier_paiement.strftime('%d/%m/%Y')}) : un remboursement ne peut pas précéder le versement "
            "des fonds. Corrigez la date du déblocage ou celle de la 1re échéance : l'échéancier ne peut pas être généré."
        )

depassement = None
montant_verse = round(sum(d.montant for d in deblocages), 2) if deblocages else (montant_debloque or 0)
if capital and montant_verse > capital + 0.005:
    depassement = round(montant_verse - capital, 2)
    st.error(
        f"⛔ Les déblocages ({euros(montant_verse)}) dépassent le montant emprunté ({euros(capital)}) de "
        f"{euros(depassement)}. Corrigez les déblocages ou le montant emprunté : l'échéancier ne peut pas être généré."
    )
elif deblocages:
    total = round(sum(d.montant for d in deblocages), 2)
    libelle = f"**Total des déblocages : {euros(total)}** ({len(deblocages)} déblocage{'s' if len(deblocages) > 1 else ''})"
    if not capital:
        st.info(libelle)
    elif partiel and total < capital - 0.005:
        st.info(f"{libelle} — reste non débloqué : {euros(capital - total)} sur {euros(capital)} empruntés.")
    elif abs(total - capital) <= 0.005:
        st.success(f"{libelle} — égal au montant emprunté.")
        if partiel:
            st.warning("Les fonds sont débloqués en totalité : choisissez « en totalité » à l'étape 1.")
    else:
        st.warning(f"{libelle} — il manque {euros(capital - total)} pour atteindre le montant emprunté ({euros(capital)}).")

echeance_proratisee = False
if len(deblocages) > 1 and premier_paiement and nb_echeances and type_remboursement == "Échéances constantes":
    mois = PERIODICITES[periodicite]
    premiere_amortissement = ajouter_mois(premier_paiement, int(nb_differe) * mois, premier_paiement.day)
    tardifs = [d for d in deblocages if d.date > premiere_amortissement]
    if tardifs:
        st.markdown(
            f"**{len(tardifs)} déblocage{'s' if len(tardifs) > 1 else ''}** "
            f"intervien{'nent' if len(tardifs) > 1 else 't'} après la 1re échéance de remboursement du capital "
            f"({premiere_amortissement.strftime('%d/%m/%Y')}). Jusqu'au dernier déblocage "
            f"({max(d.date for d in tardifs).strftime('%d/%m/%Y')}), les échéances sont…"
        )
        echeance_proratisee = st.radio(
            "Échéances avant le dernier déblocage",
            [
                "totales : échéance constante, calculée sur la totalité du prêt dès la 1re échéance",
                "proratisées : réduites au prorata des fonds déjà versés, puis recalculées après le dernier déblocage",
            ],
            key=cle("echeance_proratisee"),
            label_visibility="collapsed",
        ).startswith("proratisées")

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
if partiel and not montant_debloque:
    manquants.append("le montant débloqué")
if source.startswith("Importer") and not deblocages:
    manquants.append(
        "au moins un déblocage (importez le grand livre ou ajoutez une ligne au tableau)"
        if grand_livre is not None
        else "le grand livre (ou choisissez une autre façon de renseigner les déblocages)"
    )
if manquants:
    st.info("Pour générer l'échéancier, renseignez : " + ", ".join(manquants) + ".")
    st.stop()
if depassement or deblocage_tardif:
    motif = "les déblocages dépassent le montant emprunté" if depassement else "le 1er déblocage est postérieur à la 1re échéance"
    st.error(f"⛔ Échéancier non généré : {motif} (voir l'étape 2).")
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
    echeance_imposee=echeance_banque or None,
    echeance_assurance_comprise=True,
    remboursements_constates=[] if remboursements is None else remboursements["Capital remboursé (€)"].tolist(),
    periodicite=periodicite,
    type_remboursement=type_remboursement,
    interets_jours_exacts=jours_exacts,
    assurance_mensuelle=0.0 if assurance_en_taux else (valeur_assurance or 0.0),
    assurance_taux_crd=(valeur_assurance or 0.0) if assurance_en_taux else 0.0,
    autres_frais=autres_frais,
    autres_frais_en_pourcentage=mode_frais.startswith("%"),
    montant_debloque=montant_debloque,
    partiel_duree_reduite=duree_reduite,
    echeance_proratisee=echeance_proratisee,
)
with st.expander("🎯 Ajuster sur un capital restant dû connu (facultatif)"):
    st.caption(
        "Si vous connaissez le capital restant dû à une date (tableau de la banque, relevé annuel…), saisissez-le : "
        "l'échéancier est recalculé pour retomber exactement sur ce montant."
    )
    c1, c2 = st.columns(2)
    date_reference = c1.date_input("Date", key=cle("date_reference"), value=None, format="DD/MM/YYYY")
    solde_reference = c2.number_input(
        "Capital restant dû à cette date (€)", key=cle("solde_reference"), min_value=0.0, value=None, step=0.01, format="%.2f", placeholder="ex. 21 859,20"
    )
    if date_reference and solde_reference is not None:
        ajustement = ajuster_sur_solde(params, date_reference, solde_reference)
        if ajustement is None:
            st.warning("Ajustement impossible : la date est antérieure à la 1re échéance, ou le type de remboursement ne s'y prête pas.")
        else:
            params = ajustement.parametres
            precision = abs(ajustement.solde_obtenu - solde_reference)
            detail = (
                f"intérêts ajoutés au capital pendant le différé : {euros(params.interets_capitalises_imposes)}"
                if ajustement.levier == "intérêts capitalisés"
                else f"échéance recalculée, assurance comprise : {euros(params.echeance_imposee)}"
            )
            message = (
                f"Échéancier recalculé ({detail}). Capital restant dû après l'échéance du "
                f"{ajustement.date_echeance.strftime('%d/%m/%Y')} : {euros(ajustement.solde_obtenu)}"
            )
            if precision <= 0.005:
                st.success(message + " ✅")
            else:
                st.warning(message + f" — le plus proche possible au centime (écart {euros(precision)}).")

resultat = calculer(params)
echeancier = resultat.echeancier

m1, m2, m3, m4 = st.columns(4)
m1.metric(
    "Échéance (ass. comprise)" if params.assurance_mensuelle or params.assurance_taux_crd else "Échéance",
    euros(echeancier["Échéance (€)"].iloc[params.nb_echeances_differe :].mode().iloc[0]),
)
m2.metric(
    "Nombre d'échéances",
    len(echeancier),
    help=f"Dernière échéance le {echeancier['Date'].iloc[-1].strftime('%d/%m/%Y')}.",
)
m3.metric("Capital remboursé", euros(resultat.capital_amorti))
m4.metric("Total des intérêts", euros(echeancier["Intérêt (€)"].sum()))
rang = resultat.rang_capital_solde
if rang < len(echeancier):
    reste = len(echeancier) - rang
    st.info(
        f"Capital soldé à l'échéance n°{rang} ({echeancier['Date'].iloc[rang - 1].strftime('%d/%m/%Y')}). "
        f"Les {reste} échéance{'s' if reste > 1 else ''} suivante{'s' if reste > 1 else ''}, jusqu'au "
        f"{echeancier['Date'].iloc[-1].strftime('%d/%m/%Y')}, restent dans l'échéancier à 0 € hors assurance et frais."
    )

if params.echeance_imposee and resultat.echeance_constante and (params.assurance_mensuelle or params.assurance_taux_crd):
    st.caption(
        f"Échéance hors assurance déduite de l'échéance saisie ({euros(params.echeance_imposee)}) : "
        f"{euros(resultat.echeance_constante)}."
    )

if params.nb_echeances_differe and interets_capitalises:
    st.caption(
        f"Intérêts ajoutés au capital pendant le différé : {euros(resultat.interets_capitalises_retenus)} — "
        f"dernière échéance : {euros(echeancier['Échéance (€)'].iloc[-1])}."
    )

if remboursements is not None and not remboursements.empty:
    st.subheader("Contrôle avec le grand livre")
    controle = comparer(echeancier, remboursements)
    nature = diagnostic_controle(controle)
    n = len(controle)
    if nature == "capital":
        st.success(f"✅ Les {n} remboursements de capital du grand livre sont retrouvés au centime.")
    elif nature:
        st.info(
            f"ℹ️ Les {n} remboursements du compte 164 correspondent au centime à **{nature}** de l'échéancier, "
            "et non au seul capital : dans la comptabilité, l'échéance a été passée en totalité au compte d'emprunt. "
            "L'échéancier est correct ; c'est l'écriture comptable qui mélange capital et "
            + ("assurance/frais" if "frais" in nature else "assurance" if "assurance" in nature else "intérêts, assurance et frais")
            + " (à reclasser le cas échéant)."
        )
    else:
        st.warning(
            "⚠️ Le capital remboursé en comptabilité diffère de l'échéancier : vérifiez l'échéance et le différé, "
            "ou utilisez l'ajustement sur un capital restant dû connu."
        )
    with st.expander("Détail du contrôle : grand livre / échéancier"):
        st.dataframe(
            tableau_euros(controle[["Date", "Capital remboursé (€)", "Amortissement (€)", "Écart (€)"]].rename(
                columns={"Capital remboursé (€)": "Débit compte 164 (€)", "Amortissement (€)": "Capital échéancier (€)"}
            )),
            hide_index=True,
            width="stretch",
        )

st.subheader("Tableau d'échéancier (fichier Pennylane)")
st.download_button(
    "📥 Télécharger l'échéancier Pennylane (.xlsx)",
    data=exporter_pennylane(params, echeancier),
    file_name="Echeancier_pennylane.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    width="stretch",
)
st.dataframe(tableau_euros(echeancier), width="stretch", hide_index=True, height=420)

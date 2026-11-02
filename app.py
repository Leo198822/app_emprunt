"""Échéancier d'emprunt à déblocages multiples — export au format Pennylane."""

import pandas as pd
import streamlit as st

from dataclasses import replace

from echeancier import (
    PERIODICITES,
    Deblocage,
    ParametresPret,
    RemboursementAnticipe,
    Suspension,
    ajouter_mois,
    ajuster_sur_solde,
    calculer,
    calculer_echeancier,
    capital_constate,
    comparer,
    contient,
    ecarts_controle,
    dates_echeances,
    dates_suspendues,
    diagnostic_controle,
    exporter_pennylane,
    fonds_insuffisants,
    controle_reclassements,
    lire_grand_livre_complet,
)

st.set_page_config(page_title="Échéancier Pennylane", page_icon="📅", layout="centered")

# La traduction automatique du navigateur (Chrome « Traduire cette page ») modifie la page pendant que l'application
# la met à jour, ce qui provoque des erreurs « removeChild » : la page est déclarée en français, à ne pas traduire.
st.html(
    """<script>
    const racine = window.parent.document.documentElement;
    racine.lang = "fr";
    racine.setAttribute("translate", "no");
    racine.classList.add("notranslate");
    if (!window.parent.document.querySelector('meta[name="google"]')) {
        const meta = window.parent.document.createElement("meta");
        meta.name = "google";
        meta.content = "notranslate";
        window.parent.document.head.appendChild(meta);
    }
    // Tableaux modifiables : la cellule en cours de saisie (affichée par-dessus la page) restait fixe à l'écran
    // quand on faisait défiler la page ; elle est décalée du même défilement pour rester sur sa ligne.
    const doc = window.parent.document;
    if (!doc.__celluleSuitDefilement) {
        doc.__celluleSuitDefilement = true;
        const positions = new WeakMap();
        doc.addEventListener("scroll", (evenement) => {
            const zone = evenement.target === doc ? doc.scrollingElement : evenement.target;
            if (!zone || zone.closest?.("#portal")) return;
            const avant = positions.has(zone) ? positions.get(zone) : zone.scrollTop;
            positions.set(zone, zone.scrollTop);
            const decalage = zone.scrollTop - avant;
            if (!decalage) return;
            doc.querySelectorAll("#portal .gdg-style").forEach((cellule) => {
                const total = (parseFloat(cellule.dataset.decalage || "0") || 0) + decalage;
                cellule.dataset.decalage = String(total);
                cellule.style.translate = `0 ${-total}px`;
            });
        }, true);
        // Mémorise la position de défilement avant toute saisie, pour calculer le premier décalage.
        doc.addEventListener("pointerdown", () => {
            const zone = doc.querySelector('[data-testid="stMain"]');
            if (zone) positions.set(zone, zone.scrollTop);
            if (doc.scrollingElement) positions.set(doc.scrollingElement, doc.scrollingElement.scrollTop);
        }, true);
    }
    </script>""",
    unsafe_allow_javascript=True,
)


def nombre(valeur: float) -> str:
    return f"{valeur:,.2f}".replace(",", "\u202f").replace(".", ",")


def euros(valeur: float) -> str:
    return f"{nombre(valeur)} €"


def cle(nom: str) -> str:
    """Clé de widget : change à chaque remise à zéro, ce qui recrée les champs vides."""
    return f"{nom}_{st.session_state.get('reinitialisations', 0)}"


def remettre_a_zero() -> None:
    st.session_state["reinitialisations"] = st.session_state.get("reinitialisations", 0) + 1


def editer_lignes(
    initial: pd.DataFrame, cle_tableau: str, colonnes: dict, requises: list[str], consigne_annuler: str = ""
) -> pd.DataFrame:
    """Tableau modifiable : correction des cellules, ajout de lignes, et suppression des lignes cochées
    (colonne « Sélection ») par le bouton 🗑️. Les corrections et ajouts déjà faits sont conservés."""
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
        column_order=["Sélection", *colonnes],
        column_config={
            "Sélection": st.column_config.CheckboxColumn("☑", default=False, width="small", help="Sélectionner la ligne"),
            **colonnes,
        },
    )
    selection = saisie["Sélection"].fillna(False).astype(bool)
    nb = int(selection.sum())
    with barre:
        consignes, bouton = st.columns([3, 1], vertical_alignment="top")  # loin de la barre d'outils du tableau
        consignes.caption(
            "✏️ **Corriger** : double-cliquez sur une cellule.  \n"
            "🗑️ **Supprimer** : cochez la ou les lignes (colonne ☑), puis cliquez sur « 🗑️ Supprimer ».  \n"
            "➕ **Ajouter** : remplissez la ligne vide en bas du tableau."
            + (f"  \n↺ **Annuler** {consigne_annuler}" if consigne_annuler else "")
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
    return saisie.drop(columns="Sélection")


def lignes_incompletes(saisie: pd.DataFrame, colonne_montant: str, objet: str) -> list[str]:
    """Lignes que le calcul ne peut pas prendre en compte (date manquante ou illisible, date invraisemblable,
    montant manquant), décrites en clair pour l'utilisateur."""
    erreurs = []
    for numero, (_, r) in enumerate(saisie.iterrows(), start=1):
        date_ok, montant_ok = pd.notna(r["Date"]), pd.notna(r[colonne_montant])
        if not date_ok and not montant_ok:
            continue  # ligne vide
        montant = f" de {euros(float(r[colonne_montant]))}" if montant_ok else ""
        if not date_ok:
            erreurs.append(
                f"Ligne n°{numero} ({objet}{montant}) : la date est vide ou n'a pas été reconnue. Double-cliquez sur la "
                "cellule et saisissez-la au format JJ/MM/AAAA (ou choisissez-la dans le calendrier)."
            )
        elif not 1990 <= pd.Timestamp(r["Date"]).year <= 2100:
            jour = pd.Timestamp(r["Date"])
            erreurs.append(
                f"Ligne n°{numero} ({objet}{montant}) : la date du {jour.day:02d}/{jour.month:02d}/{jour.year:04d} n'est "
                "pas vraisemblable. Vérifiez l'année."
            )
        elif not montant_ok and colonne_montant == "Montant (€)" and objet == "déblocage":
            erreurs.append(f"Ligne n°{numero} ({objet} du {pd.Timestamp(r['Date']).strftime('%d/%m/%Y')}) : le montant est vide.")
    return erreurs


def editer_deblocages(initial: pd.DataFrame, cle_tableau: str, annulable: bool = False) -> list[Deblocage]:
    """Tableau modifiable des déblocages (dates et montants) ; les lignes incomplètes sont signalées et ajoutées
    aux erreurs de chronologie (l'échéancier n'est alors pas généré)."""
    saisie = editer_lignes(
        initial,
        cle_tableau,
        {
            "Date": st.column_config.DateColumn("Date du déblocage", format="DD/MM/YYYY", required=True),
            "Montant (€)": st.column_config.NumberColumn("Montant (€)", min_value=0.0, format="%.2f", required=True),
        },
        ["Date", "Montant (€)"],
        "revient aux déblocages du grand livre." if annulable else "",
    )
    erreurs_saisie.extend(lignes_incompletes(saisie, "Montant (€)", "déblocage"))
    saisie = saisie.dropna(subset=["Date", "Montant (€)"])
    saisie = saisie[pd.to_datetime(saisie["Date"]).dt.year.between(1990, 2100)]
    return sorted(
        (Deblocage(pd.Timestamp(r["Date"]).date(), round(float(r["Montant (€)"]), 2)) for _, r in saisie.iterrows()),
        key=lambda d: d.date,
    )


def tableau_euros(df: pd.DataFrame):
    affiche = df.copy()
    affiche["Date"] = pd.to_datetime(affiche["Date"]).dt.strftime("%d/%m/%Y")
    return affiche.style.format({c: nombre for c in affiche.columns if c != "Date"})


def sans_plantage(fonction, *args, **kwargs):
    """Exécute un calcul ; en cas d'erreur imprévue, affiche un message compréhensible au lieu du détail technique
    et arrête la page proprement."""
    try:
        return fonction(*args, **kwargs)
    except Exception:
        st.error(
            "⛔ Le calcul n'a pas pu aboutir avec les informations saisies. Vérifiez en particulier la chronologie des "
            "dates (déblocages, 1re échéance, remboursements anticipés) et les montants. Si le problème persiste, "
            "cliquez sur « 🔄 Remettre à zéro » en haut de la page."
        )
        st.stop()


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

    jour_versement_inclus = st.checkbox(
        "Intérêts d'un déblocage : compter le jour du versement (du 2 au 9 = 8 jours au lieu de 7)",
        key=cle("jour_versement_inclus"),
        help="Pour les fonds versés en cours de période, certaines banques comptent les intérêts à partir du jour du "
        "versement inclus. Cochez si les intérêts de la banque sont légèrement supérieurs à ceux calculés.",
    )
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
deblocages, remboursements, reclassements = [], None, None
erreurs_saisie = []  # lignes de tableau illisibles (date non reconnue, montant manquant…)
if source.startswith("Importer"):
    grand_livre = st.file_uploader(
        "Grand livre du compte 164 exporté de Pennylane (.xlsx)", key=cle("grand_livre"),
        type=["xlsx"],
        help="Les crédits sont repris comme déblocages ; les débits (capital remboursé) servent au contrôle.",
    )
    if grand_livre is not None:
        try:
            importes, remboursements, reclassements = lire_grand_livre_complet(grand_livre)
        except Exception as erreur:  # fichier inattendu
            st.error(
                "⛔ Lecture du grand livre impossible : vérifiez qu'il s'agit bien de l'export Excel (.xlsx) du grand "
                f"livre du compte 164 depuis Pennylane, sans modification de ses colonnes. (Détail : {erreur})"
            )
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
            if not reclassements.empty:
                st.info(
                    "ℹ️ "
                    + ("Écriture" if len(reclassements) == 1 else f"{len(reclassements)} écritures")
                    + " de reclassement des intérêts écartée"
                    + ("" if len(reclassements) == 1 else "s")
                    + " des déblocages : "
                    + " ; ".join(
                        f"{r['Date'].strftime('%d/%m/%Y')} « {r['Libellé']} » {euros(r['Montant (€)'])}"
                        for _, r in reclassements.iterrows()
                    )
                    + ". Les débits du compte comprennent donc les intérêts : ce reclassement est contrôlé sous "
                    "l'échéancier."
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

erreurs_dates = list(erreurs_saisie)  # saisie ou chronologie des déblocages incohérente : pas d'échéancier
if deblocages and premier_paiement:
    premier_deblocage = min(d.date for d in deblocages)
    if premier_deblocage > premier_paiement:
        erreurs_dates.append(
            f"Le 1er déblocage ({premier_deblocage.strftime('%d/%m/%Y')}) intervient après la date de la 1re "
            f"échéance ({premier_paiement.strftime('%d/%m/%Y')}) : un remboursement ne peut pas précéder le "
            "versement des fonds. Corrigez la date du déblocage ou celle de la 1re échéance."
        )
    if nb_echeances:
        derniere_echeance = ajouter_mois(
            premier_paiement, (int(nb_echeances) - 1) * PERIODICITES[periodicite], premier_paiement.day
        )
        for d in deblocages:
            if d.date > derniere_echeance:
                erreurs_dates.append(
                    f"Le déblocage du {d.date.strftime('%d/%m/%Y')} ({euros(d.montant)}) est postérieur à la "
                    f"dernière échéance du prêt ({derniere_echeance.strftime('%d/%m/%Y')}) : des fonds ne peuvent pas "
                    "être versés après la fin du remboursement. Vérifiez l'année de ce déblocage, le nombre "
                    "d'échéances ou la date de la 1re échéance."
                )
for erreur in erreurs_dates:
    st.error(f"⛔ {erreur}")

depassement = manque = None
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
    elif not erreurs_saisie:  # une ligne illisible est déjà signalée : pas de second message sur le total
        manque = round(capital - total, 2)
        st.error(
            f"⛔ {libelle} : il manque {euros(manque)} pour atteindre le montant emprunté ({euros(capital)}). "
            "Ajoutez les déblocages manquants (même à venir, à leur date prévue), corrigez le montant emprunté, ou "
            "choisissez « partiellement » à l'étape 1 si une partie des fonds ne sera jamais versée."
        )

echeance_proratisee = interets_fonds_verses = False
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
        mode_tardifs = st.radio(
            "Échéances avant le dernier déblocage",
            [
                "totales : échéance constante, calculée sur la totalité du prêt dès la 1re échéance",
                "proratisées : réduites au prorata des fonds déjà versés, puis recalculées après le dernier déblocage",
                "capital du prêt complet, intérêts sur les seuls fonds versés : capital de l'échéance constante du prêt "
                "complet, intérêts calculés sur les fonds déjà versés (échéance réduite jusqu'au dernier déblocage)",
            ],
            key=cle("echeance_proratisee"),
            index=1,  # proratisation par défaut, en fonction des dates de déblocage
            label_visibility="collapsed",
        )
        echeance_proratisee = mode_tardifs.startswith("proratisées")
        interets_fonds_verses = mode_tardifs.startswith("capital du prêt complet")

# --- Suspensions d'échéances ------------------------------------------------------------
# Libellés courts : ils doivent tenir dans la colonne du tableau (le détail est expliqué sous le tableau).
TYPES_SUSPENSION = {
    "Capital seul": True,
    "Capital + intérêts capitalisés": False,
    "Capital + intérêts reportés": False,
}
etape = 3
suspensions, suspension_allonge, interets_reportes_etales, erreurs_suspensions = [], True, True, []
if st.checkbox(
    "Le prêt a fait l'objet d'une **suspension d'échéances** (report, pause des remboursements)", key=cle("avec_suspension")
):
    st.header(f"{etape}. Suspension d'échéances", divider="gray")
    etape += 1
    saisie_s = editer_lignes(
        pd.DataFrame({
            "Date": pd.Series(dtype="datetime64[ns]"),
            "Nombre": pd.Series(dtype="Int64"),
            "Type": pd.Series(dtype="object"),
        }),
        cle("suspensions"),
        {
            "Date": st.column_config.DateColumn(
                "1re échéance", format="DD/MM/YYYY", required=True, width=165,
                help="Date de la 1re échéance suspendue, non prélevée (ou date de début de la suspension).",
            ),
            "Nombre": st.column_config.NumberColumn(
                "Nb d'échéances", min_value=1, max_value=600, step=1, format="%d", required=True, default=1, width=125,
                help="Nombre d'échéances consécutives suspendues.",
            ),
            "Type": st.column_config.SelectboxColumn(
                "Type de suspension", options=list(TYPES_SUSPENSION), default=next(iter(TYPES_SUSPENSION)), required=True, width=300,
                help="Capital seul : seuls les intérêts (et l'assurance) sont prélevés. Capital et intérêts : rien n'est "
                "prélevé hors assurance ; les intérêts sont soit ajoutés au capital restant dû (ils portent alors "
                "intérêt), soit reportés sans être capitalisés et payés après la reprise.",
            ),
        },
        ["Date", "Nombre"],
    )
    for numero, (_, r) in enumerate(saisie_s.iterrows(), start=1):
        date_ok, nombre_ok = pd.notna(r["Date"]), pd.notna(r["Nombre"])
        if not date_ok and not nombre_ok:
            continue  # ligne vide
        if not date_ok:
            erreurs_suspensions.append(f"ligne n°{numero} : la date de la 1re échéance suspendue est vide ou n'a pas été reconnue")
        elif not 1990 <= pd.Timestamp(r["Date"]).year <= 2100:
            erreurs_suspensions.append(f"ligne n°{numero} : la date du {pd.Timestamp(r['Date']).strftime('%d/%m/%Y')} n'est pas vraisemblable")
        elif not nombre_ok or int(r["Nombre"]) < 1:
            erreurs_suspensions.append(f"ligne n°{numero} : indiquez le nombre d'échéances suspendues")
        else:
            type_su = r["Type"] if pd.notna(r["Type"]) else ""
            suspensions.append(Suspension(
                pd.Timestamp(r["Date"]).date(), int(r["Nombre"]),
                TYPES_SUSPENSION.get(type_su, True), interets_reportes=type_su.endswith("reportés"),
            ))
    st.caption(
        "**Type de suspension** :  \n"
        "• **Capital seul** : l'échéance se limite aux intérêts (plus l'assurance et les frais).  \n"
        "• **Capital + intérêts capitalisés** : rien n'est prélevé hors assurance et frais ; les intérêts sont ajoutés "
        "au capital restant dû (amortissement négatif dans le fichier Pennylane, comme pendant un différé) et "
        "l'échéance est recalculée à la reprise.  \n"
        "• **Capital + intérêts reportés** : rien n'est prélevé hors assurance et frais ; le capital restant dû ne "
        "bouge pas et les intérêts de la suspension (à 0 dans l'échéancier) sont payés après la reprise, en plus "
        "des intérêts normaux."
    )
    if any(su.reporte for su in suspensions):
        interets_reportes_etales = st.radio(
            "Les intérêts reportés sont payés…",
            [
                "étalés sur les échéances restantes",
                "en une fois, avec la 1re échéance après la reprise",
            ],
            key=cle("interets_reportes_etales"),
            horizontal=True,
        ).startswith("étalés")
    suspension_allonge = st.radio(
        "À la fin de la suspension…",
        [
            "la durée du prêt est allongée du nombre d'échéances suspendues",
            "la durée du prêt est maintenue : l'échéance est recalculée sur les échéances restantes",
        ],
        key=cle("suspension_allonge"),
    ).startswith("la durée du prêt est allongée")
    if suspensions and premier_paiement and nb_echeances:
        mois = PERIODICITES[periodicite]
        echeances_offre = [ajouter_mois(premier_paiement, k * mois, premier_paiement.day) for k in range(int(nb_echeances))]
        premiere_amortissement = echeances_offre[min(int(nb_differe), len(echeances_offre) - 1)]
        for su in suspensions:
            debut = next((k for k, d in enumerate(echeances_offre) if d >= su.date), None)
            if debut is None:
                erreurs_suspensions.append(
                    f"la suspension du {su.date.strftime('%d/%m/%Y')} est postérieure à la dernière échéance "
                    f"({echeances_offre[-1].strftime('%d/%m/%Y')})"
                )
            elif debut < int(nb_differe):
                erreurs_suspensions.append(
                    f"la suspension du {su.date.strftime('%d/%m/%Y')} commence pendant le différé : elle doit porter sur "
                    f"des échéances de remboursement du capital (à partir du {premiere_amortissement.strftime('%d/%m/%Y')})"
                )
            elif not suspension_allonge and debut + su.nb_echeances > len(echeances_offre) - 1:
                erreurs_suspensions.append(
                    f"la suspension du {su.date.strftime('%d/%m/%Y')} ({su.nb_echeances} échéance(s)) atteint la dernière "
                    f"échéance du prêt ({echeances_offre[-1].strftime('%d/%m/%Y')}) : avec une durée maintenue, il doit "
                    "rester au moins une échéance pour rembourser le capital"
                )
    for erreur in erreurs_suspensions:
        st.error(f"⛔ Suspension d'échéances : {erreur}.")
# Nombre d'échéances de l'échéancier, allongé des échéances suspendues le cas échéant.
nb_echeances_total = int(nb_echeances or 0) + (
    sum(su.nb_echeances for su in suspensions) if suspension_allonge else 0
)

# --- Remboursements anticipés -----------------------------------------------------------
anticipes, anticipe_reduit_duree, erreurs_anticipes = [], True, []
if st.checkbox("Le prêt a fait l'objet d'un **remboursement anticipé**", key=cle("avec_anticipe")):
    st.header(f"{etape}. Remboursements anticipés", divider="gray")
    saisie_ra = editer_lignes(
        pd.DataFrame({
            "Date": pd.Series(dtype="datetime64[ns]"),
            "Montant (€)": pd.Series(dtype="float"),
            "Total": pd.Series(dtype="bool"),
            "Indemnités (€)": pd.Series(dtype="float"),
        }),
        cle("anticipes"),
        {
            "Date": st.column_config.DateColumn("Date du remboursement", format="DD/MM/YYYY", required=True),
            "Montant (€)": st.column_config.NumberColumn(
                "Capital remboursé (€)", min_value=0.0, format="%.2f", help="Laisser vide si le remboursement est total."
            ),
            "Total": st.column_config.CheckboxColumn(
                "Total", default=False, help="Cochez si tout le capital restant dû est remboursé (prêt soldé)."
            ),
            "Indemnités (€)": st.column_config.NumberColumn(
                "Indemnités (€)", min_value=0.0, format="%.2f", help="Indemnités de remboursement anticipé (IRA), facultatif."
            ),
        },
        ["Date"],
    )
    erreurs_anticipes.extend(e[0].lower() + e[1:].rstrip(".") for e in lignes_incompletes(saisie_ra, "Montant (€)", "remboursement"))
    saisie_ra = saisie_ra.dropna(subset=["Date"])
    saisie_ra = saisie_ra[pd.to_datetime(saisie_ra["Date"]).dt.year.between(1990, 2100)]
    for _, r in saisie_ra.iterrows():
        total_ra = bool(r["Total"]) if pd.notna(r["Total"]) else False
        montant_ra = float(r["Montant (€)"]) if pd.notna(r["Montant (€)"]) else 0.0
        if not total_ra and montant_ra <= 0:
            continue  # ligne incomplète
        anticipes.append(RemboursementAnticipe(
            pd.Timestamp(r["Date"]).date(), round(montant_ra, 2), total_ra,
            round(float(r["Indemnités (€)"]), 2) if pd.notna(r["Indemnités (€)"]) else 0.0,
        ))
    st.caption(
        "Le remboursement est intégré à l'échéance qui suit sa date (capital remboursé dans la colonne Amortissement, "
        "indemnités dans Autres frais). Après un remboursement total, l'échéancier s'arrête."
    )
    if any(not ra.total for ra in anticipes):
        anticipe_reduit_duree = st.radio(
            "Après un remboursement partiel…",
            [
                "l'échéance est maintenue : la durée est réduite",
                "la durée est maintenue : l'échéance est recalculée",
            ],
            key=cle("anticipe_reduit_duree"),
        ).startswith("l'échéance est maintenue")
    if anticipes and premier_paiement and nb_echeances:
        mois = PERIODICITES[periodicite]
        derniere = ajouter_mois(premier_paiement, (nb_echeances_total - 1) * mois, premier_paiement.day)
        premiere_amortissement = ajouter_mois(premier_paiement, int(nb_differe) * mois, premier_paiement.day)
        for ra in anticipes:
            if ra.date > derniere:
                erreurs_anticipes.append(
                    f"le remboursement du {ra.date.strftime('%d/%m/%Y')} est postérieur à la dernière échéance "
                    f"({derniere.strftime('%d/%m/%Y')})"
                )
            elif ra.date <= premier_paiement or (nb_differe and ra.date < premiere_amortissement):
                erreurs_anticipes.append(
                    f"le remboursement du {ra.date.strftime('%d/%m/%Y')} précède la 1re échéance de remboursement "
                    f"du capital ({premiere_amortissement.strftime('%d/%m/%Y')})"
                )
        for ra in anticipes:
            if ra.total and (apres := [d for d in deblocages if d.date > ra.date]):
                erreurs_anticipes.append(
                    f"le remboursement total du {ra.date.strftime('%d/%m/%Y')} précède le déblocage du "
                    f"{apres[0].date.strftime('%d/%m/%Y')} : des fonds ne peuvent pas être versés une fois le prêt soldé"
                )
    for erreur in erreurs_anticipes:
        st.error(f"⛔ Remboursement anticipé : {erreur}.")

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
if source.startswith("Saisir") and not deblocages and not erreurs_saisie:
    manquants.append("au moins un déblocage (remplissez une ligne du tableau de l'étape 2)")
if manquants:
    st.info("Pour générer l'échéancier, renseignez : " + ", ".join(manquants) + ".")
    st.stop()
if erreurs_suspensions:
    st.error("⛔ Échéancier non généré : corrigez les suspensions d'échéances (voir ci-dessus).")
    st.stop()
if erreurs_anticipes:
    st.error("⛔ Échéancier non généré : corrigez les remboursements anticipés (voir ci-dessus).")
    st.stop()
if depassement or manque or erreurs_dates:
    motif = (
        "les déblocages dépassent le montant emprunté"
        if depassement
        else "les déblocages n'atteignent pas le montant emprunté"
        if manque
        else "les dates des déblocages ne sont pas cohérentes avec celles des échéances"
    )
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
    interets_fonds_verses=interets_fonds_verses,
    jour_versement_inclus=jour_versement_inclus,
    remboursements_anticipes=anticipes,
    anticipe_reduit_duree=anticipe_reduit_duree,
    suspensions=suspensions,
    suspension_allonge_duree=suspension_allonge,
    interets_reportes_etales=interets_reportes_etales,
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
    derniere_date = dates_echeances(params)[-1]
    if date_reference and date_reference > derniere_date:
        st.error(
            f"⛔ Ajustement impossible : la date saisie ({date_reference.strftime('%d/%m/%Y')}) est postérieure à la "
            f"dernière échéance du prêt ({derniere_date.strftime('%d/%m/%Y')}). Vérifiez l'année."
        )
    elif date_reference and solde_reference is not None:
        ajustement = sans_plantage(ajuster_sur_solde, params, date_reference, solde_reference)
        if ajustement is None:
            st.error("⛔ Ajustement impossible : la date saisie est antérieure à la 1re échéance.")
        elif not ajustement.possible:
            bas, haut = ajustement.fourchette or (ajustement.solde_obtenu, ajustement.solde_obtenu)
            st.error(
                f"⛔ Ajustement impossible : à l'échéance du {ajustement.date_echeance.strftime('%d/%m/%Y')}, le capital "
                + (f"restant dû ne peut être que de {euros(bas)}" if abs(haut - bas) < 0.01 else f"restant dû ne peut varier qu'entre {euros(bas)} et {euros(haut)}")
                + f" avec ces paramètres (saisi : {euros(solde_reference)}). Vérifiez la date, le montant, le taux, le différé "
                "ou l'échéance saisie. L'échéancier n'a pas été modifié."
            )
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

# Contrôle avec le grand livre : établi sur l'échéancier calculé ; si l'utilisateur choisit d'appliquer les
# montants du grand livre, l'échéancier est régénéré avec le capital constaté.
cle_appliquer = cle("appliquer_grand_livre")
cle_interets_gl = cle("grand_livre_interets_inclus")
CHOIX_INTERETS_GL = ["le capital seul (hors intérêts)", "le capital et les intérêts"]
controle_initial = nature_initiale = None
grand_livre_applique = interets_inclus_gl = False
if remboursements is not None and not remboursements.empty:
    controle_initial = sans_plantage(lambda: comparer(calculer_echeancier(params), remboursements))
    nature_initiale = diagnostic_controle(controle_initial)
    # Intérêts compris dans les débits du compte 164 : choix de l'utilisateur (affiché plus bas), par défaut
    # d'après ce que les débits contiennent.
    # Un reclassement des intérêts au crédit du compte 164 montre que les débits comprennent les intérêts.
    avec_reclassement = reclassements is not None and not reclassements.empty
    choix_defaut_gl = CHOIX_INTERETS_GL[1 if contient(nature_initiale, "intérêts") or avec_reclassement else 0]
    interets_inclus_gl = st.session_state.get(cle_interets_gl, choix_defaut_gl) == CHOIX_INTERETS_GL[1]
    grand_livre_applique = nature_initiale != "capital" and st.session_state.get(cle_appliquer, False)
    if grand_livre_applique:
        montants_gl = capital_constate(controle_initial, nature_initiale, interets_inclus_gl)
        params = replace(
            params, **({"echeances_constatees": montants_gl} if interets_inclus_gl else {"capital_impose": montants_gl})
        )

# Modifications faites par l'utilisateur directement dans le tableau d'échéancier (par date d'échéance).
cle_corrections = cle("corrections")
corrections = st.session_state.setdefault(cle_corrections, {})
# Historique des états précédents des corrections : une entrée par modification validée dans le tableau.
historique = st.session_state.setdefault(cle_corrections + "_historique", [])


def annuler_derniere_modification() -> None:
    if historique:
        st.session_state[cle_corrections] = historique.pop()
        st.session_state[cle_corrections + "_version"] = st.session_state.get(cle_corrections + "_version", 0) + 1


def annuler_toutes_les_modifications() -> None:
    st.session_state[cle_corrections] = {}
    historique.clear()
    st.session_state[cle_corrections + "_version"] = st.session_state.get(cle_corrections + "_version", 0) + 1


def boutons_annulation(zone_derniere, zone_tout) -> None:
    """« Annuler la dernière modification » et « Tout annuler », affichés s'il y a des modifications."""
    if historique:
        zone_derniere.button(
            "↶ Annuler la dernière modification",
            help="Revient à l'échéancier tel qu'il était avant votre dernière saisie dans le tableau.",
            on_click=annuler_derniere_modification,
            width="stretch",
        )
    if corrections:
        zone_tout.button(
            f"↺ Tout annuler ({len(historique)})" if historique else "↺ Tout annuler",
            help="Annule toutes vos modifications du tableau et revient à l'échéancier calculé.",
            on_click=annuler_toutes_les_modifications,
            width="stretch",
        )

if corrections:
    params = replace(params, corrections=corrections)

if (
    params.echeance_imposee and type_remboursement == "Échéances constantes"
    and params.assurance_sur(params.capital_effectif) >= params.echeance_imposee
):
    st.error(
        f"⛔ Échéancier non généré : l'assurance ({euros(params.assurance_sur(params.capital_effectif))} par échéance) "
        f"est supérieure ou égale à l'échéance saisie assurance comprise ({euros(params.echeance_imposee)}). "
        "Vérifiez le montant de l'échéance (étape 1) et celui de l'assurance (Options) : l'assurance se saisit par mois."
    )
    st.stop()
resultat = sans_plantage(calculer, params)
echeancier = resultat.echeancier
if insuffisance := fonds_insuffisants(params, echeancier):
    tardifs = insuffisance.deblocages_tardifs
    st.error(
        f"⛔ Échéancier non généré : à l'échéance du {insuffisance.date_echeance.strftime('%d/%m/%Y')}, le capital "
        f"remboursé dépasserait de {euros(insuffisance.depassement)} les fonds versés à cette date"
        + (
            " : le" + ("s déblocages du " if len(tardifs) > 1 else " déblocage du ")
            + ", du ".join(d.date.strftime('%d/%m/%Y') for d in tardifs)
            + (" arrivent" if len(tardifs) > 1 else " arrive")
            + " trop tard par rapport au rythme de remboursement"
            if tardifs
            else ""
        )
        + ". Vérifiez les dates des déblocages"
        + (", ou choisissez des échéances « proratisées » à l'étape 2" if len(deblocages) > 1 and not echeance_proratisee and type_remboursement == "Échéances constantes" else "")
        + (", ou annulez vos modifications du tableau" if corrections else "")
        + "."
    )
    boutons_annulation(*st.columns(2))
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric(
    "Échéance (ass. comprise)" if params.assurance_mensuelle or params.assurance_taux_crd else "Échéance",
    # Échéance la plus fréquente, hors échéances à 0 (capital soldé avant le terme).
    euros(echeances_payees.mode().iloc[0] if not (echeances_payees := echeancier["Échéance (€)"].iloc[
        params.nb_echeances_differe :].loc[lambda x: x > 0]).empty else 0.0),
)
m2.metric(
    "Nombre d'échéances",
    len(echeancier),
    help=f"Dernière échéance le {echeancier['Date'].iloc[-1].strftime('%d/%m/%Y')}.",
)
capitalises_rembourses = round(resultat.capital_amorti - params.capital_effectif, 2)
m3.metric(
    "Capital remboursé",
    euros(params.capital_effectif),
    help="Capital versé, jamais plus que le montant emprunté"
    + (f" ; s'y ajoutent {euros(capitalises_rembourses)} d'intérêts capitalisés pendant le différé." if capitalises_rembourses > 0 else "."),
)
m4.metric("Total des intérêts", euros(echeancier["Intérêt (€)"].sum()))
for jour_ra, montant_ra, indemnites_ra in resultat.anticipes:
    st.info(
        f"💶 Remboursement anticipé de {euros(montant_ra)} intégré à l'échéance du {jour_ra.strftime('%d/%m/%Y')}"
        + (f", avec {euros(indemnites_ra)} d'indemnités (colonne Autres frais)" if indemnites_ra else "")
        + "."
    )
if resultat.anticipes and len(echeancier) < len(dates_echeances(params)):
    st.info(
        f"Prêt soldé le {echeancier['Date'].iloc[-1].strftime('%d/%m/%Y')} : {len(echeancier)} échéances au lieu de "
        f"{len(dates_echeances(params))}."
    )
suspendues = dates_suspendues(params)
if suspendues:
    lignes_suspendues = echeancier[echeancier["Date"].isin(list(suspendues))]
    ajoutes = round(-float(lignes_suspendues["Amortissement (€)"].clip(upper=0).sum()), 2)
    st.info(
        f"⏸️ {len(suspendues)} échéance{'s' if len(suspendues) > 1 else ''} suspendue{'s' if len(suspendues) > 1 else ''} "
        f"({', '.join(d.strftime('%d/%m/%Y') for d in suspendues)})"
        + (
            " : " + " ; ".join(filter(None, [
                f"{euros(ajoutes)} d'intérêts ajoutés au capital" if ajoutes else "",
                f"{euros(resultat.interets_reportes)} d'intérêts reportés (non capitalisés), payés "
                + ("en plus des intérêts des échéances restantes" if params.interets_reportes_etales
                   else "avec la 1re échéance après la reprise")
                if resultat.interets_reportes else "",
            ])) if ajoutes or resultat.interets_reportes else " : intérêts payés, capital non remboursé"
        )
        + (
            f". Durée allongée : {params.nb_echeances_total} échéances au lieu de {params.nb_echeances}."
            if params.suspension_allonge_duree
            else ". Durée maintenue : l'échéance est recalculée à la reprise."
        )
    )

rang = resultat.rang_capital_solde
if rang < len(echeancier):
    reste = len(echeancier) - rang
    st.info(
        f"Capital soldé à l'échéance n°{rang} ({echeancier['Date'].iloc[rang - 1].strftime('%d/%m/%Y')}). "
        + (
            f"Les {reste} échéances suivantes, jusqu'au {echeancier['Date'].iloc[-1].strftime('%d/%m/%Y')}, restent"
            if reste > 1
            else f"L'échéance suivante ({echeancier['Date'].iloc[-1].strftime('%d/%m/%Y')}) reste"
        )
        + " dans l'échéancier à 0 € hors assurance et frais."
    )

amortissement = echeancier.iloc[params.nb_echeances_differe : -1]
amortissement = amortissement[~amortissement["Date"].isin(list(suspendues))]  # suspensions : pas de capital, c'est voulu
if ((amortissement["Amortissement (€)"] <= 0) & (amortissement["Solde (€)"] > 0.005)).any():
    st.warning(
        f"⚠️ L'échéance est trop faible pour couvrir les intérêts : certaines échéances ne remboursent aucun capital, "
        f"et la dernière échéance ({euros(echeancier['Échéance (€)'].iloc[-1])}) solde le capital restant. "
        "Vérifiez le montant de l'échéance saisi."
    )

if echeance_banque and type_remboursement == "Amortissement constant":
    st.caption(
        f"L'échéance saisie ({euros(echeance_banque)}) n'est pas utilisée : en amortissement constant, le capital est "
        "remboursé par parts égales et l'échéance diminue au fil des intérêts."
    )
elif echeance_banque and rang <= params.nb_echeances_differe + 1 < params.nb_echeances:
    st.warning(
        f"⚠️ L'échéance saisie ({euros(echeance_banque)}) rembourse tout le capital dès la 1re échéance : vérifiez "
        "le montant (échéance d'une période, assurance comprise)."
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

st.subheader("Contrôler l'échéancier avant téléchargement")
st.caption("Comparez l'échéancier au tableau d'amortissement de la banque et corrigez-le si besoin, en deux temps.")

# 1. Grand livre ------------------------------------------------------------------------------------------
st.markdown("##### 1. Appliquez les montants du grand livre")
ecarts_restants = None  # None : pas de grand livre ; True / False : écarts avec le grand livre après l'étape 1
if controle_initial is None:
    st.caption(
        "Aucun grand livre importé : importez celui du compte d'emprunt à l'étape 2 pour comparer le capital "
        "remboursé en comptabilité à l'échéancier et l'appliquer. Sinon, passez directement à l'étape 2 ci-dessous."
    )
else:
    nature, n = nature_initiale, len(controle_initial)
    retires = [e for e in ("assurance", "frais") if contient(nature, e)]
    hors = f" (hors {' et '.join(retires)})" if retires else ""
    if nature == "capital":
        st.success(f"✅ Les {n} remboursements de capital du grand livre correspondent déjà à l'échéancier : rien à appliquer.")
    else:
        if grand_livre_applique:
            pass  # le message de réussite, sous l'interrupteur, suffit
        elif nature:
            st.info(
                f"ℹ️ Les {n} débits du compte 164 correspondent à **{nature}** de l'échéancier"
                + (f" : {' et '.join(retires)} en sont retirés avant d'appliquer les montants." if retires else ".")
            )
        else:
            st.warning(f"⚠️ Les montants remboursés en comptabilité ({n} échéances) diffèrent de l'échéancier.")
        st.radio(
            "Les montants du grand livre (débits du compte 164) comprennent…",
            CHOIX_INTERETS_GL,
            index=CHOIX_INTERETS_GL.index(choix_defaut_gl),
            key=cle_interets_gl,
            horizontal=True,
            help="Capital seul : chaque débit est repris comme capital remboursé. Capital et intérêts : chaque débit "
            "est repris comme échéance (intérêts + capital) ; le capital en est déduit avec les intérêts calculés "
            "de la ligne. Le choix proposé par défaut est déduit des montants.",
        )
        st.toggle(
            f"Appliquer les montants du grand livre à l'échéancier{hors}",
            key=cle_appliquer,
            help="Reprend les montants comptabilisés au compte 164 pour chaque échéance concernée ; "
            "les échéances suivantes sont recalculées sur le capital restant dû pour finir au terme. "
            "Désactivez pour revenir au calcul théorique.",
        )
        if grand_livre_applique:
            nb_gl = len(params.echeances_constatees or params.capital_impose)
            st.success(
                f"✅ Montants du grand livre appliqués à {nb_gl} échéance(s) "
                + (
                    "comme échéances intérêts compris : le capital vaut le débit moins les intérêts calculés"
                    if interets_inclus_gl else "comme capital remboursé"
                )
                + ". Les échéances suivantes sont recalculées pour solder le prêt au terme."
            )
    controle = sans_plantage(comparer, echeancier, remboursements)
    controle["Écart (€)"] = ecarts_controle(controle, nature, interets_inclus_gl)
    if reclassements is not None and not reclassements.empty:
        for _, r in controle_reclassements(echeancier, reclassements).iterrows():
            periode = f"du {r['Du'].strftime('%d/%m/%Y')} " if r["Du"] is not None else ""
            texte = (
                f"Reclassement des intérêts du {r['Date'].strftime('%d/%m/%Y')} : {euros(r['Reclassé (€)'])} ; intérêts "
                f"de l'échéancier {periode}au {r['Date'].strftime('%d/%m/%Y')} : {euros(r['Intérêts échéancier (€)'])}"
            )
            if abs(r["Écart (€)"]) <= 0.05:
                st.success(f"✅ {texte}.")
            else:
                st.warning(
                    f"⚠️ {texte} — écart de {euros(r['Écart (€)'])}. Vérifiez l'écriture de reclassement : si elle est "
                    "trop forte, le capital restant dû au compte 164 est sous-évalué d'autant (et les intérêts en "
                    "charge surévalués)."
                )
    ecarts_restants = bool((controle["Écart (€)"].abs() > 0.02).any())
    with st.expander("Détail : grand livre / échéancier"):
        colonnes_detail = ["Date", "Capital remboursé (€)", "Amortissement (€)"]
        if interets_inclus_gl:
            colonnes_detail.append("Intérêt (€)")
        st.dataframe(
            tableau_euros(controle[colonnes_detail + ["Écart (€)"]].rename(columns={
                "Capital remboursé (€)": "Débit compte 164 (€)",
                "Amortissement (€)": "Capital échéancier (€)",
                "Intérêt (€)": "Intérêts échéancier (€)",
            })),
            hide_index=True,
            width="stretch",
        )

# 2. Modification directe ---------------------------------------------------------------------------------
COLONNES_MODIFIABLES = {
    "Intérêt (€)": "interet",
    "Assurance (€)": "assurance",
    "Autres frais (€)": "frais",
    "Amortissement (€)": "amortissement",
}
st.markdown("##### 2. S'il reste des écarts, modifiez directement l'échéancier")
if ecarts_restants:
    st.warning(
        "⚠️ Il reste des écarts avec le grand livre (voir le détail ci-dessus) : corrigez-les directement dans le "
        "tableau ci-dessous."
    )
elif ecarts_restants is False:
    st.caption(
        "L'échéancier correspond au grand livre. S'il reste des écarts avec le tableau de la banque "
        "(intérêts, échéance, capital restant dû), corrigez-les directement dans le tableau ci-dessous."
    )
st.info(
    "✏️ **Modifier** : double-cliquez sur un intérêt, une assurance, des frais, un capital ou une échéance, saisissez "
    "le bon montant puis appuyez sur Entrée. Les échéances suivantes sont ajustées pour solder le prêt au terme (un "
    "intérêt modifié conserve l'échéance ; une échéance modifiée fixe le capital).  \n"
    "➕ 🗑️ **Ajouter ou supprimer des échéances** : sous le tableau. L'échéance est alors répartie sur le nouveau "
    "nombre d'échéances."
)
supprimees_tableau = sorted(d for d, c in corrections.items() if c.get("supprimee"))
nb_ajoutees = sum(1 for c in corrections.values() if c.get("ajoutee"))
nb_modifiees = len(corrections) - len(supprimees_tableau) - nb_ajoutees
if corrections or historique:
    consignes, zone_derniere, zone_tout = st.columns([2, 1.3, 1], vertical_alignment="center")
    if corrections:
        consignes.caption(" · ".join(filter(None, [
            f"✏️ {nb_modifiees} modifiée{'s' if nb_modifiees > 1 else ''}" if nb_modifiees else "",
            f"➕ {nb_ajoutees} ajoutée{'s' if nb_ajoutees > 1 else ''}" if nb_ajoutees else "",
            f"🗑️ {len(supprimees_tableau)} supprimée{'s' if len(supprimees_tableau) > 1 else ''}" if supprimees_tableau else "",
        ])))
    boutons_annulation(zone_derniere, zone_tout)
if message_tableau := st.session_state.pop(cle_corrections + "_message", None):
    st.warning(f"⚠️ {message_tableau}")
version_tableau = st.session_state.setdefault(cle_corrections + "_version", 0)
cle_tableau = f"{cle_corrections}_tableau_{version_tableau}"


def etat_ligne(jour) -> str:
    correction = corrections.get(jour, {})
    if correction.get("ajoutee"):
        return "➕"
    return "✏️" if correction else ""


affiche = echeancier.assign(État=[etat_ligne(d) for d in echeancier["Date"]])
# Échéancier : pas de tri ni de menu par colonne (un clic sur l'en-tête est sans effet), ni barre d'outils.
st.html(
    """<style>
    .st-key-tableau_echeancier [data-testid="stElementToolbar"] { display: none !important; }
    .st-key-tableau_echeancier [data-testid="stDataFrame"] { position: relative; }
    .st-key-tableau_echeancier [data-testid="stDataFrame"]::after {
        content: ""; position: absolute; top: 0; left: 0; right: 0; height: 36px; z-index: 10; cursor: default;
    }
    </style>"""
)
with st.container(key="tableau_echeancier"):
    st.data_editor(
        affiche,
        key=cle_tableau,
        width="stretch",
        hide_index=True,
        height=420,
        num_rows="fixed",
        column_order=["État", "Date", *COLONNES_MODIFIABLES, "Échéance (€)", "Solde (€)"],
        disabled=["État", "Date", "Solde (€)"],
        column_config={
            "État": st.column_config.TextColumn(" ", width=34, help="✏️ ligne modifiée · ➕ échéance ajoutée"),
            "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY", width=95),
            "Intérêt (€)": st.column_config.NumberColumn("Intérêt", min_value=0.0, format="%.2f", width=80),
            "Assurance (€)": st.column_config.NumberColumn("Assurance", min_value=0.0, format="%.2f", width=90),
            "Autres frais (€)": st.column_config.NumberColumn("Frais", min_value=0.0, format="%.2f", width=70),
            "Amortissement (€)": st.column_config.NumberColumn("Capital", min_value=0.0, format="%.2f", width=90, help="Amortissement"),
            "Échéance (€)": st.column_config.NumberColumn("Échéance", min_value=0.0, format="%.2f", width=90),
            "Solde (€)": st.column_config.NumberColumn("Solde", format="%.2f", width=100),
        },
    )
modifications = st.session_state.get(cle_tableau, {}).get("edited_rows", {})


def enregistrer(nouvelles: dict, message: str | None = None) -> None:
    """Remplace les corrections (historique pour « Annuler ») et recharge le tableau."""
    historique.append({jour: dict(valeurs) for jour, valeurs in corrections.items()})
    corrections.clear()
    corrections.update(nouvelles)
    if message:
        st.session_state[cle_corrections + "_message"] = message
    st.session_state[cle_corrections + "_version"] = version_tableau + 1


def refuser(message: str) -> None:
    st.session_state[cle_corrections + "_message"] = message
    st.session_state[cle_corrections + "_version"] = version_tableau + 1


if modifications:
    avant = {jour: dict(valeurs) for jour, valeurs in corrections.items()}  # pour « Annuler la dernière modification »
    ignorees, refusees = 0, []
    # Montant saisi invraisemblable (négatif, ou supérieur au capital et aux intérêts de tout le prêt) : refusé.
    plafond_saisie = round(params.capital + resultat.interets_capitalises_retenus + echeancier["Intérêt (€)"].sum(), 2)
    for ligne, valeurs in modifications.items():
        actuelle = echeancier.iloc[int(ligne)]
        jour = actuelle["Date"]
        correction = dict(corrections.get(jour, {}))
        dans_differe = int(ligne) < params.nb_echeances_differe or jour in suspendues  # pas de capital remboursé
        for colonne, valeur in valeurs.items():
            if valeur is not None and not 0 <= float(valeur) <= plafond_saisie:
                refusees.append(f"{euros(float(valeur))} le {jour.strftime('%d/%m/%Y')}")
                continue
            if colonne == "Intérêt (€)" and jour in suspendues and suspendues[jour].reporte:
                ignorees += 1  # intérêts reportés : payés après la reprise, pas à cette échéance
                continue
            if colonne == "Échéance (€)":
                if dans_differe or valeur is None:
                    ignorees += 1
                    continue
                # Échéance saisie : conservée telle quelle ; le capital en est déduit au calcul (échéance
                # moins intérêts, assurance et frais de la ligne).
                frais_ligne = sum(float(valeurs.get(c, actuelle[c])) for c in ("Assurance (€)", "Autres frais (€)"))
                correction["echeance"] = round(float(valeur) - frais_ligne, 2)
                correction.pop("amortissement", None)
            elif colonne in COLONNES_MODIFIABLES:
                if colonne == "Amortissement (€)" and dans_differe:
                    ignorees += 1
                    continue
                if valeur is None:
                    correction.pop(COLONNES_MODIFIABLES[colonne], None)
                else:
                    correction[COLONNES_MODIFIABLES[colonne]] = round(float(valeur), 2)
                if colonne == "Amortissement (€)":
                    correction.pop("echeance", None)  # le dernier montant saisi l'emporte
        if correction:
            corrections[jour] = correction
        else:
            corrections.pop(jour, None)
    messages = []
    if ignorees:
        messages.append(
            "Pendant le différé ou une suspension d'échéances, seuls les intérêts, l'assurance et les frais sont "
            "modifiables (et pas les intérêts reportés d'une suspension, payés après la reprise)."
        )
    if refusees:
        messages.append(
            f"Montant{'s' if len(refusees) > 1 else ''} refusé{'s' if len(refusees) > 1 else ''} "
            f"({', '.join(refusees)}) : un montant doit être compris entre 0 € et {euros(plafond_saisie)} "
            "(capital emprunté plus intérêts du prêt)."
        )
    if messages:
        st.session_state[cle_corrections + "_message"] = " ".join(messages)
    if corrections != avant:
        historique.append(avant)
    st.session_state[cle_corrections + "_version"] = version_tableau + 1
    st.rerun()

# Ajout, suppression et rétablissement d'échéances --------------------------------------------------------------
st.markdown("**Ajouter ou supprimer des échéances**")
dates_tableau = list(echeancier["Date"])
debut_ajout = dates_tableau[params.nb_echeances_differe - 1] if params.nb_echeances_differe else None
copie = lambda: {jour: dict(valeurs) for jour, valeurs in corrections.items()}  # noqa: E731

c_champ, c_bouton = st.columns([3, 1], vertical_alignment="bottom")
date_ajout = c_champ.date_input(
    "➕ Ajouter une échéance le", key=cle(f"date_ajout_{version_tableau}"), value=None, format="DD/MM/YYYY",
    help="L'échéance est insérée à sa date dans le tableau, puis l'échéancier est recalculé.",
)
if c_bouton.button("➕ Ajouter", key=cle("ajouter_echeance"), disabled=date_ajout is None, width="stretch"):
    if date_ajout in dates_tableau:
        refuser(f"Une échéance existe déjà le {date_ajout.strftime('%d/%m/%Y')} : modifiez-la directement dans le tableau.")
    elif debut_ajout and date_ajout <= debut_ajout:
        refuser(
            f"L'échéance du {date_ajout.strftime('%d/%m/%Y')} tomberait pendant le différé (jusqu'au "
            f"{debut_ajout.strftime('%d/%m/%Y')}) : modifiez plutôt le nombre d'échéances de différé à l'étape 1."
        )
    elif not 1990 <= date_ajout.year <= 2100:
        refuser(f"La date du {date_ajout.strftime('%d/%m/%Y')} n'est pas vraisemblable.")
    else:
        nouvelles = copie()
        if nouvelles.get(date_ajout, {}).get("supprimee"):
            nouvelles.pop(date_ajout)  # échéance prévue supprimée puis rajoutée : retour au calcul
        else:
            nouvelles[date_ajout] = {"ajoutee": True}
        enregistrer(nouvelles)
    st.rerun()

c_champ, c_bouton = st.columns([3, 1], vertical_alignment="bottom")
a_supprimer = c_champ.multiselect(
    "🗑️ Supprimer les échéances du",
    dates_tableau[params.nb_echeances_differe :],  # les échéances du différé se règlent à l'étape 1
    format_func=lambda d: d.strftime("%d/%m/%Y"),
    key=cle(f"a_supprimer_{version_tableau}"),
    placeholder="Choisissez une ou plusieurs dates",
)
if c_bouton.button("🗑️ Supprimer", key=cle("supprimer_echeances"), disabled=not a_supprimer, width="stretch"):
    if len(dates_tableau) - params.nb_echeances_differe - len(a_supprimer) < 1:
        refuser("Suppression impossible : il doit rester au moins une échéance de remboursement du capital.")
    else:
        nouvelles = copie()
        for jour in a_supprimer:
            if nouvelles.get(jour, {}).get("ajoutee"):
                nouvelles.pop(jour)  # échéance ajoutée par l'utilisateur : simplement retirée
            else:
                nouvelles[jour] = {"supprimee": True}
        enregistrer(nouvelles)
    st.rerun()

if supprimees_tableau:
    c_champ, c_bouton = st.columns([3, 1], vertical_alignment="bottom")
    a_retablir = c_champ.multiselect(
        f"↩ Rétablir des échéances supprimées ({len(supprimees_tableau)})",
        supprimees_tableau,
        format_func=lambda d: d.strftime("%d/%m/%Y"),
        key=cle(f"a_retablir_{version_tableau}"),
        placeholder="Choisissez une ou plusieurs dates",
        help="Échéances supprimées : " + ", ".join(d.strftime("%d/%m/%Y") for d in supprimees_tableau),
    )
    if c_bouton.button("↩ Rétablir", key=cle("retablir_echeances"), disabled=not a_retablir, width="stretch"):
        nouvelles = copie()
        for jour in a_retablir:
            nouvelles.pop(jour, None)
        enregistrer(nouvelles)
        st.rerun()

st.download_button(
    "📥 Télécharger l'échéancier Pennylane (.xlsx)",
    data=sans_plantage(exporter_pennylane, params, echeancier),
    file_name="Echeancier_pennylane.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    width="stretch",
)

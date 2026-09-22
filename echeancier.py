"""Calcul d'un échéancier d'emprunt à déblocages multiples, au format Pennylane.

Principe (constaté sur le grand livre d'un prêt Crédit Agricole à déblocages successifs) :
- pendant le **différé**, les intérêts courent sur les fonds réellement débloqués, en jours
  exacts sur une base de 365 jours ; ils sont soit payés à chaque échéance, soit **capitalisés** (ajoutés au capital) ;
- à la fin du différé, la banque amortit le capital total (+ intérêts capitalisés) par
  **échéances constantes**, comme un prêt classique, quelles que soient les dates des derniers déblocages ;
- pendant l'amortissement, les intérêts sont calculés à taux / 12 sur le capital restant dû
  (vérifié au centime sur le tableau bancaire) ; une option permet les jours exacts / 365.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd

MODELE_PENNYLANE = Path(__file__).parent / "modeles" / "Echeancier_type.xlsx"

BASE_JOURS = 365  # intérêts : jours exacts / 365
FORMAT_DATE = "dd/mm/yyyy"  # dates au format français dans le fichier exporté
PERIODICITES = {"Mensuelle": 1, "Trimestrielle": 3, "Semestrielle": 6, "Annuelle": 12}
COLONNES = ["Date", "Intérêt (€)", "Assurance (€)", "Autres frais (€)", "Amortissement (€)", "Échéance (€)", "Solde (€)"]


@dataclass
class Deblocage:
    date: date
    montant: float


@dataclass
class ParametresPret:
    capital: float
    taux: float  # taux nominal annuel en %
    nb_echeances: int  # nombre total d'échéances, différé inclus
    date_premier_paiement: date
    jour_prelevement: int
    deblocages: list[Deblocage] = field(default_factory=list)
    nb_echeances_differe: int = 0  # échéances de différé avant l'amortissement
    interets_differe_capitalises: bool = True  # False : intérêts du différé payés à chaque échéance
    interets_capitalises_imposes: float | None = None  # montant du tableau bancaire, si connu
    periodicite: str = "Mensuelle"
    type_remboursement: str = "Échéances constantes"  # ou "Amortissement constant"
    echeance_imposee: float | None = None  # échéance hors assurance de l'offre bancaire, si connue
    remboursements_constates: list[float] = field(default_factory=list)  # capital remboursé (grand livre)
    interets_jours_exacts: bool = False  # amortissement : taux / 12 (banque) ; True : jours exacts / 365
    assurance: float = 0.0
    assurance_en_pourcentage: bool = False  # True : taux annuel sur le capital ; False : montant total
    autres_frais: float = 0.0
    autres_frais_en_pourcentage: bool = False  # True : % du capital ; False : montant total

    @property
    def mois_par_periode(self) -> int:
        return PERIODICITES[self.periodicite]

    @property
    def taux_periodique(self) -> float:
        return self.taux / 100 * self.mois_par_periode / 12

    @property
    def nb_echeances_amortissement(self) -> int:
        return self.nb_echeances - self.nb_echeances_differe

    @property
    def montant_total_assurance(self) -> float:
        if self.assurance_en_pourcentage:
            par_echeance = round(self.capital * self.assurance / 100 * self.mois_par_periode / 12, 2)
            return round(par_echeance * self.nb_echeances, 2)
        return round(self.assurance, 2)

    @property
    def montant_total_autres_frais(self) -> float:
        if self.autres_frais_en_pourcentage:
            return round(self.capital * self.autres_frais / 100, 2)
        return round(self.autres_frais, 2)

    @property
    def taux_assurance(self) -> float:
        return self.assurance if self.assurance_en_pourcentage else 0.0

    @property
    def pourcentage_autres_frais(self) -> float:
        return self.autres_frais if self.autres_frais_en_pourcentage else 0.0


@dataclass
class Resultat:
    echeancier: pd.DataFrame
    capital_amorti: float  # capital + intérêts capitalisés
    interets_capitalises_calcules: float
    interets_capitalises_retenus: float
    echeance_constante: float | None


def ajouter_mois(d: date, mois: int, jour: int | None = None) -> date:
    """Décale une date de `mois` mois en gardant le jour voulu (borné à la fin du mois)."""
    total = d.month - 1 + mois
    annee, mois_ = d.year + total // 12, total % 12 + 1
    jour = jour or d.day
    return date(annee, mois_, min(jour, calendar.monthrange(annee, mois_)[1]))


def dates_echeances(p: ParametresPret) -> list[date]:
    """Première date au jour de prélèvement à partir de la date du premier paiement, puis une par période."""
    premiere = ajouter_mois(p.date_premier_paiement, 0, p.jour_prelevement)
    if premiere < p.date_premier_paiement:
        premiere = ajouter_mois(premiere, 1, p.jour_prelevement)
    return [ajouter_mois(premiere, k * p.mois_par_periode, p.jour_prelevement) for k in range(p.nb_echeances)]


def repartir(total: float, n: int) -> list[float]:
    """Répartit un montant en n parts arrondies au centime ; la dernière absorbe l'écart."""
    if n <= 0:
        return []
    part = round(total / n, 2)
    return [part] * (n - 1) + [round(total - part * (n - 1), 2)]


def interets_differe(p: ParametresPret, dates: list[date]) -> list[float]:
    """Intérêts de chaque échéance de différé, sur les fonds réellement débloqués.

    Calcul en jours exacts sur une base de 365 jours : chaque déblocage porte intérêt du jour du
    versement (ou du début de la période) jusqu'à la date d'échéance.
    """
    # Sans déblocage saisi : fonds versés en totalité une période avant la première échéance.
    deblocages = sorted(p.deblocages, key=lambda d: d.date) or [
        Deblocage(ajouter_mois(dates[0], -p.mois_par_periode, p.jour_prelevement), p.capital)
    ]
    r = p.taux / 100
    interets, debut = [], None
    for fin in dates[: p.nb_echeances_differe]:
        interet = 0.0
        for d in deblocages:
            if d.date < fin:
                depart = d.date if debut is None else max(d.date, debut)
                interet += d.montant * r * (fin - depart).days / BASE_JOURS
        interets.append(round(interet, 2))
        debut = fin
    return interets


def facteurs_interets(p: ParametresPret, dates: list[date]) -> list[float]:
    """Taux d'intérêt de chaque période d'amortissement : taux périodique (ou jours exacts / 365)."""
    if not p.interets_jours_exacts:
        return [p.taux_periodique] * p.nb_echeances_amortissement
    r, k0 = p.taux / 100, p.nb_echeances_differe
    debuts = [dates[k0 - 1] if k0 else ajouter_mois(dates[0], -p.mois_par_periode, p.jour_prelevement)] + dates[k0:-1]
    return [r * (fin - debut).days / BASE_JOURS for debut, fin in zip(debuts, dates[k0:])]


def tableau_constant(base: float, echeance: float, facteurs: list[float]) -> list[tuple[float, float]]:
    """(intérêt, amortissement) de chaque échéance, arrondis au centime ligne à ligne.

    La dernière échéance solde le capital et reste égale aux autres quand l'écart n'est qu'un arrondi
    (convention Pennylane et bancaire).
    """
    lignes, restant, n = [], base, len(facteurs)
    for k, facteur in enumerate(facteurs):
        interet = round(restant * facteur, 2)
        if k == n - 1:
            a = restant
            if abs(round(echeance - a, 2) - interet) <= 0.02:
                interet = round(echeance - a, 2)
        else:
            a = min(round(echeance - interet, 2), restant)
        lignes.append((interet, round(a, 2)))
        restant = round(restant - a, 2)
    return lignes


def echeance_pour(base: float, t: float, n: int) -> float:
    return round(base / n if t == 0 else base * t / (1 - (1 + t) ** -n), 2)


def calibrer_base(echeance: float, t: float, facteurs: list[float], constates: list[float]) -> float:
    """Capital amorti correspondant à une échéance connue.

    Sans données comptables : valeur actuelle des échéances. Avec les remboursements de capital du
    grand livre : milieu de la plage de capitaux (au centime) qui les reproduit exactement.
    """
    n = len(facteurs)
    base = round(echeance * n if t == 0 else echeance * (1 - (1 + t) ** -n) / t, 2)
    if not constates:
        return base
    compatibles = [
        c / 100
        for c in range(round(base * 100) - 1000, round(base * 100) + 1000)
        if [a for _, a in tableau_constant(c / 100, echeance, facteurs)[: len(constates)]] == constates
    ]
    return compatibles[len(compatibles) // 2] if compatibles else base


def calculer(p: ParametresPret) -> Resultat:
    """Échéancier complet : différé puis amortissement du capital (+ intérêts capitalisés)."""
    n, t = p.nb_echeances_amortissement, p.taux_periodique
    if n <= 0:
        raise ValueError("Le nombre d'échéances doit être supérieur au nombre d'échéances de différé.")
    dates = dates_echeances(p)
    interets = interets_differe(p, dates)
    facteurs = facteurs_interets(p, dates)
    calcules = round(sum(interets), 2) if p.interets_differe_capitalises else 0.0

    capitalises = calcules
    if p.interets_differe_capitalises and p.interets_capitalises_imposes is not None:
        capitalises = round(p.interets_capitalises_imposes, 2)
    base = round(p.capital + capitalises, 2)

    echeance = None
    if p.type_remboursement == "Amortissement constant":
        amortissements = repartir(base, n)
        lignes_amort, restant = [], base
        for a, facteur in zip(amortissements, facteurs):
            lignes_amort.append((round(restant * facteur, 2), a))
            restant = round(restant - a, 2)
    else:
        if p.echeance_imposee:
            echeance = round(p.echeance_imposee, 2)
            if p.interets_differe_capitalises and p.interets_capitalises_imposes is None:
                # L'échéance de la banque fixe le capital amorti, donc les intérêts capitalisés.
                base = calibrer_base(echeance, t, facteurs, p.remboursements_constates)
                capitalises = round(base - p.capital, 2)
        else:
            echeance = echeance_pour(base, t, n)
        lignes_amort = tableau_constant(base, echeance, facteurs)

    if p.interets_differe_capitalises and interets:
        # L'écart entre intérêts retenus et calculés est porté sur la dernière échéance de différé.
        interets[-1] = round(interets[-1] + capitalises - calcules, 2)

    assurances = repartir(p.montant_total_assurance, p.nb_echeances)
    frais = repartir(p.montant_total_autres_frais, p.nb_echeances)
    lignes, solde = [], p.capital
    for k, d in enumerate(dates):
        if k < p.nb_echeances_differe:
            interet = interets[k]
            amort = -interet if p.interets_differe_capitalises else 0.0
        else:
            interet, amort = lignes_amort[k - p.nb_echeances_differe]
        solde = round(solde - amort, 2)
        paye = round(interet + amort, 2)  # nul pendant un différé capitalisé
        lignes.append([d, interet, assurances[k], frais[k], amort, round(paye + assurances[k] + frais[k], 2), solde])
    return Resultat(pd.DataFrame(lignes, columns=COLONNES), base, calcules, capitalises, echeance)


def calculer_echeancier(p: ParametresPret) -> pd.DataFrame:
    return calculer(p).echeancier


def exporter_pennylane(p: ParametresPret, echeancier: pd.DataFrame) -> bytes:
    """Remplit le fichier type Pennylane (en-tête lignes 1-2, échéances à partir de la ligne 6)."""
    wb = openpyxl.load_workbook(MODELE_PENNYLANE)
    ws = wb.active
    format_nombre = ws["A2"].number_format
    style_ligne = [ws.cell(row=6, column=c)._style for c in range(1, 8)]
    ws.delete_rows(6, ws.max_row)

    entete = [
        p.capital,
        p.taux,
        p.taux_assurance,
        p.montant_total_assurance,
        p.pourcentage_autres_frais,
        p.montant_total_autres_frais,
        p.nb_echeances,
    ]
    for c, valeur in enumerate(entete, start=1):
        ws.cell(row=2, column=c, value=valeur)

    for i, ligne in enumerate(echeancier.itertuples(index=False), start=6):
        for c, valeur in enumerate(ligne, start=1):
            cellule = ws.cell(row=i, column=c, value=valeur)
            cellule._style = style_ligne[c - 1]
            cellule.number_format = FORMAT_DATE if c == 1 else format_nombre

    sortie = BytesIO()
    wb.save(sortie)
    return sortie.getvalue()


def lire_grand_livre(fichier) -> tuple[list[Deblocage], pd.DataFrame]:
    """Lit un export « Grand livre » Pennylane du compte d'emprunt (colonnes Date, Débit, Crédit).

    Retourne les déblocages (crédits) et les remboursements de capital constatés (débits).
    """
    gl = pd.read_excel(fichier)
    gl["Date"] = pd.to_datetime(gl["Date"], dayfirst=True).dt.date
    gl[["Débit", "Crédit"]] = gl[["Débit", "Crédit"]].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    deblocages = [Deblocage(r.Date, round(float(r.Crédit), 2)) for r in gl.itertuples() if r.Crédit > 0]
    remboursements = gl.loc[gl["Débit"] > 0, ["Date", "Débit"]].rename(columns={"Débit": "Capital remboursé (€)"})
    return deblocages, remboursements.reset_index(drop=True)


def comparer(echeancier: pd.DataFrame, remboursements: pd.DataFrame) -> pd.DataFrame:
    """Rapproche le capital remboursé en comptabilité de l'amortissement calculé, mois par mois."""
    calc = echeancier[echeancier["Amortissement (€)"] > 0][["Date", "Amortissement (€)"]].copy()
    calc["Mois"] = [d.strftime("%Y-%m") for d in calc["Date"]]
    reel = remboursements.copy()
    reel["Mois"] = [d.strftime("%Y-%m") for d in reel["Date"]]
    comp = reel.drop(columns="Date").merge(calc, on="Mois", how="left")
    comp["Écart (€)"] = (comp["Capital remboursé (€)"] - comp["Amortissement (€)"]).round(2)
    return comp[["Date", "Capital remboursé (€)", "Amortissement (€)", "Écart (€)"]]

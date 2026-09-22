"""Calcul d'un échéancier d'emprunt à déblocages multiples, au format Pennylane.

Principe (constaté sur les tableaux bancaires de type Crédit Agricole) :
- le **capital amorti** suit un tableau théorique calculé sur le capital total du prêt,
  indépendamment des dates de déblocage ;
- les **intérêts** sont calculés sur le capital réellement débloqué et non encore remboursé,
  au prorata des jours pour les fonds débloqués en cours de période ;
- les premières échéances peuvent être des échéances de différé (intérêts seuls).
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
    nb_echeances_differe: int = 0  # échéances d'intérêts seuls avant l'amortissement
    periodicite: str = "Mensuelle"
    type_remboursement: str = "Échéances constantes"  # ou "Amortissement constant"
    echeance_imposee: float | None = None  # échéance hors assurance de l'offre bancaire, si connue
    assurance: float = 0.0
    assurance_en_pourcentage: bool = False  # True : taux annuel sur le capital ; False : montant total
    autres_frais: float = 0.0
    autres_frais_en_pourcentage: bool = False  # True : % du capital ; False : montant total
    base_jours: int = 365  # base de calcul des intérêts au prorata des jours

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


def amortissements_theoriques(p: ParametresPret) -> tuple[list[float], float | None]:
    """Tableau d'amortissement théorique du capital total, arrondi au centime comme les banques.

    Retourne les amortissements et l'échéance constante hors assurance (None en amortissement constant).
    """
    n, t, restant = p.nb_echeances_amortissement, p.taux_periodique, p.capital
    if n <= 0:
        raise ValueError("Le nombre d'échéances doit être supérieur au nombre d'échéances de différé.")
    if p.type_remboursement == "Amortissement constant":
        return repartir(p.capital, n), None
    if p.echeance_imposee:
        echeance = round(p.echeance_imposee, 2)
    elif t == 0:
        echeance = round(p.capital / n, 2)
    else:
        echeance = round(p.capital * t / (1 - (1 + t) ** -n), 2)
    amortissements = []
    for k in range(n):
        interet = round(restant * t, 2)
        a = restant if k == n - 1 else min(round(echeance - interet, 2), restant)
        amortissements.append(round(a, 2))
        restant = round(restant - a, 2)
    return amortissements, echeance


def calculer_echeancier(p: ParametresPret) -> pd.DataFrame:
    """Échéancier réel : amortissement théorique, intérêts sur le capital effectivement débloqué."""
    deblocages = sorted(p.deblocages, key=lambda d: d.date) or [Deblocage(p.date_premier_paiement, p.capital)]
    dates = dates_echeances(p)
    theoriques, echeance_constante = amortissements_theoriques(p)
    amortissements = [0.0] * p.nb_echeances_differe + theoriques
    assurances = repartir(p.montant_total_assurance, p.nb_echeances)
    frais = repartir(p.montant_total_autres_frais, p.nb_echeances)
    r, t = p.taux / 100, p.taux_periodique

    lignes, rembourse = [], 0.0
    fin_precedente = ajouter_mois(dates[0], -p.mois_par_periode, p.jour_prelevement)
    for k, fin in enumerate(dates):
        debut = fin_precedente
        # Capital débloqué avant la période et non remboursé : intérêt d'une période pleine.
        debloque_avant = sum(d.montant for d in deblocages if d.date <= debut)
        interet = (debloque_avant - rembourse) * t
        # Fonds débloqués pendant la période : prorata des jours jusqu'à l'échéance.
        for d in deblocages:
            if debut < d.date <= fin:
                interet += d.montant * r * (fin - d.date).days / p.base_jours
            elif k == 0 and d.date < debut:
                # Première échéance : intérêts intercalaires depuis le déblocage.
                interet += d.montant * r * (debut - d.date).days / p.base_jours
        interet = round(interet, 2)
        if k == len(dates) - 1 and echeance_constante is not None:
            # Comme Pennylane et les banques : la dernière échéance reste égale aux autres,
            # l'intérêt absorbe l'écart d'arrondi.
            ajuste = round(echeance_constante - amortissements[k], 2)
            if abs(ajuste - interet) <= 0.02:
                interet = ajuste
        rembourse = round(rembourse + amortissements[k], 2)
        solde = round(sum(d.montant for d in deblocages if d.date <= fin) - rembourse, 2)
        echeance = round(interet + assurances[k] + frais[k] + amortissements[k], 2)
        lignes.append([fin, interet, assurances[k], frais[k], amortissements[k], echeance, solde])
        fin_precedente = fin
    return pd.DataFrame(lignes, columns=COLONNES)


def lignes_deblocage(p: ParametresPret) -> pd.DataFrame:
    """Déblocages présentés comme des lignes d'amortissement négatif (le solde augmente)."""
    return pd.DataFrame(
        [[d.date, 0.0, 0.0, 0.0, -d.montant, -d.montant, None] for d in p.deblocages], columns=COLONNES
    )


def echeancier_avec_deblocages(p: ParametresPret, echeancier: pd.DataFrame) -> pd.DataFrame:
    """Insère les déblocages dans l'échéancier et recalcule le solde ligne à ligne."""
    tout = pd.concat([lignes_deblocage(p), echeancier], ignore_index=True)
    tout["_ordre"] = tout["Échéance (€)"] >= 0  # à date égale, le déblocage passe avant l'échéance
    tout = tout.sort_values(["Date", "_ordre"], kind="stable").drop(columns="_ordre").reset_index(drop=True)
    tout["Solde (€)"] = (-tout["Amortissement (€)"]).cumsum().round(2)
    return tout


def exporter_pennylane(p: ParametresPret, echeancier: pd.DataFrame) -> bytes:
    """Remplit le fichier type Pennylane (en-tête lignes 1-2, échéances à partir de la ligne 6)."""
    wb = openpyxl.load_workbook(MODELE_PENNYLANE)
    ws = wb.active
    format_nombre = ws["A2"].number_format
    format_date = ws["A6"].number_format
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
            cellule.number_format = format_date if c == 1 else format_nombre

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

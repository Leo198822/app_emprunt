"""Fonctions de calcul pour un prêt à amortissement constant (mensualités fixes)."""

from dataclasses import dataclass

import pandas as pd


@dataclass
class Pret:
    montant: float  # capital emprunté, en euros
    taux_annuel: float  # taux nominal annuel, en pourcentage (ex. 3.5)
    duree_annees: int
    taux_assurance: float = 0.0  # taux annuel de l'assurance, en % du capital initial

    @property
    def nb_mois(self) -> int:
        return self.duree_annees * 12

    @property
    def taux_mensuel(self) -> float:
        return self.taux_annuel / 100 / 12

    @property
    def assurance_mensuelle(self) -> float:
        return self.montant * self.taux_assurance / 100 / 12


def mensualite(montant: float, taux_annuel: float, nb_mois: int) -> float:
    """Mensualité hors assurance d'un prêt à échéances constantes."""
    if nb_mois <= 0:
        raise ValueError("La durée doit être strictement positive.")
    t = taux_annuel / 100 / 12
    if t == 0:
        return montant / nb_mois
    return montant * t / (1 - (1 + t) ** -nb_mois)


def tableau_amortissement(pret: Pret) -> pd.DataFrame:
    """Tableau d'amortissement mois par mois."""
    m = mensualite(pret.montant, pret.taux_annuel, pret.nb_mois)
    capital_restant = pret.montant
    lignes = []
    for mois in range(1, pret.nb_mois + 1):
        interets = capital_restant * pret.taux_mensuel
        capital = m - interets
        if mois == pret.nb_mois:
            # Absorbe les écarts d'arrondi sur la dernière échéance.
            capital = capital_restant
        capital_restant -= capital
        lignes.append(
            {
                "Mois": mois,
                "Année": (mois - 1) // 12 + 1,
                "Mensualité": capital + interets,
                "Capital": capital,
                "Intérêts": interets,
                "Assurance": pret.assurance_mensuelle,
                "Capital restant dû": max(capital_restant, 0.0),
            }
        )
    return pd.DataFrame(lignes)


def synthese(pret: Pret) -> dict:
    """Indicateurs clés du prêt."""
    m = mensualite(pret.montant, pret.taux_annuel, pret.nb_mois)
    cout_interets = m * pret.nb_mois - pret.montant
    cout_assurance = pret.assurance_mensuelle * pret.nb_mois
    return {
        "mensualite_hors_assurance": m,
        "mensualite_totale": m + pret.assurance_mensuelle,
        "cout_interets": cout_interets,
        "cout_assurance": cout_assurance,
        "cout_total": cout_interets + cout_assurance,
        "montant_total_rembourse": pret.montant + cout_interets + cout_assurance,
    }


def capacite_emprunt(
    revenus_mensuels: float,
    charges_mensuelles: float,
    taux_annuel: float,
    duree_annees: int,
    taux_endettement_max: float = 35.0,
) -> tuple[float, float]:
    """Mensualité maximale et capital empruntable selon un taux d'endettement cible.

    Retourne (mensualite_max, capital_max).
    """
    mensualite_max = max(revenus_mensuels * taux_endettement_max / 100 - charges_mensuelles, 0.0)
    nb_mois = duree_annees * 12
    t = taux_annuel / 100 / 12
    if t == 0:
        capital = mensualite_max * nb_mois
    else:
        capital = mensualite_max * (1 - (1 + t) ** -nb_mois) / t
    return mensualite_max, capital

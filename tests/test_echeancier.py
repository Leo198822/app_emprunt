from datetime import date
from pathlib import Path

import openpyxl
import pytest

from echeancier import (
    calculer,
    MODELE_PENNYLANE,
    Deblocage,
    ParametresPret,
    calculer_echeancier,
    comparer,
    exporter_pennylane,
    lire_grand_livre,
)

GRAND_LIVRE = Path(__file__).parent / "grand_livre_exemple.xlsx"


def pret_simple():
    return ParametresPret(
        capital=24_000,
        taux=4.17,
        nb_echeances=60,
        date_premier_paiement=date(2026, 1, 5),
        jour_prelevement=10,
        deblocages=[Deblocage(date(2025, 12, 10), 24_000)],
    )


def pret_banque(echeance_imposee=None, constates=()):
    deblocages, _ = lire_grand_livre(GRAND_LIVRE)
    return ParametresPret(
        capital=24_000,
        taux=4.17,
        nb_echeances=60,
        nb_echeances_differe=3,
        date_premier_paiement=date(2026, 1, 5),
        jour_prelevement=5,
        deblocages=deblocages,
        echeance_imposee=echeance_imposee,
        remboursements_constates=list(constates),
    )


def test_reproduit_le_fichier_type_pennylane():
    """Sans déblocages multiples, on retrouve à l'identique l'échéancier généré par Pennylane."""
    calcule = calculer_echeancier(pret_simple()).values.tolist()
    reference = [[c.value for c in ligne] for ligne in openpyxl.load_workbook(MODELE_PENNYLANE).active.iter_rows(min_row=6)]
    assert len(calcule) == len(reference) == 60
    for ligne, attendu in zip(calcule, reference):
        assert ligne[0] == attendu[0].date()
        assert ligne[1:] == pytest.approx(attendu[1:], abs=0.001)


def test_lecture_grand_livre():
    deblocages, remboursements = lire_grand_livre(GRAND_LIVRE)
    assert len(deblocages) == 5
    assert sum(d.montant for d in deblocages) == pytest.approx(24_000)
    assert remboursements["Capital remboursé (€)"].tolist()[0] == pytest.approx(384.40)


def test_differe_capitalise():
    r = calculer(pret_banque())
    e = r.echeancier
    # Différé : intérêts sur les fonds débloqués, ajoutés au capital, rien n'est prélevé.
    assert e["Intérêt (€)"].iloc[0] == pytest.approx(18_319 * 0.0417 * 24 / 365, abs=0.01)
    assert e["Amortissement (€)"].iloc[:3].tolist() == pytest.approx((-e["Intérêt (€)"].iloc[:3]).tolist())
    assert e["Échéance (€)"].iloc[:3].tolist() == [0, 0, 0]
    assert r.capital_amorti == pytest.approx(24_000 + r.interets_capitalises_calcules)
    assert e["Solde (€)"].iloc[2] == pytest.approx(r.capital_amorti)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)
    # Échéances constantes ensuite.
    assert e["Échéance (€)"].iloc[3:-1].nunique() == 1


def test_differe_paye():
    p = pret_banque()
    p.interets_differe_capitalises = False
    e = calculer_echeancier(p)
    assert e["Amortissement (€)"].iloc[:3].tolist() == [0, 0, 0]
    assert e["Échéance (€)"].iloc[0] == e["Intérêt (€)"].iloc[0] > 0
    assert e["Amortissement (€)"].sum() == pytest.approx(24_000)


def test_echeance_bancaire_reproduit_le_grand_livre():
    """Échéance de l'offre (468,45 €) + remboursements du grand livre : écart nul au centime."""
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    p = pret_banque(468.45, remboursements["Capital remboursé (€)"])
    r = calculer(p)
    assert comparer(r.echeancier, remboursements)["Écart (€)"].abs().max() == 0
    assert set(r.echeancier["Échéance (€)"].iloc[3:-1]) == {468.45}
    assert r.echeancier["Solde (€)"].iloc[-1] == pytest.approx(0)
    assert 185 < r.interets_capitalises_retenus < 186


def test_export_respecte_le_fichier_type(tmp_path):
    p = pret_banque()
    fichier = tmp_path / "export.xlsx"
    fichier.write_bytes(exporter_pennylane(p, calculer_echeancier(p)))
    ws = openpyxl.load_workbook(fichier).active
    modele = openpyxl.load_workbook(MODELE_PENNYLANE).active
    for ligne in (1, 5):
        assert [c.value for c in ws[ligne]] == [c.value for c in modele[ligne]]
    assert [c.value for c in ws[2]] == [24_000, 4.17, 0, 0, 0, 0, 60]
    assert ws.max_row == 65
    assert ws["A6"].number_format == "dd/mm/yyyy"

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from echeancier import (
    MODELE_PENNYLANE,
    Deblocage,
    ParametresPret,
    calculer_echeancier,
    comparer,
    echeancier_avec_deblocages,
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


def pret_banque(echeance_imposee=None):
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


def test_deblocages_multiples_et_differe():
    e = calculer_echeancier(pret_banque())
    # Différé : intérêts seuls, calculés sur les fonds débloqués.
    assert e["Amortissement (€)"].iloc[:3].tolist() == [0, 0, 0]
    assert e["Intérêt (€)"].iloc[0] == pytest.approx(18_319 * 0.0417 * 24 / 365, abs=0.01)
    assert e["Solde (€)"].iloc[2] == pytest.approx(21_672.72)
    assert e["Amortissement (€)"].sum() == pytest.approx(24_000)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)


def test_echeance_imposee_colle_au_grand_livre():
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    controle = comparer(calculer_echeancier(pret_banque(467.80)), remboursements)
    assert controle["Écart (€)"].abs().max() <= 0.01


def test_lignes_de_deblocage():
    p = pret_banque()
    tout = echeancier_avec_deblocages(p, calculer_echeancier(p))
    assert len(tout) == 65
    assert tout["Solde (€)"].iloc[0] == pytest.approx(18_319)
    assert tout["Solde (€)"].iloc[-1] == pytest.approx(0)


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
    assert ws["A6"].number_format == modele["A6"].number_format

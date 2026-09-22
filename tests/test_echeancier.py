from datetime import date
from pathlib import Path

import openpyxl
import pytest

from echeancier import (
    ajuster_sur_solde,
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


# Extrait du tableau d'amortissement bancaire du prêt n°141 : rang -> (intérêts, capital amorti, CRD).
TABLEAU_BANQUE = {
    10: (75.96, 392.49, 21_466.71),
    11: (74.60, 393.85, 21_072.86),
    16: (67.71, 400.74, 19_082.97),
    20: (62.11, 406.34, 17_466.02),
    30: (47.76, 420.69, 13_324.11),
    40: (32.91, 435.54, 9_035.98),
    50: (17.54, 450.91, 4_596.50),
    55: (9.65, 458.80, 2_318.33),
    58: (4.85, 463.60, 932.35),
    59: (3.24, 465.21, 467.14),
}


def test_reproduit_le_tableau_bancaire():
    """Échéance 468,45 € et capital de départ 24 185,76 € (21 859,20 + 2 326,56) : tableau au centime."""
    p = pret_banque(468.45)
    p.interets_capitalises_imposes = 185.76
    e = calculer_echeancier(p)
    assert e["Solde (€)"].iloc[8] == pytest.approx(21_859.20)
    assert e["Amortissement (€)"].iloc[3:9].sum() == pytest.approx(2_326.56)
    for rang, attendu in TABLEAU_BANQUE.items():
        ligne = e.iloc[rang - 1]
        assert (ligne["Intérêt (€)"], ligne["Amortissement (€)"], ligne["Solde (€)"]) == pytest.approx(attendu, abs=0.001)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    assert comparer(e, remboursements)["Écart (€)"].abs().max() == 0


def test_calage_sur_le_grand_livre():
    """Sans le tableau bancaire : capital déduit de l'échéance et des remboursements comptabilisés."""
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    r = calculer(pret_banque(468.45, remboursements["Capital remboursé (€)"]))
    assert comparer(r.echeancier, remboursements)["Écart (€)"].abs().max() == 0
    assert set(r.echeancier["Échéance (€)"].iloc[3:-1]) == {468.45}
    assert abs(r.capital_amorti - 24_185.76) < 0.2


def test_option_jours_exacts():
    p = pret_banque(468.45)
    p.interets_jours_exacts = True
    e = calculer_echeancier(p)
    avril, mai = e.iloc[3], e.iloc[4]  # 05/03 → 05/04 : 31 jours ; 05/04 → 05/05 : 30 jours
    assert avril["Intérêt (€)"] == pytest.approx(e["Solde (€)"].iloc[2] * 0.0417 * 31 / 365, abs=0.01)
    assert mai["Intérêt (€)"] == pytest.approx(avril["Solde (€)"] * 0.0417 * 30 / 365, abs=0.01)


def test_ajustement_sur_le_capital_restant_du_de_la_banque():
    """CRD de la banque au 08/09/2026 (21 859,20 €) : l'application retrouve seule le tableau bancaire."""
    a = ajuster_sur_solde(pret_banque(468.45), date(2026, 9, 8), 21_859.20)
    assert a.levier == "intérêts capitalisés"
    assert a.date_echeance == date(2026, 9, 5)
    assert a.solde_obtenu == pytest.approx(21_859.20)
    assert a.parametres.interets_capitalises_imposes == pytest.approx(185.76)
    e = calculer_echeancier(a.parametres)
    for rang, attendu in TABLEAU_BANQUE.items():
        ligne = e.iloc[rang - 1]
        assert (ligne["Intérêt (€)"], ligne["Amortissement (€)"], ligne["Solde (€)"]) == pytest.approx(attendu, abs=0.001)


def test_ajustement_sans_differe_recalcule_l_echeance():
    p = pret_simple()
    p.echeance_imposee = 400.0  # échéance erronée
    a = ajuster_sur_solde(p, date(2026, 12, 15), 19_591.09)  # CRD du fichier type Pennylane au 10/12/2026
    assert a.levier == "échéance"
    assert a.parametres.echeance_imposee == pytest.approx(443.84)
    assert a.solde_obtenu == pytest.approx(19_591.09)


def test_ajustement_avant_la_premiere_echeance():
    assert ajuster_sur_solde(pret_simple(), date(2025, 12, 1), 24_000) is None


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

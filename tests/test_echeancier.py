from dataclasses import replace
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from echeancier import (
    capital_constate,
    RemboursementAnticipe,
    Suspension,
    dates_suspendues,
    plafond_interets_capitalises,
    solde_a_la_date,
    diagnostic_controle,
    ecarts_controle,
    ajuster_sur_solde,
    calculer,
    MODELE_PENNYLANE,
    Deblocage,
    ParametresPret,
    calculer_echeancier,
    comparer,
    exporter_pennylane,
    fonds_insuffisants,
    repartir_ecart,
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
    # Solde au 05/03/2026 : fonds réellement versés (21 672,72 €) + intérêts ajoutés au capital.
    assert e["Solde (€)"].iloc[2] == pytest.approx(21_672.72 + r.interets_capitalises_calcules)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)
    # Échéances constantes dès la fin du différé, malgré les déblocages de juin.
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
    r = calculer(p)
    e, base = r.echeancier, r.capital_amorti  # tableau du prêt complet
    avril, mai = e.iloc[3], e.iloc[4]  # 05/03 → 05/04 : 31 jours ; 05/04 → 05/05 : 30 jours
    assert avril["Intérêt (€)"] == pytest.approx(base * 0.0417 * 31 / 365, abs=0.01)
    assert mai["Intérêt (€)"] == pytest.approx((base - avril["Amortissement (€)"]) * 0.0417 * 30 / 365, abs=0.01)


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


def test_solde_reel_egal_au_grand_livre_plus_interets_capitalises():
    """Le solde suit les déblocages : il égale à chaque date le solde du compte 164 + 185,76 € capitalisés."""
    p = pret_banque(468.45)
    p.interets_capitalises_imposes = 185.76
    e = calculer_echeancier(p)
    grand_livre = {date(2026, 4, 5): 21_288.32, date(2026, 5, 5): 20_902.58, date(2026, 6, 5): 21_235.93,
                   date(2026, 7, 5): 22_454.35, date(2026, 8, 5): 22_064.57, date(2026, 9, 5): 21_673.44}
    for jour, solde_164 in grand_livre.items():
        assert e.loc[e["Date"] == jour, "Solde (€)"].iloc[0] == pytest.approx(solde_164 + 185.76)


def test_ajustement_sans_differe_recalcule_l_echeance():
    p = pret_simple()
    p.echeance_imposee = 400.0  # échéance erronée
    a = ajuster_sur_solde(p, date(2026, 12, 15), 19_591.09)  # CRD du fichier type Pennylane au 10/12/2026
    assert a.levier == "échéance"
    assert a.parametres.echeance_imposee == pytest.approx(443.84)
    assert a.solde_obtenu == pytest.approx(19_591.09)


def test_ajustement_avant_la_premiere_echeance():
    assert ajuster_sur_solde(pret_simple(), date(2025, 12, 1), 24_000) is None


def pret_partiel(**options):
    """Prêt de 10 000 € sur 80 mois à 4 %, dont 7 500 € seulement débloqués."""
    valeurs = dict(
        capital=10_000,
        taux=4.0,
        nb_echeances=80,
        date_premier_paiement=date(2026, 1, 10),
        jour_prelevement=10,
        montant_debloque=7_500,
    )
    return ParametresPret(**{**valeurs, **options})


def test_partiel_echeance_maintenue_solde_le_capital_plus_tot():
    r = calculer(pret_partiel(partiel_duree_reduite=True))
    e = r.echeancier
    assert r.echeance_constante == pytest.approx(142.61)  # échéance du prêt complet de 10 000 €
    assert len(e) == 80  # la durée saisie est conservée
    assert r.rang_capital_solde == 58  # capital soldé à la 58e échéance
    assert set(e["Échéance (€)"].iloc[:57]) == {142.61}
    assert (e.iloc[58:][["Intérêt (€)", "Amortissement (€)", "Échéance (€)", "Solde (€)"]] == 0).all().all()
    assert e["Amortissement (€)"].sum() == pytest.approx(7_500)


def test_partiel_l_assurance_continue_apres_le_solde_du_capital():
    e = calculer_echeancier(pret_partiel(assurance_mensuelle=3.0))
    assert len(e) == 80
    assert set(e["Assurance (€)"]) == {3.00}  # coût mensuel saisi, sur toute la durée
    assert (e["Échéance (€)"].iloc[58:] == 3.00).all()


def test_assurance_en_pourcentage_du_capital_restant_du():
    e = calculer_echeancier(pret_partiel(assurance_taux_crd=0.36))
    # 1re échéance : 7 500 € restant dû x 0,36 % / 12
    assert e["Assurance (€)"].iloc[0] == pytest.approx(2.25)
    # 2e échéance : sur le capital restant dû après la 1re
    assert e["Assurance (€)"].iloc[1] == pytest.approx(round(e["Solde (€)"].iloc[0] * 0.0036 / 12, 2))
    # L'assurance diminue avec le capital et s'arrête une fois celui-ci soldé (58e échéance).
    assert e["Assurance (€)"].is_monotonic_decreasing
    assert (e["Assurance (€)"].iloc[58:] == 0).all()


def test_assurance_en_pourcentage_trimestrielle_et_export(tmp_path):
    p = pret_partiel(assurance_taux_crd=0.36, periodicite="Trimestrielle", nb_echeances=27)
    e = calculer_echeancier(p)
    assert e["Assurance (€)"].iloc[0] == pytest.approx(6.75)  # 7 500 x 0,36 % x 3 / 12
    fichier = tmp_path / "assurance.xlsx"
    fichier.write_bytes(exporter_pennylane(p, e))
    ws = openpyxl.load_workbook(fichier).active
    assert ws["C2"].value == 0.36
    assert ws["D2"].value == pytest.approx(round(e["Assurance (€)"].sum(), 2))


def test_echeance_saisie_assurance_comprise():
    """468,45 € hors assurance + 12,50 € d'assurance = 480,95 € saisis : même tableau que le prêt n°141."""
    hors_assurance = pret_banque(468.45)
    hors_assurance.assurance_mensuelle = 12.5
    comprise = replace(hors_assurance, echeance_imposee=480.95, echeance_assurance_comprise=True)
    e1, e2 = calculer_echeancier(hors_assurance), calculer_echeancier(comprise)
    assert e2.equals(e1)
    assert set(e2["Échéance (€)"].iloc[3:-1]) == {480.95}


def test_echeance_assurance_comprise_en_pourcentage_du_crd():
    p = pret_partiel(montant_debloque=None, echeance_imposee=145.61, echeance_assurance_comprise=True, assurance_taux_crd=0.36)
    e = calculer_echeancier(p)
    # 1re échéance : 142,61 € de crédit + 3,00 € d'assurance (10 000 € x 0,36 % / 12).
    assert e["Échéance (€)"].iloc[0] == pytest.approx(145.61)
    assert e["Intérêt (€)"].iloc[0] + e["Amortissement (€)"].iloc[0] == pytest.approx(142.61)


def test_assurance_mensuelle_ramenee_a_la_periodicite():
    e = calculer_echeancier(pret_partiel(assurance_mensuelle=12.5, periodicite="Trimestrielle", nb_echeances=27))
    assert set(e["Assurance (€)"]) == {37.50}  # 3 mois x 12,50 €
    assert e["Échéance (€)"].iloc[0] == pytest.approx(e["Intérêt (€)"].iloc[0] + e["Amortissement (€)"].iloc[0] + 37.50)


def test_partiel_duree_maintenue_reduit_l_echeance():
    r = calculer(pret_partiel(partiel_duree_reduite=False))
    e = r.echeancier
    assert len(e) == 80
    assert r.rang_capital_solde == 80
    assert r.echeance_constante == pytest.approx(106.96)  # 7 500 € sur 80 mois
    assert e["Amortissement (€)"].sum() == pytest.approx(7_500)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)


def test_partiel_echeance_bancaire_decide_de_la_duree():
    assert calculer(pret_partiel(echeance_imposee=142.61)).rang_capital_solde == 58
    assert calculer(pret_partiel(echeance_imposee=106.96)).rang_capital_solde == 80


def test_partiel_export_porte_sur_le_montant_debloque(tmp_path):
    p = pret_partiel()
    fichier = tmp_path / "partiel.xlsx"
    fichier.write_bytes(exporter_pennylane(p, calculer_echeancier(p)))
    ws = openpyxl.load_workbook(fichier).active
    assert ws["A2"].value == 7_500
    assert ws["G2"].value == 80
    assert ws.max_row == 5 + 80


@pytest.mark.parametrize("periodicite, mois, nombre", [("Mensuelle", 1, 80), ("Trimestrielle", 3, 27), ("Semestrielle", 6, 14), ("Annuelle", 12, 7)])
@pytest.mark.parametrize("duree_reduite", [True, False])
def test_periodicites_en_deblocage_partiel(periodicite, mois, nombre, duree_reduite):
    e = calculer_echeancier(pret_partiel(periodicite=periodicite, nb_echeances=nombre, partiel_duree_reduite=duree_reduite))
    assert (e["Date"].iloc[1] - e["Date"].iloc[0]).days in range(28 * mois, 31 * mois + 1)
    assert e["Amortissement (€)"].sum() == pytest.approx(7_500)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)
    assert len(e) == nombre
    solde_avant_terme = (e["Solde (€)"].iloc[:-1] == 0).any()
    assert solde_avant_terme if duree_reduite else not solde_avant_terme


def pret_deux_deblocages(**options):
    """Prêt de 10 000 € sur 24 mois à 4 % : 6 000 € versés le 15/12/2025, 4 000 € le 20/03/2026."""
    valeurs = dict(
        capital=10_000,
        taux=4.0,
        nb_echeances=24,
        date_premier_paiement=date(2026, 1, 10),
        jour_prelevement=10,
        deblocages=[Deblocage(date(2025, 12, 15), 6_000), Deblocage(date(2026, 3, 20), 4_000)],
    )
    return ParametresPret(**{**valeurs, **options})


def test_echeances_totales_par_defaut():
    e = calculer_echeancier(pret_deux_deblocages())
    # Échéance constante du prêt complet (10 000 € sur 24 mois), quelles que soient les dates de déblocage.
    assert set(e["Échéance (€)"].iloc[:-1]) == {434.25}
    theorique = calculer_echeancier(pret_deux_deblocages(deblocages=[Deblocage(date(2025, 12, 10), 10_000)]))
    assert e["Amortissement (€)"].tolist() == theorique["Amortissement (€)"].tolist()
    # Le solde suit les fonds réellement versés : 6 000 € jusqu'au 20/03/2026, puis 10 000 €.
    assert e["Solde (€)"].iloc[0] == pytest.approx(6_000 - e["Amortissement (€)"].iloc[0])
    assert e["Solde (€)"].iloc[3] == pytest.approx(theorique["Solde (€)"].iloc[3])


def test_echeances_proratisees_jusqu_au_dernier_deblocage():
    e = calculer_echeancier(pret_deux_deblocages(echeance_proratisee=True))
    # Tant que 6 000 € sur 10 000 € sont versés : 60 % de l'échéance.
    assert e["Échéance (€)"].iloc[:3].tolist() == [260.55] * 3
    # 1re échéance : intérêts sur les 6 000 € du 15/12/2025 au 10/01/2026 (26 jours).
    assert e["Intérêt (€)"].iloc[0] == pytest.approx(6_000 * 0.04 * 26 / 365, abs=0.01)
    # Échéance d'avril : tout est versé, échéance entière ; intérêts des 4 000 € au prorata (21 jours).
    assert e["Échéance (€)"].iloc[3] == pytest.approx(434.25)
    # Ensuite : échéance recalculée pour solder le prêt au terme.
    assert len(set(e["Échéance (€)"].iloc[4:-1])) == 1
    assert len(e) == 24
    assert e["Amortissement (€)"].sum() == pytest.approx(10_000)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)


def test_proratisation_sans_effet_si_tout_est_verse_avant_la_1re_echeance():
    p = pret_deux_deblocages(echeance_proratisee=True)
    p.deblocages = [Deblocage(date(2025, 12, 1), 6_000), Deblocage(date(2025, 12, 20), 4_000)]
    assert calculer_echeancier(p).equals(calculer_echeancier(replace(p, echeance_proratisee=False)))


def test_proratisation_sur_le_pret_141():
    """Prêt n°141 : les déblocages de juin interviennent après la 1re échéance d'amortissement (05/04/2026)."""
    p = pret_banque(468.45)
    p.interets_capitalises_imposes = 185.76
    totale = calculer_echeancier(p)
    proratisee = calculer_echeancier(replace(p, echeance_proratisee=True))
    assert proratisee["Échéance (€)"].iloc[3] < totale["Échéance (€)"].iloc[3]  # avril : fonds pas tous versés
    assert proratisee["Amortissement (€)"].sum() == pytest.approx(totale["Amortissement (€)"].sum())
    assert proratisee["Solde (€)"].iloc[-1] == pytest.approx(0)


def test_diagnostic_du_controle_avec_le_grand_livre():
    p = pret_banque(468.45)
    p.interets_capitalises_imposes = 185.76
    p.assurance_mensuelle = 3.12
    e = calculer_echeancier(p)
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    assert diagnostic_controle(comparer(e, remboursements)) == "capital"
    # Grand livre où l'échéance est passée en totalité au 164 (capital + assurance).
    avec_assurance = remboursements.assign(**{"Capital remboursé (€)": remboursements["Capital remboursé (€)"] + 3.12})
    assert diagnostic_controle(comparer(e, avec_assurance)) == "capital + assurance"
    fausse = remboursements.assign(**{"Capital remboursé (€)": remboursements["Capital remboursé (€)"] + 10})
    assert diagnostic_controle(comparer(e, fausse)) is None


def test_echeance_saisie_sans_differe_ne_modifie_pas_le_capital():
    for echeance in (20.0, 358.05, 434.25, 5_000.0):
        r = calculer(replace(pret_simple(), echeance_imposee=echeance))
        assert r.capital_amorti == pytest.approx(24_000)
        assert (r.echeancier["Amortissement (€)"] >= 0).all()  # jamais de capital négatif
        assert r.echeancier["Amortissement (€)"].sum() == pytest.approx(24_000)


def test_pret_a_taux_nul_jamais_d_interets_capitalises():
    p = ParametresPret(capital=4_447.14, taux=0.0, nb_echeances=72, nb_echeances_differe=2,
                       date_premier_paiement=date(2025, 6, 15), jour_prelevement=15)
    for cible in (3_000, 4_000):
        a = ajuster_sur_solde(p, date(2026, 7, 20), cible)
        assert a.possible and a.levier == "échéance" and abs(a.ecart) <= 0.5
        r = calculer(a.parametres)
        assert r.capital_amorti == pytest.approx(4_447.14)  # rien au-delà du capital emprunté


def test_ajustement_impossible_ne_modifie_rien():
    p = pret_deux_deblocages()
    a = ajuster_sur_solde(p, date(2026, 6, 10), 12_000)  # plus que le capital emprunté
    assert not a.possible and a.parametres == p
    assert a.fourchette[1] <= 10_000
    b = ajuster_sur_solde(replace(pret_banque(), interets_differe_capitalises=False), date(2026, 2, 10), 15_000)
    assert not b.possible  # pendant le différé, le solde ne dépend pas de l'échéance


def test_ajustement_retombe_sur_le_solde_saisi():
    p = pret_deux_deblocages()
    for jour, cible in ((date(2026, 6, 10), 7_000), (date(2027, 1, 10), 3_000), (date(2026, 1, 10), 5_800)):
        a = ajuster_sur_solde(p, jour, cible)
        assert a.possible and abs(a.ecart) <= 0.05
        assert solde_a_la_date(a.parametres, jour)[1] == pytest.approx(cible, abs=0.05)


@pytest.mark.parametrize("taux", [0.0, 2.0, 4.17])
@pytest.mark.parametrize("differe", [0, 3])
@pytest.mark.parametrize("interets_imposes", [None, 0.0, 50.0, 1_000_000.0])
def test_capital_rembourse_jamais_superieur_au_capital_de_base(taux, differe, interets_imposes):
    p = pret_banque(468.45)
    p = replace(p, taux=taux, nb_echeances_differe=differe, interets_capitalises_imposes=interets_imposes)
    r = calculer(p)
    e = r.echeancier
    assert r.capital_amorti <= 24_000 + plafond_interets_capitalises(p) + 0.005
    assert e["Amortissement (€)"].sum() == pytest.approx(24_000, abs=0.01)  # capital net remboursé = capital emprunté
    assert (e["Amortissement (€)"].iloc[differe:] >= 0).all()
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)


def pret_10000(**options):
    valeurs = dict(capital=10_000, taux=4.0, nb_echeances=24, date_premier_paiement=date(2026, 1, 10), jour_prelevement=10)
    return ParametresPret(**{**valeurs, **options})


def test_remboursement_anticipe_partiel_duree_reduite():
    r = calculer(pret_10000(remboursements_anticipes=[RemboursementAnticipe(date(2026, 4, 1), 3_000)]))
    e = r.echeancier
    assert r.anticipes == [(date(2026, 4, 10), 3_000.0, 0.0)]  # rattaché à l'échéance suivante
    assert e["Amortissement (€)"].iloc[3] == pytest.approx(404.94 + 3_000)
    assert set(e["Échéance (€)"].iloc[4:-1]) == {434.25}  # échéance maintenue…
    assert len(e) == 17  # … donc durée réduite, et plus d'échéance après le solde
    assert e["Amortissement (€)"].sum() == pytest.approx(10_000)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)


def test_remboursement_anticipe_partiel_echeance_reduite():
    e = calculer_echeancier(pret_10000(
        remboursements_anticipes=[RemboursementAnticipe(date(2026, 4, 1), 3_000)], anticipe_reduit_duree=False
    ))
    assert len(e) == 24  # durée maintenue
    assert e["Échéance (€)"].iloc[4] < 434.25 and len(set(e["Échéance (€)"].iloc[4:-1])) == 1
    assert e["Amortissement (€)"].sum() == pytest.approx(10_000)
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)


def test_remboursement_anticipe_total_avec_indemnites(tmp_path):
    p = pret_10000(remboursements_anticipes=[RemboursementAnticipe(date(2026, 9, 10), total=True, indemnites=150)])
    e = calculer_echeancier(p)
    assert len(e) == 9 and e["Date"].iloc[-1] == date(2026, 9, 10)
    assert e["Solde (€)"].iloc[-1] == 0 and e["Autres frais (€)"].iloc[-1] == 150
    assert e["Amortissement (€)"].sum() == pytest.approx(10_000)
    fichier = tmp_path / "anticipe.xlsx"
    fichier.write_bytes(exporter_pennylane(p, e))
    ws = openpyxl.load_workbook(fichier).active
    assert ws["F2"].value == 150 and ws["G2"].value == 9 and ws.max_row == 5 + 9


def test_remboursement_anticipe_ne_rembourse_jamais_plus_que_le_capital():
    for montant in (500, 9_000, 50_000):
        for duree in (True, False):
            e = calculer_echeancier(pret_10000(
                remboursements_anticipes=[RemboursementAnticipe(date(2026, 6, 10), montant)], anticipe_reduit_duree=duree
            ))
            assert e["Amortissement (€)"].sum() == pytest.approx(10_000)
            assert (e["Amortissement (€)"] >= 0).all() and (e["Solde (€)"] >= 0).all()


def test_remboursement_anticipe_amortissement_constant_et_differe():
    e = calculer_echeancier(pret_10000(
        type_remboursement="Amortissement constant", remboursements_anticipes=[RemboursementAnticipe(date(2026, 3, 10), 2_000)]
    ))
    assert e["Amortissement (€)"].iloc[2] == pytest.approx(416.67 + 2_000) and len(e) < 24
    assert e["Amortissement (€)"].sum() == pytest.approx(10_000)
    p = pret_banque(468.45)
    p.interets_capitalises_imposes = 185.76
    p.remboursements_anticipes = [RemboursementAnticipe(date(2027, 1, 5), 5_000)]
    e = calculer_echeancier(p)
    assert e["Amortissement (€)"].iloc[12] == pytest.approx(396.60 + 5_000)  # rang 13 du tableau bancaire
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)


def test_appliquer_les_montants_du_grand_livre():
    p = pret_banque(468.45)
    p.interets_capitalises_imposes = 185.76
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    grand_livre = remboursements.assign(**{"Capital remboursé (€)": remboursements["Capital remboursé (€)"] + 10})
    controle = comparer(calculer_echeancier(p), grand_livre)
    assert diagnostic_controle(controle) is None  # écart inexpliqué
    e = calculer_echeancier(replace(p, capital_impose=capital_constate(controle, None)))
    # Le capital des échéances comptabilisées est repris du grand livre…
    assert diagnostic_controle(comparer(e, grand_livre)) == "capital"
    # … puis l'échéance est recalculée pour finir au terme, sans rembourser plus que le capital.
    assert len(e) == 60 and e["Solde (€)"].iloc[-1] == pytest.approx(0)
    assert len(set(e["Échéance (€)"].iloc[9:-1])) == 1
    assert e["Amortissement (€)"].sum() == pytest.approx(24_000)


def test_appliquer_le_grand_livre_retire_l_assurance_passee_au_164():
    p = pret_banque(468.45)
    p.interets_capitalises_imposes, p.assurance_mensuelle = 185.76, 3.12
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    avec_assurance = remboursements.assign(**{"Capital remboursé (€)": remboursements["Capital remboursé (€)"] + 3.12})
    controle = comparer(calculer_echeancier(p), avec_assurance)
    nature = diagnostic_controle(controle)
    assert nature == "capital + assurance"
    assert list(capital_constate(controle, nature).values()) == remboursements["Capital remboursé (€)"].tolist()


def test_appliquer_le_grand_livre_en_echeances_proratisees():
    p = replace(pret_banque(468.45), interets_capitalises_imposes=185.76, echeance_proratisee=True)
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    controle = comparer(calculer_echeancier(p), remboursements)
    assert diagnostic_controle(controle) is None  # la banque n'a pas proratisé
    e = calculer_echeancier(replace(p, capital_impose=capital_constate(controle, None)))
    assert diagnostic_controle(comparer(e, remboursements)) == "capital"
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0) and e["Amortissement (€)"].sum() == pytest.approx(24_000)


def test_modifier_le_capital_d_une_echeance():
    e = calculer_echeancier(pret_10000(corrections={date(2026, 3, 10): {"amortissement": 500}}))
    assert e["Amortissement (€)"].iloc[2] == 500
    assert len(set(e["Échéance (€)"].iloc[3:-1])) == 1  # échéances suivantes recalculées…
    assert e["Échéance (€)"].iloc[3] < 434.25
    assert len(e) == 24 and e["Solde (€)"].iloc[-1] == 0  # … pour solder le prêt au terme
    assert e["Amortissement (€)"].sum() == pytest.approx(10_000)


def test_modifier_un_interet_conserve_l_echeance():
    e = calculer_echeancier(pret_10000(corrections={date(2026, 5, 10): {"interet": 40}}))
    assert e["Intérêt (€)"].iloc[4] == 40 and e["Échéance (€)"].iloc[4] == pytest.approx(434.25)
    assert e["Amortissement (€)"].sum() == pytest.approx(10_000) and e["Solde (€)"].iloc[-1] == 0


def test_modifier_l_echeance_et_plusieurs_lignes():
    corrections = {
        date(2026, 3, 10): {"amortissement": 500},
        date(2026, 5, 10): {"interet": 40},
        date(2026, 8, 10): {"echeance": 600},
    }
    e = calculer_echeancier(pret_10000(assurance_mensuelle=5, corrections=corrections))
    assert e["Échéance (€)"].iloc[7] == pytest.approx(605)  # 600 € + 5 € d'assurance, exactement
    assert e["Amortissement (€)"].iloc[2] == 500 and e["Intérêt (€)"].iloc[4] == 40
    assert e["Amortissement (€)"].sum() == pytest.approx(10_000) and e["Solde (€)"].iloc[-1] == 0


def test_modifier_assurance_frais_et_interet_du_differe():
    p = replace(pret_banque(468.45), interets_capitalises_imposes=None, remboursements_constates=[])
    jour = date(2026, 2, 5)  # échéance de différé
    e0 = calculer(p)
    r = calculer(replace(p, corrections={jour: {"interet": 100, "assurance": 7, "frais": 2}}))
    e = r.echeancier
    assert e["Intérêt (€)"].iloc[1] == 100 and e["Assurance (€)"].iloc[1] == 7 and e["Autres frais (€)"].iloc[1] == 2
    # L'intérêt corrigé du différé s'ajoute au capital (dans la limite vraisemblable).
    assert r.interets_capitalises_calcules > e0.interets_capitalises_calcules
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)


def test_la_derniere_echeance_solde_toujours_le_capital():
    e = calculer_echeancier(pret_10000(corrections={date(2027, 12, 10): {"amortissement": 1}}))
    assert e["Solde (€)"].iloc[-1] == 0 and e["Amortissement (€)"].sum() == pytest.approx(10_000)


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


def test_pas_de_fonds_insuffisants_sur_le_pret_de_la_banque():
    p = pret_banque(468.45)
    assert fonds_insuffisants(p, calculer_echeancier(p)) is None


def test_deblocage_trop_tardif_signale_au_lieu_d_un_solde_negatif():
    # Échéances totales : le prêt complet est amorti dès la 1re échéance, mais le dernier déblocage arrive
    # après que le capital déjà versé est entièrement remboursé.
    p = ParametresPret(
        capital=20_000,
        taux=3,
        nb_echeances=12,
        date_premier_paiement=date(2026, 1, 5),
        jour_prelevement=5,
        deblocages=[Deblocage(date(2025, 12, 10), 5_000), Deblocage(date(2026, 11, 20), 15_000)],
    )
    echeancier = calculer_echeancier(p)
    insuffisance = fonds_insuffisants(p, echeancier)
    assert insuffisance is not None
    assert insuffisance.depassement > 0
    assert insuffisance.date_echeance < date(2026, 11, 20)
    assert [d.date for d in insuffisance.deblocages_tardifs] == [date(2026, 11, 20)]
    # Échéances proratisées : les remboursements suivent les fonds versés, la chronologie est cohérente.
    p = replace(p, echeance_proratisee=True)
    assert fonds_insuffisants(p, calculer_echeancier(p)) is None


def test_repartition_des_interets_capitalises_jamais_negative():
    # Long différé de petits montants : l'accumulation des arrondis ne doit pas rendre une ligne négative.
    montants = repartir_ecart([0.10] * 58 + [0.98], 5.52)
    assert min(montants) >= 0
    assert round(sum(montants), 2) == 5.52


def test_derniere_echeance_sans_interet_negatif():
    # Échéance saisie très faible : l'ajustement d'arrondi de la dernière échéance ne crée pas d'intérêt négatif.
    p = ParametresPret(
        capital=1, taux=0.001, nb_echeances=2, nb_echeances_differe=1, date_premier_paiement=date(2022, 2, 1),
        jour_prelevement=1, interets_differe_capitalises=False, periodicite="Trimestrielle", echeance_imposee=1,
        echeance_assurance_comprise=True, assurance_taux_crd=5,
    )
    assert (calculer_echeancier(p)["Intérêt (€)"] >= 0).all()


def test_correction_d_un_interet_du_differe_retenue_sans_negatif_ailleurs():
    p = pret_banque(468.45)
    jour = calculer_echeancier(p)["Date"].iloc[1]
    e = calculer_echeancier(replace(p, corrections={jour: {"interet": 500.0}}))
    assert e["Intérêt (€)"].iloc[1] == 500.0
    assert (e["Intérêt (€)"] >= 0).all()


def test_ajustement_sur_un_solde_nul_solde_le_pret_a_la_date_indiquee():
    p = pret_simple()
    ajustement = ajuster_sur_solde(p, date(2028, 1, 5), 0.0)
    assert ajustement.possible and ajustement.solde_obtenu == 0
    e = calculer_echeancier(ajustement.parametres)
    # Capital soldé à la dernière échéance avant la date (10/12/2027), pas avant : échéance la plus faible.
    assert e.loc[e["Date"] == date(2027, 11, 10), "Solde (€)"].iloc[0] > 0


def pret_suspendu(capital_seul, allonge, **autres):
    return ParametresPret(
        capital=12_000, taux=3.0, nb_echeances=24, date_premier_paiement=date(2026, 1, 5), jour_prelevement=5,
        suspensions=[Suspension(date(2026, 6, 1), 3, capital_seul)], suspension_allonge_duree=allonge, **autres,
    )


def test_suspension_du_capital_seul_allonge_la_duree_sans_changer_l_echeance():
    sans = calculer_echeancier(replace(pret_suspendu(True, True), suspensions=[]))
    e = calculer_echeancier(pret_suspendu(True, True))
    assert len(e) == 27 and e["Solde (€)"].iloc[-1] == 0
    suspendues = e.iloc[5:8]
    assert (suspendues["Amortissement (€)"] == 0).all()
    assert (suspendues["Échéance (€)"] == suspendues["Intérêt (€)"]).all()  # seuls les intérêts sont payés
    # Échéance inchangée avant et après la suspension, et capital remboursé identique.
    assert e["Échéance (€)"].iloc[8] == sans["Échéance (€)"].iloc[0] == e["Échéance (€)"].iloc[0]
    assert round(e["Amortissement (€)"].sum(), 2) == 12_000


def test_suspension_du_capital_et_des_interets_les_ajoute_au_capital():
    e = calculer_echeancier(pret_suspendu(False, True))
    suspendues = e.iloc[5:8]
    assert (suspendues["Échéance (€)"] == 0).all()
    assert (suspendues["Amortissement (€)"] == -suspendues["Intérêt (€)"]).all()
    assert e["Solde (€)"].iloc[7] == round(e["Solde (€)"].iloc[4] + suspendues["Intérêt (€)"].sum(), 2)
    assert len(e) == 27 and e["Solde (€)"].iloc[-1] == 0
    assert e["Échéance (€)"].iloc[8] > e["Échéance (€)"].iloc[0]  # échéance recalculée à la reprise


@pytest.mark.parametrize("capital_seul", [True, False])
def test_suspension_a_duree_maintenue_recalcule_l_echeance(capital_seul):
    e = calculer_echeancier(pret_suspendu(capital_seul, False))
    assert len(e) == 24 and e["Solde (€)"].iloc[-1] == 0
    assert e["Échéance (€)"].iloc[8] > e["Échéance (€)"].iloc[0]
    assert abs(e["Échéance (€)"].iloc[-1] - e["Échéance (€)"].iloc[8]) < 1


def test_suspension_en_amortissement_constant_et_dates():
    p = pret_suspendu(True, True, type_remboursement="Amortissement constant")
    e = calculer_echeancier(p)
    assert len(e) == 27 and e["Solde (€)"].iloc[-1] == 0
    assert (e["Amortissement (€)"].iloc[5:8] == 0).all() and e["Amortissement (€)"].iloc[8] == 500
    assert list(dates_suspendues(p)) == [date(2026, 6, 5), date(2026, 7, 5), date(2026, 8, 5)]


def test_suspension_en_echeances_proratisees_et_export(tmp_path):
    p = ParametresPret(
        capital=20_000, taux=4, nb_echeances=36, date_premier_paiement=date(2026, 1, 5), jour_prelevement=5,
        deblocages=[Deblocage(date(2025, 12, 1), 10_000), Deblocage(date(2026, 3, 20), 10_000)],
        echeance_proratisee=True, suspensions=[Suspension(date(2026, 7, 1), 2, False)],
    )
    e = calculer_echeancier(p)
    assert len(e) == 38 and e["Solde (€)"].iloc[-1] == 0
    assert (e["Échéance (€)"].iloc[6:8] == 0).all()
    assert exporter_pennylane(p, e)


@pytest.mark.parametrize("allonge", [True, False])
def test_interets_reportes_non_capitalises_etales(allonge):
    p = pret_suspendu(False, allonge)
    p.suspensions[0].interets_reportes = True
    r = calculer(p)
    e = r.echeancier
    suspendues = e.iloc[5:8]
    assert (suspendues[["Intérêt (€)", "Amortissement (€)", "Échéance (€)"]] == 0).all().all()
    assert (e["Solde (€)"].iloc[5:8] == e["Solde (€)"].iloc[4]).all()  # le capital n'augmente pas
    assert e["Solde (€)"].iloc[-1] == 0 and len(e) == (27 if allonge else 24)
    # Les intérêts reportés sont payés ensuite : même total que s'ils avaient été payés à leur date.
    capital_seul = calculer_echeancier(pret_suspendu(True, allonge))
    assert r.interets_reportes == round(capital_seul["Intérêt (€)"].iloc[5:8].sum(), 2)
    assert round(e["Intérêt (€)"].sum(), 2) == round(capital_seul["Intérêt (€)"].sum(), 2)
    assert (e["Amortissement (€)"] == capital_seul["Amortissement (€)"]).all()


def test_interets_reportes_payes_en_une_fois_a_la_reprise():
    p = replace(pret_suspendu(False, True), interets_reportes_etales=False)
    p.suspensions[0].interets_reportes = True
    r = calculer(p)
    e, capital_seul = r.echeancier, calculer_echeancier(pret_suspendu(True, True))
    assert e["Intérêt (€)"].iloc[8] == round(capital_seul["Intérêt (€)"].iloc[8] + r.interets_reportes, 2)
    assert (e["Intérêt (€)"].iloc[9:] == capital_seul["Intérêt (€)"].iloc[9:]).all()


def test_ajouter_et_supprimer_des_echeances():
    p = pret_suspendu(True, True, )
    p = replace(p, suspensions=[])
    base = calculer_echeancier(p)
    # Échéance supprimée : 23 échéances, période de 2 mois au taux de la durée réelle, prêt soldé.
    e = calculer_echeancier(replace(p, corrections={date(2026, 6, 5): {"supprimee": True}}))
    assert len(e) == 23 and date(2026, 6, 5) not in set(e["Date"]) and e["Solde (€)"].iloc[-1] == 0
    assert e["Échéance (€)"].iloc[0] > base["Échéance (€)"].iloc[0]
    deux_mois = e[e["Date"] == date(2026, 7, 5)].iloc[0]
    precedent = e[e["Date"] == date(2026, 5, 5)].iloc[0]
    assert deux_mois["Intérêt (€)"] == round(precedent["Solde (€)"] * 0.03 * 61 / 365, 2)
    # Échéance ajoutée : 25 échéances, insérée à sa date.
    e = calculer_echeancier(replace(p, corrections={date(2026, 6, 20): {"ajoutee": True}}))
    assert len(e) == 25 and list(e["Date"]) == sorted(e["Date"]) and e["Solde (€)"].iloc[-1] == 0
    assert e["Échéance (€)"].iloc[0] < base["Échéance (€)"].iloc[0]


def test_les_echeances_du_differe_ne_sont_ni_ajoutees_ni_supprimees():
    p = replace(pret_banque(), corrections={date(2026, 1, 5): {"supprimee": True}, date(2026, 2, 20): {"ajoutee": True}})
    assert len(calculer_echeancier(p)) == 60


def test_grand_livre_interets_inclus():
    """Débits du compte 164 = intérêts + capital : reconnus, puis appliqués comme échéances (capital = débit moins
    intérêts recalculés), ou réduits au capital si l'utilisateur choisit « capital seul »."""
    p = pret_banque(468.45)
    p.interets_capitalises_imposes = 185.76
    banque = calculer_echeancier(p)
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    controle = comparer(banque, remboursements)
    avec_interets = remboursements.assign(**{
        "Capital remboursé (€)": (remboursements["Capital remboursé (€)"] + controle["Intérêt (€)"]).round(2)
    })
    assert diagnostic_controle(comparer(banque, avec_interets)) == "capital + intérêts"
    # Échéancier calculé autrement (sans le différé calé) : écarts avec le grand livre.
    autre = replace(p, echeance_imposee=480.0)  # échéance différente : écarts avec le grand livre
    controle = comparer(calculer_echeancier(autre), avec_interets)
    nature = diagnostic_controle(controle)
    assert nature is None
    assert (ecarts_controle(controle, nature, True).abs() > 0.02).any()
    # Intérêts inclus : chaque débit devient l'échéance (intérêts + capital) de la ligne.
    e = calculer_echeancier(replace(autre, echeances_constatees=capital_constate(controle, nature, True)))
    apres = comparer(e, avec_interets)
    assert (ecarts_controle(apres, nature, True).abs() <= 0.01).all()
    assert e["Solde (€)"].iloc[-1] == pytest.approx(0)
    # Capital seul : si les débits contiennent les intérêts, les intérêts calculés en sont retirés.
    montants = capital_constate(comparer(banque, avec_interets), "capital + intérêts", False)
    assert list(montants.values()) == remboursements["Capital remboursé (€)"].tolist()


GRAND_LIVRE_CMB = Path(__file__).parent / "grand_livre_cmb_interets_inclus.xlsx"


def deblocages_cmb():
    """Crédits du grand livre, sans la ligne de reclassement des intérêts (777,71 € au 31/12/2025) : c'est à
    l'utilisateur de supprimer les lignes qui ne sont pas des déblocages."""
    deblocages, remboursements = lire_grand_livre(GRAND_LIVRE_CMB)
    return [d for d in deblocages if d.date != date(2025, 12, 31)], remboursements


def pret_cmb(**autres):
    """Prêt de 32 500 € à 3,55 % sur 48 mois, débloqué en 6 fois : 1re échéance (09/05/2025) d'intérêts seuls,
    puis 48 échéances de 727,30 €. Débits du compte 164 = capital + intérêts."""
    deblocages, _ = deblocages_cmb()
    return ParametresPret(
        capital=32_500, taux=3.55, nb_echeances=49, nb_echeances_differe=1, interets_differe_capitalises=False,
        date_premier_paiement=date(2025, 5, 9), jour_prelevement=9, deblocages=deblocages, echeance_imposee=727.30,
        echeance_assurance_comprise=True, **autres,
    )


def test_grand_livre_tous_les_credits_sont_des_deblocages():
    deblocages, remboursements = lire_grand_livre(GRAND_LIVRE_CMB)
    assert len(deblocages) == 7 and len(remboursements) == 8  # y compris le reclassement, à supprimer à la main
    assert len(deblocages_cmb()[0]) == 6 and round(sum(d.montant for d in deblocages_cmb()[0]), 2) == 32_500


def test_capital_du_pret_complet_interets_sur_fonds_verses():
    """Méthode de la banque : capital de l'échéance constante du prêt complet, intérêts sur les fonds versés
    (jour du versement compris). Débits du grand livre reproduits au centime, sauf 0,13 € le 09/06/2025 (fonds
    du 16/05/2025 probablement en valeur au 15/05) et l'arrondi des intérêts du 09/05/2025."""
    _, remboursements = deblocages_cmb()
    e = calculer_echeancier(pret_cmb(interets_fonds_verses=True, jour_versement_inclus=True))
    ecarts = (e["Échéance (€)"].iloc[:8].values - remboursements["Capital remboursé (€)"].values).round(2)
    assert list(ecarts) == [0.01, -0.13, 0, 0, 0, 0, 0, 0]
    assert (e["Amortissement (€)"].iloc[1:8] == [631.15, 633.02, 634.89, 636.77, 638.66, 640.55, 642.44]).all()
    assert e["Solde (€)"].iloc[-1] == 0 and len(e) == 49
    # Les autres modes ne reproduisent pas ces débits.
    for mode in ({}, {"echeance_proratisee": True}):
        autre = calculer_echeancier(pret_cmb(**mode))
        assert abs(autre["Échéance (€)"].iloc[1] - 671.27) > 50


def test_ajustement_apres_grand_livre_et_modifications():
    """L'ajustement sur un capital restant dû est calculé sur l'ensemble des critères : le grand livre appliqué et
    les modifications du tableau restent en place, et le solde visé est celui de l'échéancier final."""
    p = pret_banque(468.45)
    _, remboursements = lire_grand_livre(GRAND_LIVRE)
    grand_livre = remboursements.assign(**{"Capital remboursé (€)": remboursements["Capital remboursé (€)"] + 10})
    p = replace(p, capital_impose=capital_constate(comparer(calculer_echeancier(p), grand_livre), None))
    p = replace(p, corrections={date(2027, 1, 5): {"interet": 60.0}})
    ajustement = ajuster_sur_solde(p, date(2027, 6, 5), 18_000)
    assert ajustement.possible and ajustement.levier == "échéance après les montants imposés"
    e = calculer_echeancier(ajustement.parametres)
    assert solde_a_la_date(ajustement.parametres, date(2027, 6, 5))[1] == pytest.approx(18_000, abs=0.05)
    assert (comparer(e, grand_livre)["Écart (€)"].dropna().abs() < 0.01).all()  # grand livre toujours appliqué
    assert e[e["Date"] == date(2027, 1, 5)]["Intérêt (€)"].iloc[0] == 60.0  # modification conservée
    assert e["Solde (€)"].iloc[-1] == 0


def test_repartition_jamais_de_signe_contraire():
    """Petit montant réparti sur beaucoup d'échéances : aucune part négative, total exact."""
    from echeancier import repartir
    for total, n in [(1.0, 157), (50.0, 300), (0.05, 12)]:
        parts = repartir(total, n)
        assert round(sum(parts), 2) == total and min(parts) >= 0


def test_pret_a_taux_nul_sans_interet():
    p = ParametresPret(capital=5_541.60, taux=0.0, nb_echeances=197, date_premier_paiement=date(2026, 3, 28),
                       jour_prelevement=28)
    e = calculer_echeancier(p)
    assert e["Intérêt (€)"].abs().sum() == 0 and e["Solde (€)"].iloc[-1] == 0


def test_grand_livre_sur_la_derniere_echeance_solde_le_pret():
    p = ParametresPret(capital=10_000, taux=3.55, nb_echeances=9, nb_echeances_differe=6,
                       date_premier_paiement=date(2025, 10, 10), jour_prelevement=10, periodicite="Annuelle")
    e = calculer_echeancier(p)
    mois = {d.strftime("%Y-%m"): round(a - 100, 2) for d, a in zip(e["Date"], e["Amortissement (€)"]) if a > 0}
    for cle in ("capital_impose", "echeances_constatees"):
        e2 = calculer_echeancier(replace(p, **{cle: mois}))
        assert e2["Solde (€)"].iloc[-1] == 0


def test_differe_sans_deblocage_saisi_periode_pleine():
    """Sans déblocage saisi, les fonds sont versés une période avant la 1re échéance : intérêts sur une période
    pleine (taux / 12), comme les échéances suivantes, et non en jours."""
    p = ParametresPret(capital=100_000, taux=3.42, nb_echeances=120, nb_echeances_differe=3,
                       interets_differe_capitalises=False, date_premier_paiement=date(2026, 3, 31), jour_prelevement=31)
    e = calculer_echeancier(p)
    assert (e["Intérêt (€)"].iloc[:3] == round(100_000 * 0.0342 / 12, 2)).all()


def test_pas_d_echeance_a_zero_en_fin_si_deblocage_complet():
    """Échéance saisie plus forte que nécessaire : le capital est soldé avant le terme et l'échéancier s'arrête
    là, sans échéances à 0 ; les autres frais restent répartis en totalité sur les échéances restantes."""
    p = ParametresPret(capital=10_000, taux=4.0, nb_echeances=24, date_premier_paiement=date(2026, 1, 5),
                       jour_prelevement=5, echeance_imposee=600.0, autres_frais=240.0)
    e = calculer_echeancier(p)
    assert len(e) < 24 and e["Solde (€)"].iloc[-1] == 0
    assert ((e["Intérêt (€)"] + e["Amortissement (€)"]).round(2) > 0).all()
    assert round(e["Autres frais (€)"].sum(), 2) == 240.0
    # Déblocage partiel avec l'échéance du prêt complet : les échéances à 0 restent jusqu'au terme (voulu).
    partiel = calculer_echeancier(replace(p, echeance_imposee=None, montant_debloque=7_500, autres_frais=0.0))
    assert len(partiel) == 24

import pytest

from emprunt import Pret, capacite_emprunt, mensualite, synthese, tableau_amortissement


def test_mensualite_valeur_connue():
    # 200 000 € à 3,5 % sur 20 ans -> 1 159,92 €/mois
    assert mensualite(200_000, 3.5, 240) == pytest.approx(1159.92, abs=0.01)


def test_mensualite_taux_zero():
    assert mensualite(12_000, 0, 12) == pytest.approx(1000)


def test_mensualite_duree_invalide():
    with pytest.raises(ValueError):
        mensualite(1000, 3, 0)


def test_tableau_rembourse_tout_le_capital():
    pret = Pret(montant=150_000, taux_annuel=4.1, duree_annees=15, taux_assurance=0.25)
    tableau = tableau_amortissement(pret)
    assert len(tableau) == 180
    assert tableau["Capital"].sum() == pytest.approx(150_000)
    assert tableau["Capital restant dû"].iloc[-1] == pytest.approx(0, abs=1e-6)


def test_synthese_coherente_avec_tableau():
    pret = Pret(montant=150_000, taux_annuel=4.1, duree_annees=15, taux_assurance=0.25)
    tableau = tableau_amortissement(pret)
    res = synthese(pret)
    assert res["cout_interets"] == pytest.approx(tableau["Intérêts"].sum())
    assert res["cout_assurance"] == pytest.approx(tableau["Assurance"].sum())


def test_capacite_inverse_de_la_mensualite():
    mensualite_max, capital = capacite_emprunt(4000, 200, 3.5, 20, 35)
    assert mensualite_max == pytest.approx(1200)
    assert mensualite(capital, 3.5, 240) == pytest.approx(1200)


def test_capacite_charges_superieures():
    assert capacite_emprunt(1000, 800, 3.5, 20, 35) == (0.0, 0.0)

from imagedupe.security.csv import safe_cell
def test_formula_prefixes_are_neutralized():
    for x in ['=SUM(A1:A2)','+cmd','-2+3','@x']:assert safe_cell(x).startswith("'")
    assert safe_cell('photo.jpg')=='photo.jpg'

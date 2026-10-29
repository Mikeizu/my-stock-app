import pandas as pd
from exports import safe_csv


def test_csv_quotes_formula_text_without_altering_numeric_returns():
    frame = pd.DataFrame({'Company': ['=SUM(1,2)', '  @bad', 'Normal'], 'Return': [-0.2, 0.0, 1.2]})
    text = safe_csv(frame)
    read = pd.read_csv(__import__('io').StringIO(text))
    assert read['Company'].iloc[0].startswith("'=")
    assert read['Company'].iloc[1].startswith("'")
    assert read['Company'].iloc[2] == 'Normal'
    assert read['Return'].tolist() == [-0.2, 0.0, 1.2]

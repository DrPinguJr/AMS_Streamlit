from __future__ import annotations

import datetime

from streamlit.testing.v1 import AppTest

from Contracts.generators.cfs_generator import end_of_month


def test_cfs_end_date_defaults_to_month_end_but_preserves_manual_selection() -> None:
    app = AppTest.from_file("Contracts/pages/CFS_Generator.py", default_timeout=30).run()
    expected_default = end_of_month(datetime.date.today())
    manual_end_date = expected_default - datetime.timedelta(days=1)

    assert not app.exception
    assert app.date_input(key="c_end_date").value == expected_default

    app.date_input(key="c_end_date").set_value(manual_end_date).run()
    assert app.date_input(key="c_end_date").value == manual_end_date

    different_start_date = manual_end_date - datetime.timedelta(days=manual_end_date.day)
    app.date_input(key="c_start_date").set_value(different_start_date).run()
    assert app.date_input(key="c_end_date").value == manual_end_date

    app.radio(key="contract_gen_mode").set_value("Paste Multiple Contractors").run()
    assert app.date_input(key="bulk_contract_gen_end_date").value == expected_default

    app.date_input(key="bulk_contract_gen_end_date").set_value(manual_end_date).run()
    assert app.date_input(key="bulk_contract_gen_end_date").value == manual_end_date
    assert not app.exception

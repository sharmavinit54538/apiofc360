"""Pure scenario-generator checks for the PostgreSQL payroll stress harness."""

from scripts.payroll_engine_stress import scenarios


def test_stress_scenarios_include_pf_and_tds_effective_date_boundaries():
    items = scenarios(700, 36020261114)
    assert {item["pf_wage_boundary_rupees"] for item in items if item["pf_wage_boundary_rupees"]} == {
        15_000, 20_000, 25_000, 30_000,
    }
    assert any(item["year"] == 2026 and item["month"] == 9 for item in items)

    march_payments = {
        item["payment_date"] for item in items
        if item["year"] == 2026 and item["month"] == 3
    }
    assert {"2026-03-31", "2026-04-01"}.issubset(march_payments)

    april_payments = {
        item["payment_date"] for item in items
        if item["year"] == 2026 and item["month"] == 4
    }
    assert {"2026-04-30", "2026-05-15"}.issubset(april_payments)
    assert items == scenarios(700, 36020261114)
    for item in items:
        if item["pf_wage_boundary_rupees"] is not None:
            assert item["lop_days"] == "0"
            assert item["basic_paise"] == item["pf_wage_boundary_rupees"] * 100
            assert item["overtime_paise"] == item["bonus_paise"] == item["arrear_paise"] == 0

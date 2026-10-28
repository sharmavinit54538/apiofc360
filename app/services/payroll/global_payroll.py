"""Multi-currency helpers and pluggable country statutory calculators.

Legacy Indian payroll remains in StatutoryService.  Other countries use an
explicit, versioned rules snapshot supplied by the tenant's payroll reviewer;
no time-sensitive tax rate is silently invented by this package.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol

SUPPORTED_CURRENCIES = frozenset({"INR", "USD", "GBP", "EUR", "AED", "SGD"})
CURRENCY_DEFAULT_COUNTRY = {"INR": "IN", "USD": "US", "GBP": "GB", "EUR": "EU", "AED": "AE", "SGD": "SG"}
SUPPORTED_COUNTRIES = frozenset(CURRENCY_DEFAULT_COUNTRY.values())


def normalize_currency(value: str | None, default: str = "INR") -> str:
    currency = str(value or default).strip().upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency '{value}'. Choose one of {', '.join(sorted(SUPPORTED_CURRENCIES))}.")
    return currency


def normalize_country(value: str | None, currency: str = "INR") -> str:
    country = str(value or CURRENCY_DEFAULT_COUNTRY[currency]).strip().upper()
    if country not in SUPPORTED_COUNTRIES:
        raise ValueError(f"Unsupported payroll country '{value}'. Choose one of {', '.join(sorted(SUPPORTED_COUNTRIES))}.")
    return country


def positive_fx_rate(value: Any) -> Decimal:
    try:
        rate = Decimal(str(value))
    except Exception as exc:
        raise ValueError("FX rate must be a positive decimal number.") from exc
    if not rate.is_finite() or rate <= 0:
        raise ValueError("FX rate must be a positive finite decimal number.")
    return rate.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def convert_minor_units(amount: int, rate_to_base: Any) -> int:
    """Convert integer minor units with deterministic half-up rounding."""
    return int((Decimal(int(amount)) * positive_fx_rate(rate_to_base)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def convert_via_inr_minor_units(amount: int, source_fx_to_inr: Any, target_fx_to_inr: Any) -> int:
    source = positive_fx_rate(source_fx_to_inr)
    target = positive_fx_rate(target_fx_to_inr)
    return int((Decimal(int(amount)) * source / target).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_fx_snapshot(
    *, currency: str, base_currency: str = "INR", rate_to_base: Any,
    source: str = "MANUAL", rate_as_of: datetime | None = None,
    locked_at: datetime | None = None,
) -> dict[str, Any]:
    currency = normalize_currency(currency)
    base_currency = normalize_currency(base_currency)
    rate = positive_fx_rate(rate_to_base)
    if currency == base_currency and rate != Decimal("1.00000000"):
        raise ValueError("Same-currency payroll runs must use an FX rate of 1.")
    locked = locked_at or datetime.now(UTC)
    effective = rate_as_of or locked
    return {
        "currency": currency, "base_currency": base_currency,
        "rate_to_base": str(rate), "source": str(source or "MANUAL")[:100],
        "rate_as_of": effective.isoformat(), "locked_at": locked.isoformat(),
        "minor_unit_precision": 2,
    }


@dataclass(frozen=True)
class CountryStatutoryInput:
    country_code: str
    currency: str
    gross_paise: int
    basic_paise: int
    period_month: int
    period_year: int
    rules: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CountryStatutoryResult:
    employee_deductions_paise: int
    employer_contributions_paise: int
    components: dict[str, int]
    rule_version: str
    review_required: bool
    warnings: list[str]


class CountryStatutoryCalculator(Protocol):
    country_code: str

    def calculate(self, context: CountryStatutoryInput) -> CountryStatutoryResult:
        ...


class IndiaStatutoryCalculator:
    """Marker adapter: Indian calculations stay in the mature legacy engine."""
    country_code = "IN"

    def calculate(self, context: CountryStatutoryInput) -> CountryStatutoryResult:
        return CountryStatutoryResult(0, 0, {}, "IN_LEGACY_STATUTORY_SERVICE", False, [])


class ConfigurableCountryStatutoryCalculator:
    """Versioned social-insurance/tax component calculator for non-IN runs.

    Rules contain optional ``employee_components`` and ``employer_components``.
    Each component has a unique ``code``, decimal ``rate`` and optional
    ``wage_ceiling_paise`` for the current payroll period.  Flat components can
    instead specify integer ``amount_paise``.  Missing rules never fabricate a
    contribution: they return zero plus a mandatory-review warning.
    """
    country_code = "EU"

    def _components(self, entries: Any, gross_paise: int, prefix: str, output: dict[str, int]) -> int:
        if entries is None:
            return 0
        if not isinstance(entries, list):
            raise ValueError(f"{prefix} must be a list of statutory components.")
        total = 0
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("code"):
                raise ValueError(f"Every {prefix} item requires a component code.")
            code = str(entry["code"]).strip().upper()[:40]
            if code in seen:
                raise ValueError(f"Duplicate statutory component '{code}'.")
            seen.add(code)
            ceiling = int(entry.get("wage_ceiling_paise", gross_paise))
            if ceiling < 0:
                raise ValueError("Statutory wage ceilings cannot be negative.")
            taxable = min(max(0, int(gross_paise)), ceiling)
            if "amount_paise" in entry:
                amount = int(entry["amount_paise"])
                if amount < 0:
                    raise ValueError("Statutory component amounts cannot be negative.")
            else:
                rate = Decimal(str(entry.get("rate", "0")))
                if not rate.is_finite() or not 0 <= rate <= 1:
                    raise ValueError("Statutory component rates must be between 0 and 1.")
                amount = int((Decimal(taxable) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            output[f"{prefix}:{code}"] = amount
            total += amount
        return total

    def calculate(self, context: CountryStatutoryInput) -> CountryStatutoryResult:
        rules = context.rules or {}
        version = str(rules.get("version") or "UNCONFIGURED_REVIEW_REQUIRED")
        configured = bool(rules.get("employee_components") is not None or rules.get("employer_components") is not None)
        if configured and not rules.get("version"):
            raise ValueError("Configured country statutory rules require an explicit version.")
        components: dict[str, int] = {}
        employee = self._components(rules.get("employee_components"), context.gross_paise, "EMPLOYEE", components)
        employer = self._components(rules.get("employer_components"), context.gross_paise, "EMPLOYER", components)
        warnings = [] if configured else ["Country statutory rules are unconfigured; zero statutory contributions are an estimate requiring local payroll review."]
        return CountryStatutoryResult(employee, employer, components, version, not configured, warnings)


class UnitedStatesStatutoryCalculator(ConfigurableCountryStatutoryCalculator):
    country_code = "US"


class UnitedKingdomStatutoryCalculator(ConfigurableCountryStatutoryCalculator):
    country_code = "GB"


class EuropeanUnionStatutoryCalculator(ConfigurableCountryStatutoryCalculator):
    country_code = "EU"


class UAEStatutoryCalculator(ConfigurableCountryStatutoryCalculator):
    country_code = "AE"


class SingaporeStatutoryCalculator(ConfigurableCountryStatutoryCalculator):
    country_code = "SG"


_CALCULATORS: dict[str, CountryStatutoryCalculator] = {
    "IN": IndiaStatutoryCalculator(),
    "US": UnitedStatesStatutoryCalculator(),
    "GB": UnitedKingdomStatutoryCalculator(),
    "EU": EuropeanUnionStatutoryCalculator(),
    "AE": UAEStatutoryCalculator(),
    "SG": SingaporeStatutoryCalculator(),
}


def get_country_statutory_calculator(country_code: str) -> CountryStatutoryCalculator:
    country = str(country_code).strip().upper()
    try:
        return _CALCULATORS[country]
    except KeyError as exc:
        raise ValueError(f"No statutory calculator is registered for '{country_code}'.") from exc


def register_country_statutory_calculator(country_code: str, calculator: CountryStatutoryCalculator) -> None:
    """Application-startup extension point for tenant-specific/local modules."""
    country = str(country_code).strip().upper()
    if len(country) != 2 or not country.isalpha():
        raise ValueError("Country calculator keys must be two-letter codes.")
    _CALCULATORS[country] = calculator

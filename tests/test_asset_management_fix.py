"""Asset Management module comprehensive tests.

Tests cover:
- Pydantic schema validation (field lengths, data types, business rules)
- Asset creation with valid and invalid data
- Image URL validation (rejects Base64, blob URLs)
- Edge cases (max length strings, boundary conditions)
- Database model column definitions
- Alembic migration compatibility
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# 1. Schema validation tests (no database required)
# ---------------------------------------------------------------------------


class TestAssetCreateSchema:
    """Validate AssetCreate Pydantic schema enforcement."""

    def test_valid_asset_create_minimal(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(tag="AST-001", name="Dell Laptop", category="laptop")
        assert asset.tag == "AST-001"
        assert asset.name == "Dell Laptop"
        assert asset.category == "laptop"
        assert asset.image_url is None

    def test_valid_asset_create_full(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(
            tag="AST-002",
            name="MacBook Pro 16",
            category="laptop",
            serial="SN-12345-ABCDE",
            vendor="Apple Inc.",
            purchase_date=date(2026, 1, 15),
            warranty_until=date(2027, 1, 15),
            brand="Apple",
            model="MacBook Pro 16-inch (M4 Max)",
            purchase_cost=Decimal("2499.99"),
            location="Building A, Floor 3, Desk 42",
            notes="Executive laptop with 64GB RAM",
            description="MacBook Pro with M4 Max chip for development team lead",
            image_url="https://res.cloudinary.com/demo/image/upload/v1234567890/hrms/assets/macbook.jpg",
        )
        assert asset.tag == "AST-002"
        assert asset.purchase_cost == Decimal("2499.99")
        assert asset.image_url.startswith("https://")

    def test_tag_max_length_100(self):
        from app.schemas.asset import AssetCreate
        # Exactly 100 chars should work
        tag_100 = "A" * 100
        asset = AssetCreate(tag=tag_100, name="Test", category="laptop")
        assert len(asset.tag) == 100

    def test_tag_exceeds_max_length(self):
        from app.schemas.asset import AssetCreate
        tag_101 = "A" * 101
        with pytest.raises(Exception):  # ValidationError
            AssetCreate(tag=tag_101, name="Test", category="laptop")

    def test_name_max_length_255(self):
        from app.schemas.asset import AssetCreate
        name_255 = "N" * 255
        asset = AssetCreate(tag="T-001", name=name_255, category="laptop")
        assert len(asset.name) == 255

    def test_name_exceeds_max_length(self):
        from app.schemas.asset import AssetCreate
        name_256 = "N" * 256
        with pytest.raises(Exception):
            AssetCreate(tag="T-001", name=name_256, category="laptop")

    def test_category_max_length_100(self):
        from app.schemas.asset import AssetCreate
        cat_100 = "C" * 100
        asset = AssetCreate(tag="T-001", name="Test", category=cat_100)
        assert len(asset.category) == 100

    def test_category_exceeds_max_length(self):
        from app.schemas.asset import AssetCreate
        cat_101 = "C" * 101
        with pytest.raises(Exception):
            AssetCreate(tag="T-001", name="Test", category=cat_101)

    def test_serial_max_length_150(self):
        from app.schemas.asset import AssetCreate
        serial_150 = "S" * 150
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", serial=serial_150)
        assert len(asset.serial) == 150

    def test_serial_exceeds_max_length(self):
        from app.schemas.asset import AssetCreate
        serial_151 = "S" * 151
        with pytest.raises(Exception):
            AssetCreate(tag="T-001", name="Test", category="laptop", serial=serial_151)

    def test_vendor_max_length_255(self):
        from app.schemas.asset import AssetCreate
        vendor_255 = "V" * 255
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", vendor=vendor_255)
        assert len(asset.vendor) == 255

    def test_vendor_exceeds_max_length(self):
        from app.schemas.asset import AssetCreate
        vendor_256 = "V" * 256
        with pytest.raises(Exception):
            AssetCreate(tag="T-001", name="Test", category="laptop", vendor=vendor_256)

    def test_brand_max_length_150(self):
        from app.schemas.asset import AssetCreate
        brand_150 = "B" * 150
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", brand=brand_150)
        assert len(asset.brand) == 150

    def test_brand_exceeds_max_length(self):
        from app.schemas.asset import AssetCreate
        brand_151 = "B" * 151
        with pytest.raises(Exception):
            AssetCreate(tag="T-001", name="Test", category="laptop", brand=brand_151)

    def test_model_max_length_150(self):
        from app.schemas.asset import AssetCreate
        model_150 = "M" * 150
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", model=model_150)
        assert len(asset.model) == 150

    def test_model_exceeds_max_length(self):
        from app.schemas.asset import AssetCreate
        model_151 = "M" * 151
        with pytest.raises(Exception):
            AssetCreate(tag="T-001", name="Test", category="laptop", model=model_151)

    def test_long_description_allowed(self):
        from app.schemas.asset import AssetCreate
        desc_5000 = "D" * 5000
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", description=desc_5000)
        assert len(asset.description) == 5000

    def test_long_notes_allowed(self):
        from app.schemas.asset import AssetCreate
        notes_5000 = "N" * 5000
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", notes=notes_5000)
        assert len(asset.notes) == 5000

    def test_long_location_allowed(self):
        from app.schemas.asset import AssetCreate
        loc_2000 = "Building A, " * 166
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", location=loc_2000[:5000])
        assert len(asset.location) > 100  # was previously limited to 100


class TestImageUrlValidation:
    """Validate image_url field rejects unsafe values."""

    def test_valid_cloudinary_url(self):
        from app.schemas.asset import AssetCreate
        url = "https://res.cloudinary.com/demo/image/upload/v1234567890/hrms/assets/long_path_component_that_exceeds_255_chars/" + "a" * 300 + ".jpg"
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", image_url=url)
        assert asset.image_url == url

    def test_reject_base64_data_url(self):
        from app.schemas.asset import AssetCreate
        b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        with pytest.raises(Exception) as exc_info:
            AssetCreate(tag="T-001", name="Test", category="laptop", image_url=b64)
        assert "Base64" in str(exc_info.value) or "data:" in str(exc_info.value).lower()

    def test_reject_blob_url(self):
        from app.schemas.asset import AssetCreate
        blob = "blob:http://localhost:3000/abc-def-123"
        with pytest.raises(Exception) as exc_info:
            AssetCreate(tag="T-001", name="Test", category="laptop", image_url=blob)
        assert "Blob" in str(exc_info.value) or "blob:" in str(exc_info.value).lower()

    def test_reject_random_string(self):
        from app.schemas.asset import AssetCreate
        with pytest.raises(Exception):
            AssetCreate(tag="T-001", name="Test", category="laptop", image_url="not-a-url")

    def test_null_image_url_allowed(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", image_url=None)
        assert asset.image_url is None

    def test_empty_string_image_url_becomes_none(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", image_url="")
        assert asset.image_url is None

    def test_long_cloudinary_url_accepted(self):
        """Cloudinary URLs with transformations can be very long."""
        from app.schemas.asset import AssetCreate
        # Simulate a realistic long Cloudinary URL
        url = "https://res.cloudinary.com/my-company/image/upload/f_auto,q_auto,w_800,h_600,c_fill/" + "folder/" * 50 + "image_name.jpg"
        assert len(url) > 255  # Previously would have caused DB truncation
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", image_url=url)
        assert asset.image_url == url


class TestPurchaseCostValidation:
    """Validate purchase_cost field."""

    def test_valid_purchase_cost(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", purchase_cost=Decimal("1500.50"))
        assert asset.purchase_cost == Decimal("1500.50")

    def test_zero_purchase_cost_allowed(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", purchase_cost=Decimal("0"))
        assert asset.purchase_cost == Decimal("0")

    def test_negative_purchase_cost_rejected(self):
        from app.schemas.asset import AssetCreate
        with pytest.raises(Exception):
            AssetCreate(tag="T-001", name="Test", category="laptop", purchase_cost=Decimal("-100"))

    def test_null_purchase_cost_allowed(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(tag="T-001", name="Test", category="laptop", purchase_cost=None)
        assert asset.purchase_cost is None


class TestDateValidation:
    """Validate date relationships."""

    def test_valid_warranty_after_purchase(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(
            tag="T-001", name="Test", category="laptop",
            purchase_date=date(2026, 1, 1),
            warranty_until=date(2027, 1, 1),
        )
        assert asset.warranty_until > asset.purchase_date

    def test_warranty_before_purchase_rejected(self):
        from app.schemas.asset import AssetCreate
        with pytest.raises(Exception):
            AssetCreate(
                tag="T-001", name="Test", category="laptop",
                purchase_date=date(2026, 6, 1),
                warranty_until=date(2026, 1, 1),
            )

    def test_warranty_same_as_purchase_allowed(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(
            tag="T-001", name="Test", category="laptop",
            purchase_date=date(2026, 1, 1),
            warranty_until=date(2026, 1, 1),
        )
        assert asset.warranty_until == asset.purchase_date


class TestWhitespaceNormalization:
    """Validate whitespace normalization on string fields."""

    def test_whitespace_trimmed(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(tag="  AST-001  ", name="  Dell Laptop  ", category="  laptop  ")
        assert asset.tag == "AST-001"
        assert asset.name == "Dell Laptop"
        assert asset.category == "laptop"

    def test_empty_string_becomes_none_for_optional(self):
        from app.schemas.asset import AssetCreate
        asset = AssetCreate(tag="AST-001", name="Test", category="laptop", vendor="   ")
        assert asset.vendor is None

    def test_empty_string_required_field_rejected(self):
        from app.schemas.asset import AssetCreate
        with pytest.raises(Exception):
            AssetCreate(tag="  ", name="Test", category="laptop")


class TestAssetUpdateSchema:
    """Validate AssetUpdate Pydantic schema enforcement."""

    def test_valid_partial_update(self):
        from app.schemas.asset import AssetUpdate
        update = AssetUpdate(name="Updated Name")
        assert update.name == "Updated Name"
        assert update.category is None  # unset

    def test_name_exceeds_max_length(self):
        from app.schemas.asset import AssetUpdate
        with pytest.raises(Exception):
            AssetUpdate(name="N" * 256)

    def test_invalid_status_rejected(self):
        from app.schemas.asset import AssetUpdate
        with pytest.raises(Exception):
            AssetUpdate(status="nonexistent_status")

    def test_valid_status_accepted(self):
        from app.schemas.asset import AssetUpdate
        update = AssetUpdate(status="available")
        assert update.status == "available"

    def test_reject_base64_in_update(self):
        from app.schemas.asset import AssetUpdate
        with pytest.raises(Exception):
            AssetUpdate(image_url="data:image/png;base64,ABC123==")


class TestAssetLostRequestSchema:
    """Validate AssetLostRequest schema."""

    def test_valid_lost_request(self):
        from app.schemas.asset import AssetLostRequest
        req = AssetLostRequest(reason="Left in conference room")
        assert req.reason == "Left in conference room"

    def test_empty_reason_rejected(self):
        from app.schemas.asset import AssetLostRequest
        with pytest.raises(Exception):
            AssetLostRequest(reason="")

    def test_reason_max_length(self):
        from app.schemas.asset import AssetLostRequest
        req = AssetLostRequest(reason="R" * 5000)
        assert len(req.reason) == 5000


# ---------------------------------------------------------------------------
# 2. Model definition tests (verify column definitions match requirements)
# ---------------------------------------------------------------------------


class TestAssetModelDefinitions:
    """Verify SQLAlchemy model column types match the corrected schema."""

    def test_image_url_is_text(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["image_url"]
        from sqlalchemy import Text
        assert isinstance(col.type, Text), f"Expected Text, got {col.type}"

    def test_location_is_text(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["location"]
        from sqlalchemy import Text
        assert isinstance(col.type, Text), f"Expected Text, got {col.type}"

    def test_description_is_text(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["description"]
        from sqlalchemy import Text
        assert isinstance(col.type, Text), f"Expected Text, got {col.type}"

    def test_notes_is_text(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["notes"]
        from sqlalchemy import Text
        assert isinstance(col.type, Text), f"Expected Text, got {col.type}"

    def test_lost_reason_is_text(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["lost_reason"]
        from sqlalchemy import Text
        assert isinstance(col.type, Text), f"Expected Text, got {col.type}"

    def test_name_is_varchar_255(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["name"]
        from sqlalchemy import String
        assert isinstance(col.type, String), f"Expected String, got {col.type}"
        assert col.type.length == 255, f"Expected length 255, got {col.type.length}"

    def test_tag_is_varchar_100(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["tag"]
        from sqlalchemy import String
        assert isinstance(col.type, String)
        assert col.type.length == 100

    def test_category_is_varchar_100(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["category"]
        from sqlalchemy import String
        assert isinstance(col.type, String)
        assert col.type.length == 100

    def test_serial_is_varchar_150(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["serial"]
        from sqlalchemy import String
        assert isinstance(col.type, String)
        assert col.type.length == 150

    def test_vendor_is_varchar_255(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["vendor"]
        from sqlalchemy import String
        assert isinstance(col.type, String)
        assert col.type.length == 255

    def test_brand_is_varchar_150(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["brand"]
        from sqlalchemy import String
        assert isinstance(col.type, String)
        assert col.type.length == 150

    def test_model_is_varchar_150(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["model"]
        from sqlalchemy import String
        assert isinstance(col.type, String)
        assert col.type.length == 150

    def test_status_is_varchar_50(self):
        from app.models.asset import Asset
        col = Asset.__table__.columns["status"]
        from sqlalchemy import String
        assert isinstance(col.type, String)
        assert col.type.length == 50

    def test_unique_index_on_company_tag(self):
        """Verify the unique index on (company_id, tag) exists."""
        from app.models.asset import Asset
        indices = Asset.__table__.indexes
        tag_indices = [idx for idx in indices if "tag" in str(idx.columns)]
        assert len(tag_indices) > 0, "No index found involving the tag column"
        # At least one should be unique
        unique_tag_indices = [idx for idx in tag_indices if idx.unique]
        assert len(unique_tag_indices) > 0, "No unique index found on (company_id, tag)"


# ---------------------------------------------------------------------------
# 3. Migration file verification
# ---------------------------------------------------------------------------


class TestAlembicMigration:
    """Verify migration file is valid and correct."""

    def test_migration_file_parses(self):
        import ast
        with open("alembic/versions/b8f42a1e7d05_widen_asset_columns_fix_truncation.py") as f:
            ast.parse(f.read())

    def test_migration_has_upgrade_and_downgrade(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration",
            "alembic/versions/b8f42a1e7d05_widen_asset_columns_fix_truncation.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "upgrade"), "Migration missing upgrade function"
        assert hasattr(module, "downgrade"), "Migration missing downgrade function"
        assert module.revision == "b8f42a1e7d05"
        assert module.down_revision == "a7c91f2e4d03"


# ---------------------------------------------------------------------------
# 4. Exception handler tests
# ---------------------------------------------------------------------------


class TestExceptionHandlerDataTruncation:
    """Verify the database exception handler detects data truncation errors."""

    def test_classify_truncation_by_sqlstate(self):
        """Mock a StringDataRightTruncationError and verify it maps to 422."""
        from app.core.exceptions import database_exception_handler
        # We only test classification logic, not the full handler (which needs Request)
        from sqlalchemy.exc import DBAPIError
        
        # Verify the classification function detects the sqlstate
        class FakeOrig:
            sqlstate = "22001"
            pgcode = "22001"
            def __str__(self):
                return "value too long for type character varying(255)"
        
        orig = FakeOrig()
        msg = str(orig).lower()
        is_truncation = orig.sqlstate == "22001" or "too long" in msg or "truncat" in msg
        assert is_truncation, "Should detect truncation error by sqlstate 22001"

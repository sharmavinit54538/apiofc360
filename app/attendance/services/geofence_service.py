"""Enterprise Geofence Validation Service for Face Attendance.

Performs:
- Authoritative office location resolution from database (OfficeLocation & Company tables)
- Geodesic Haversine distance calculations (in meters)
- GPS accuracy verification and spoofing / low-accuracy rejection
- Backend enforcement: never trusts client-supplied inside/outside assertions
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.office_location import OfficeLocation
from app.models.company import Company
from app.models.employee import Employee

logger = logging.getLogger(__name__)

# Earth radius in meters
EARTH_RADIUS_METERS = 6371000.0

# Maximum allowed GPS horizontal accuracy uncertainty in meters
MAX_PERMISSIBLE_GPS_ACCURACY_METERS = 500.0


def haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculates great-circle distance between two GPS coordinates using the Haversine formula."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(EARTH_RADIUS_METERS * c, 2)


class GeofenceService:
    """Handles location resolution, distance calculation, and geofence boundary checks."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_assigned_office(
        self, employee: Employee, company_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """Resolves the authorized office location for an employee from the database.
        
        Checks:
        1. Specific OfficeLocation matching employee's branch or work_location
        2. Any active OfficeLocation for the company
        3. Fallback to Company office_latitude / office_longitude columns
        """
        # 1. Match branch or work location in office_locations
        branch_name = getattr(employee, "branch", None)
        work_loc = getattr(employee, "work_location", None)

        if branch_name or work_loc:
            filters = []
            if branch_name:
                filters.append(OfficeLocation.branch.ilike(branch_name.strip()))
                filters.append(OfficeLocation.name.ilike(branch_name.strip()))
            if work_loc:
                filters.append(OfficeLocation.name.ilike(work_loc.strip()))
                filters.append(OfficeLocation.branch.ilike(work_loc.strip()))

            stmt = select(OfficeLocation).where(
                and_(
                    OfficeLocation.company_id == company_id,
                    OfficeLocation.is_active == True,
                    or_(*filters),
                )
            )
            res = await self.db.execute(stmt)
            matched = res.scalars().first()
            if matched:
                return {
                    "office_id": matched.id,
                    "office_name": matched.name,
                    "latitude": matched.latitude,
                    "longitude": matched.longitude,
                    "radius_meters": matched.radius_meters or 200.0,
                    "source": "office_locations_branch",
                }

        # 2. General active office location for company
        gen_stmt = select(OfficeLocation).where(
            and_(
                OfficeLocation.company_id == company_id,
                OfficeLocation.is_active == True,
            )
        )
        gen_res = await self.db.execute(gen_stmt)
        gen_office = gen_res.scalars().first()
        if gen_office:
            return {
                "office_id": gen_office.id,
                "office_name": gen_office.name,
                "latitude": gen_office.latitude,
                "longitude": gen_office.longitude,
                "radius_meters": gen_office.radius_meters or 200.0,
                "source": "office_locations_default",
            }

        # 3. Fallback to Company level geofence fields
        company = await self.db.get(Company, company_id)
        if (
            company
            and company.office_latitude is not None
            and company.office_longitude is not None
        ):
            return {
                "office_id": None,
                "office_name": f"{company.name} Headquarters",
                "latitude": company.office_latitude,
                "longitude": company.office_longitude,
                "radius_meters": company.geofence_radius_meters or 200.0,
                "source": "company_settings",
            }

        return None

    async def verify_geofence(
        self,
        employee: Employee,
        company_id: uuid.UUID,
        latitude: Optional[float],
        longitude: Optional[float],
        accuracy: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Independently verifies whether the employee's coordinates are inside the authorized geofence."""
        # 1. Sanity checks on coordinates
        if latitude is None or longitude is None:
            return {
                "inside_geofence": False,
                "distance": None,
                "allowed_radius": 200.0,
                "accuracy": accuracy,
                "status": "LOCATION_MISSING",
                "office_name": "Unknown",
                "message": "GPS coordinates are missing.",
            }

        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            return {
                "inside_geofence": False,
                "distance": None,
                "allowed_radius": 200.0,
                "accuracy": accuracy,
                "status": "INVALID_COORDINATES",
                "office_name": "Unknown",
                "message": "GPS coordinates are invalid.",
            }

        # 2. Accuracy sanity check (reject unreliable or suspicious GPS readings)
        if accuracy is not None:
            if accuracy < 0 or accuracy > MAX_PERMISSIBLE_GPS_ACCURACY_METERS:
                logger.warning("Suspicious GPS accuracy reported: %.2f meters", accuracy)
                return {
                    "inside_geofence": False,
                    "distance": None,
                    "allowed_radius": 200.0,
                    "accuracy": accuracy,
                    "status": "ACCURACY_LOW",
                    "office_name": "Unknown",
                    "message": f"GPS accuracy too low ({accuracy:.0f}m). Must be under {MAX_PERMISSIBLE_GPS_ACCURACY_METERS:.0f}m.",
                }

        # 3. Retrieve assigned office location from database
        office = await self.get_assigned_office(employee, company_id)
        if not office:
            # If no geofence configured in DB for company/office, allow punch by default
            return {
                "inside_geofence": True,
                "distance": 0.0,
                "allowed_radius": 200.0,
                "accuracy": accuracy,
                "status": "NO_GEOFENCE_CONFIGURED",
                "office_name": "Unrestricted",
                "message": "No geofence policy configured for this organization.",
            }

        office_lat = office["latitude"]
        office_lon = office["longitude"]
        allowed_radius = office["radius_meters"]
        office_name = office["office_name"]

        # 4. Compute Haversine distance
        distance = haversine_distance_meters(latitude, longitude, office_lat, office_lon)
        inside = distance <= allowed_radius

        status_code = "INSIDE_GEOFENCE" if inside else "OUTSIDE_GEOFENCE"
        msg = (
            f"Inside designated office zone ({office_name})."
            if inside
            else f"Outside designated office zone ({office_name}). Distance: {distance:.0f}m (Allowed: {allowed_radius:.0f}m)."
        )

        return {
            "inside_geofence": inside,
            "distance": distance,
            "allowed_radius": allowed_radius,
            "accuracy": accuracy,
            "status": status_code,
            "office_name": office_name,
            "message": msg,
        }

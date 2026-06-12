"""
Geofence math tests.

Tests haversine distance calculations against known coordinates.
"""

import pytest
import math

from app.services.geofence import haversine_meters


class TestHaversineDistance:
    """Tests for haversine_meters function with known coordinates."""

    def test_same_point_zero_distance(self):
        """Distance from a point to itself should be 0."""
        distance = haversine_meters(-1.2921, 36.8219, -1.2921, 36.8219)
        assert distance == 0.0

    def test_nairobi_to_mombasa(self):
        """
        Nairobi to Mombasa approximate distance.
        Nairobi: -1.2921, 36.8219
        Mombasa: -4.0435, 39.6682
        Known distance: ~440 km
        """
        distance = haversine_meters(-1.2921, 36.8219, -4.0435, 39.6682)
        expected = 440_000  # meters
        tolerance = 10_000  # 10km tolerance
        assert abs(distance - expected) < tolerance

    def test_one_degree_latitude(self):
        """
        One degree of latitude is approximately 111 km.
        """
        distance = haversine_meters(0.0, 0.0, 1.0, 0.0)
        expected = 111_000  # meters
        tolerance = 5_000  # 5km tolerance
        assert abs(distance - expected) < tolerance

    def test_one_degree_longitude_at_equator(self):
        """
        One degree of longitude at equator is approximately 111 km.
        """
        distance = haversine_meters(0.0, 0.0, 0.0, 1.0)
        expected = 111_000  # meters
        tolerance = 5_000  # 5km tolerance
        assert abs(distance - expected) < tolerance

    def test_one_degree_longitude_at_60_latitude(self):
        """
        One degree of longitude at 60° latitude is approximately 55.5 km
        (cos(60°) = 0.5, so half the equator distance).
        """
        distance = haversine_meters(60.0, 0.0, 60.0, 1.0)
        expected = 55_500  # meters
        tolerance = 3_000  # 3km tolerance
        assert abs(distance - expected) < tolerance

    def test_short_distance_100m(self):
        """
        Test very short distance (~100 meters).
        Approximately 0.0009 degrees at equator.
        """
        distance = haversine_meters(0.0, 0.0, 0.0, 0.0009)
        expected = 100  # meters
        tolerance = 10  # 10m tolerance
        assert abs(distance - expected) < tolerance

    def test_medium_distance_5km(self):
        """
        Test medium distance (~5 km).
        """
        distance = haversine_meters(-1.2921, 36.8219, -1.2471, 36.8219)
        expected = 5_000  # meters
        tolerance = 500  # 500m tolerance
        assert abs(distance - expected) < tolerance

    def test_crossing_antimeridian(self):
        """
        Test distance calculation crossing the antimeridian (180° longitude).
        """
        distance = haversine_meters(0.0, 179.9, 0.0, -179.9)
        expected = 22_200  # meters (about 22 km)
        tolerance = 2_000
        assert abs(distance - expected) < tolerance

    def test_pole_to_pole(self):
        """
        Distance from North Pole to South Pole should be ~20,000 km.
        """
        distance = haversine_meters(90.0, 0.0, -90.0, 0.0)
        expected = 20_000_000  # meters
        tolerance = 100_000  # 100km tolerance
        assert abs(distance - expected) < tolerance

    def test_negative_coordinates(self):
        """
        Test with negative coordinates (Southern and Western hemispheres).
        """
        distance = haversine_meters(-33.8688, -151.2093, -33.8688, -151.2093)
        assert distance == 0.0

    def test_geofence_breach_detection(self):
        """
        Test geofence breach detection scenario.
        Geofence center: -1.2921, 36.8219, radius 500m
        Location outside: -1.2971, 36.8219 (approximately 555m south)
        """
        center_lat, center_lon = -1.2921, 36.8219
        outside_lat, outside_lon = -1.2971, 36.8219

        distance = haversine_meters(center_lat, center_lon, outside_lat, outside_lon)

        assert distance > 500  # Should be outside 500m radius

    def test_geofence_inside_boundary(self):
        """
        Test location inside geofence boundary.
        Geofence center: -1.2921, 36.8219, radius 500m
        Location inside: -1.2925, 36.8219 (approximately 44m south)
        """
        center_lat, center_lon = -1.2921, 36.8219
        inside_lat, inside_lon = -1.2925, 36.8219

        distance = haversine_meters(center_lat, center_lon, inside_lat, inside_lon)

        assert distance < 500  # Should be inside 500m radius
        assert distance > 40  # Should be roughly 44m
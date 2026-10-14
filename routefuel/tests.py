from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from routefuel.models import FuelStation
from routefuel.services.geometry import build_route_segments, project_point_to_route
from routefuel.services.optimizer import CandidateStop, optimize_fuel_stops
from decimal import Decimal, ROUND_HALF_UP
from django.core.cache import cache
from routefuel.services.planner import _build_segment_estimates


def fake_station(pk, price, city="Testville"):
    return SimpleNamespace(
        id=pk, opis_truckstop_id=str(pk), name=f"Fuel {pk}", address="I-10 exit 1",
        city=city, state="TX", retail_price=price, latitude=30.0, longitude=-97.0,
    )


class GeometryTests(TestCase):
    def test_project_point_on_straight_route_has_small_offset(self):
        route = [[-97.0, 30.0], [-96.0, 30.0]]
        lengths, cumulative = build_route_segments(route)
        mile, offset = project_point_to_route([-96.5, 30.0], route, lengths, cumulative)
        self.assertAlmostEqual(offset, 0.0, places=3)
        self.assertAlmostEqual(mile, lengths[0] / 2, delta=0.2)


class OptimizerTests(TestCase):
    def test_short_route_requires_no_stop_but_estimates_cost(self):
        candidate = CandidateStop(fake_station(1, 3.0), 250, 1.0, 3.0)
        result = optimize_fuel_stops(500, [candidate], mpg=10, max_range_miles=500)
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["estimated_gallons"], 50.0)
        self.assertEqual(result["estimated_fuel_cost"], 150.0)

    def test_long_route_returns_feasible_stops(self):
        candidates = [
            CandidateStop(fake_station(1, 3.0, "One"), 300, 1, 3.0),
            CandidateStop(fake_station(2, 2.8, "Two"), 700, 1, 2.8),
        ]
        result = optimize_fuel_stops(1000, candidates, mpg=10, max_range_miles=500)
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(len(result["stops"]), 2)
        positions = [s["route_mile_marker"] for s in result["stops"]]
        self.assertLessEqual(positions[0], 500)
        self.assertTrue(all(b - a <= 500 for a, b in zip(positions, positions[1:])))
        self.assertLessEqual(1000 - positions[-1], 500)

    def test_long_route_without_station_chain_is_unreachable(self):
        candidates = [CandidateStop(fake_station(1, 3.0), 400, 1, 3.0)]
        result = optimize_fuel_stops(1200, candidates, mpg=10, max_range_miles=500)
        self.assertEqual(result["status"], "unreachable")

    def test_optimizer_precision_fuel_price_eight_decimals(self):
        """Fuel prices should be preserved up to 8 decimal places."""
        candidate = CandidateStop(fake_station(1, 3.12345678), 250, 1.0, 3.12345678)
        result = optimize_fuel_stops(600, [candidate], mpg=10, max_range_miles=500)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["stops"]), 1)
        self.assertEqual(result["stops"][0]["retail_price_per_gallon"], 3.12345678)

    def test_optimizer_precision_route_mile_three_decimals(self):
        """Route mile markers should have 3 decimal places."""
        candidate = CandidateStop(fake_station(1, 3.0), 250.1234, 1.0, 3.0)
        result = optimize_fuel_stops(600, [candidate], mpg=10, max_range_miles=500)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["stops"][0]["route_mile_marker"], 250.123)

    def test_optimizer_precision_distance_from_route_three_decimals(self):
        """Distance from route should have 3 decimal places."""
        candidate = CandidateStop(fake_station(1, 3.0), 250, 1.1234, 3.0)
        result = optimize_fuel_stops(600, [candidate], mpg=10, max_range_miles=500)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["stops"][0]["distance_from_route_miles"], 1.123)

    def test_optimizer_precision_next_leg_distance_three_decimals(self):
        """Next leg distance should have 3 decimal places."""
        c1 = CandidateStop(fake_station(1, 3.0), 200.123, 1.0, 3.0)
        c2 = CandidateStop(fake_station(2, 2.8), 450.456, 1.0, 2.8)
        result = optimize_fuel_stops(700, [c1, c2], mpg=10, max_range_miles=500)
        self.assertEqual(result["status"], "ok")
        # Verify the next leg distance has 3 decimal places
        self.assertEqual(len(str(result["stops"][0]["miles_to_next_stop_or_destination"]).split('.')[-1]), 3)

    def test_optimizer_precision_gallons_six_decimals(self):
        """Estimated gallons for next leg should have 6 decimal places."""
        candidate = CandidateStop(fake_station(1, 3.0), 250.123456, 1.0, 3.0)
        result = optimize_fuel_stops(600, [candidate], mpg=10, max_range_miles=500)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(str(result["stops"][0]["estimated_gallons_for_next_leg"]).split('.')[-1]), 6)

    def test_cost_basis_price_eight_decimals(self):
        """Cost basis price should preserve up to 8 decimal places."""
        candidate = CandidateStop(fake_station(1, 3.12345678), 250, 1.0, 3.12345678)
        result = optimize_fuel_stops(600, [candidate], mpg=10, max_range_miles=500)
        self.assertIsNotNone(result["cost_basis_price"])
        # Should preserve up to 8 decimal places
        basis_str = str(result["cost_basis_price"])
        decimal_places = len(basis_str.split('.')[-1]) if '.' in basis_str else 0
        self.assertLessEqual(decimal_places, 8)


class SegmentEstimateTests(TestCase):
    def test_no_stop_breakdown_uses_supplied_fallback_not_hardcoded_price(self):
        segments, total = _build_segment_estimates(
            stops=[],
            total_miles=100.0,
            mpg=10.0,
            cost_basis_price=None,
            status="ok",
            fallback_price=2.75,
        )
        self.assertEqual(segments[0]["price_per_gallon_usd"], 2.75)
        self.assertEqual(segments[0]["estimated_cost_usd"], 27.50)
        self.assertEqual(total, 27.50)

    def test_segment_currency_uses_decimal_half_up_rounding(self):
        segments, total = _build_segment_estimates(
            stops=[],
            total_miles=10.0,
            mpg=10.0,
            cost_basis_price=1.005,
            status="ok",
        )
        # One gallon at $1.005 is rounded to $1.01 using half-up currency rules.
        self.assertEqual(segments[0]["estimated_cost_usd"], 1.01)
        self.assertEqual(total, 1.01)


class RouteFuelAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        FuelStation.objects.create(
            source_key="test-station-key", opis_truckstop_id="123", name="Test Fuel", address="I-35",
            city="Austin", state="TX", rack_id="1", retail_price="3.00000",
            latitude=30.2672, longitude=-97.7431, coordinate_source="test",
        )

    def test_request_validation_rejects_same_locations(self):
        response = self.client.post("/api/v1/route-fuel/", {"start_location": "Austin, TX", "finish_location": "Austin, TX"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("finish_location", response.data)

    @patch("routefuel.services.planner.route_candidates", return_value=[])
    @patch("routefuel.services.planner.get_driving_route")
    @patch("routefuel.services.planner.geocode_us_location")
    def test_api_returns_geojson_and_cost_fields(self, mock_geocode, mock_route, _mock_candidates):
        mock_geocode.side_effect = [
            {"display_name": "Austin, Texas, USA", "latitude": 30.2672, "longitude": -97.7431},
            {"display_name": "San Antonio, Texas, USA", "latitude": 29.4241, "longitude": -98.4936},
        ]
        mock_route.return_value = {
            "distance_meters": 128000,
            "duration_seconds": 4500,
            "geometry": {"type": "LineString", "coordinates": [[-97.7431,30.2672],[-98.4936,29.4241]]},
        }
        response = self.client.post("/api/v1/route-fuel/", {"start_location": "Austin, TX", "finish_location": "San Antonio, TX"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("geometry", response.data["route"])
        self.assertIn("estimated_total_fuel_cost_usd", response.data["fuel_plan"])
        self.assertEqual(response.data["map"]["type"], "FeatureCollection")
        self.assertIsInstance(response.data["map"]["features"], list)
        self.assertTrue(response.data["map"]["features"])
        self.assertTrue(all(feature.get("type") == "Feature" and "geometry" in feature for feature in response.data["map"]["features"]))
        plan = response.data["fuel_plan"]
        segment_costs = [segment["estimated_cost_usd"] for segment in plan["segment_estimates"]]
        self.assertEqual(round(sum(segment_costs), 2), plan["estimated_total_fuel_cost_usd"])
        # With no corridor candidates, the estimate and segment breakdown must use
        # the same dataset-wide fallback price passed to the optimizer (3.00 here).
        self.assertEqual(plan["cost_basis_price_per_gallon_usd"], 3.0)
        self.assertEqual(plan["segment_estimates"][0]["price_per_gallon_usd"], 3.0)

    @patch("routefuel.services.planner.route_candidates")
    @patch("routefuel.services.planner.get_driving_route")
    @patch("routefuel.services.planner.geocode_us_location")
    def test_short_route_breakdown_uses_optimizer_cost_basis(self, mock_geocode, mock_route, mock_candidates):
        mock_geocode.side_effect = [
            {"display_name": "Austin, Texas, USA", "latitude": 30.2672, "longitude": -97.7431},
            {"display_name": "San Antonio, Texas, USA", "latitude": 29.4241, "longitude": -98.4936},
        ]
        mock_route.return_value = {
            "distance_meters": 100 * 1609.344,
            "duration_seconds": 100 * 60,
            "geometry": {"type": "LineString", "coordinates": [[-97.7431, 30.2672], [-98.4936, 29.4241]]},
        }
        mock_candidates.return_value = [CandidateStop(fake_station(201, 2.5, "Cheapville"), 40, 1, 2.5)]

        response = self.client.post(
            "/api/v1/route-fuel/",
            {"start_location": "Austin, TX", "finish_location": "San Antonio, TX"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        plan = response.data["fuel_plan"]
        self.assertEqual(plan["number_of_stops"], 0)
        self.assertEqual(plan["cost_basis_price_per_gallon_usd"], 2.5)
        self.assertEqual(plan["segment_estimates"][0]["price_per_gallon_usd"], 2.5)
        self.assertEqual(
            round(sum(segment["estimated_cost_usd"] for segment in plan["segment_estimates"]), 2),
            plan["estimated_total_fuel_cost_usd"],
        )

    @patch("routefuel.services.planner.route_candidates")
    @patch("routefuel.services.planner.get_driving_route")
    @patch("routefuel.services.planner.geocode_us_location")
    def test_long_route_segment_costs_reconcile_and_legs_are_feasible(self, mock_geocode, mock_route, mock_candidates):
        mock_geocode.side_effect = [
            {"display_name": "New York, NY, USA", "latitude": 40.7128, "longitude": -74.0060},
            {"display_name": "Chicago, IL, USA", "latitude": 41.8781, "longitude": -87.6298},
        ]
        mock_route.return_value = {
            "distance_meters": 790.57 * 1609.344,
            "duration_seconds": 890.8 * 60,
            "geometry": {"type": "LineString", "coordinates": [[-74.0060, 40.7128], [-87.6298, 41.8781]]},
        }
        mock_candidates.return_value = [
            CandidateStop(fake_station(101, 3.059, "Youngstown"), 382.5, 3.7, 3.059),
            CandidateStop(fake_station(102, 3.009, "Toledo"), 554.5, 5.8, 3.009),
        ]

        response = self.client.post(
            "/api/v1/route-fuel/",
            {"start_location": "New York, NY", "finish_location": "Chicago, IL"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        body = response.data
        self.assertEqual(body["fuel_plan"]["status"], "ok")
        self.assertEqual(body["fuel_plan"]["number_of_stops"], 2)
        self.assertIsInstance(body["map"]["features"], list)

        route_miles = body["route"]["distance_miles"]
        markers = [float(stop["route_mile_marker"]) for stop in body["fuel_plan"]["optimal_stops"]]
        legs = [markers[0]] + [b - a for a, b in zip(markers, markers[1:])] + [route_miles - markers[-1]]
        self.assertTrue(all(leg >= 0 for leg in legs), legs)
        self.assertTrue(all(leg <= 500.01 for leg in legs), legs)

        segments = body["fuel_plan"]["segment_estimates"]
        self.assertEqual(len(segments), 3)
        self.assertEqual(round(sum(segment["distance_miles"] for segment in segments), 2), round(route_miles, 2))
        self.assertEqual(round(sum(segment["estimated_cost_usd"] for segment in segments), 2), body["fuel_plan"]["estimated_total_fuel_cost_usd"])
        self.assertEqual(segments[1]["start_route_mile"], segments[0]["end_route_mile"])
        self.assertEqual(segments[2]["start_route_mile"], segments[1]["end_route_mile"])

    @patch("routefuel.services.planner.route_candidates", return_value=[])
    @patch("routefuel.services.planner.get_driving_route")
    @patch("routefuel.services.planner.geocode_us_location")
    def test_unreachable_route_has_no_fabricated_segment_cost(self, mock_geocode, mock_route, _mock_candidates):
        mock_geocode.side_effect = [
            {"display_name": "City A, USA", "latitude": 30.0, "longitude": -97.0},
            {"display_name": "City B, USA", "latitude": 40.0, "longitude": -80.0},
        ]
        mock_route.return_value = {
            "distance_meters": 1200 * 1609.344,
            "duration_seconds": 1200 * 60,
            "geometry": {"type": "LineString", "coordinates": [[-97.0, 30.0], [-80.0, 40.0]]},
        }
        response = self.client.post(
            "/api/v1/route-fuel/",
            {"start_location": "City A, TX", "finish_location": "City B, PA"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["fuel_plan"]["status"], "unreachable")
        self.assertIsNone(response.data["fuel_plan"]["estimated_total_fuel_cost_usd"])
        self.assertEqual(response.data["fuel_plan"]["segment_estimates"], [])

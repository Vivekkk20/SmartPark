"""
SmartPark Comprehensive Verification Test Suite
Tests authentication, permissions, slot allocation, category boundaries,
advance payment, demo duration adjustment, cash exit, simulated QR exit,
receipt generation, and security access control.
"""
import sys
import unittest
import sqlite3
import os
from datetime import datetime

# Import application
import app

class SmartParkTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        cls.test_db_path = app.Path(__file__).with_name("smartpark_test.db")
        cls.orig_db_path = app.DB_PATH
        app.DB_PATH = cls.test_db_path
        app.init_db()
        cls.client = app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app.DB_PATH = cls.orig_db_path
        if cls.test_db_path.exists():
            try:
                cls.test_db_path.unlink()
            except Exception:
                pass

    def setUp(self):
        # Reset client session to avoid cross-test cookie pollution
        self.client = app.app.test_client()
        # Reset DB state cleanly for reproducible tests
        with app.db() as con:
            con.execute("DELETE FROM sessions")
            con.execute("DELETE FROM activity_log")
            con.execute("DELETE FROM users WHERE role != 'admin'")
            con.execute("UPDATE slots SET status='available'")
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('demo_extra_minutes','0')")
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('rate_two_wheeler','10')")
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('rate_four_wheeler','20')")

    def test_01_api_status_structure(self):
        """Verify /api/status endpoint response format and fields."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["username"] = "admin"
            sess["full_name"] = "SmartPark Administrator"

        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("slots", data)
        self.assertIn("stats", data)
        self.assertIn("rates", data)
        self.assertEqual(len(data["slots"]), 12)

        # Check category breakdowns
        self.assertIn("two_wheeler", data["stats"])
        self.assertIn("four_wheeler", data["stats"])
        self.assertEqual(data["stats"]["two_wheeler"]["total"], 6)
        self.assertEqual(data["stats"]["four_wheeler"]["total"], 6)

        # Verify slot fields
        s01 = next(s for s in data["slots"] if s["slot_code"] == "S01")
        self.assertEqual(s01["category"], "two_wheeler")
        self.assertIn("status", s01)
        self.assertIn("session_id", s01)
        self.assertIn("vehicle_number", s01)

    def test_02_auth_and_role_permissions(self):
        """Verify normal user vs admin permissions on settings."""
        # Create normal user
        res = self.client.post("/register", data={
            "full_name": "Test Driver",
            "username": "driver1",
            "password": "Password123!"
        }, follow_redirects=True)
        self.assertIn(b"Account created", res.data)

        # Log in as normal user
        res = self.client.post("/login", data={
            "username": "driver1",
            "password": "Password123!"
        }, follow_redirects=True)
        self.assertIn(b"Welcome, Test Driver!", res.data)

        # Normal user accessing settings must be redirected to dashboard with error
        res = self.client.get("/settings", follow_redirects=True)
        # Log out normal user
        self.client.post("/logout", follow_redirects=True)

        # Admin login
        admin_pwd = os.environ.get("SMARTPARK_ADMIN_PASSWORD", "Pass@123")
        res = self.client.post("/login", data={
            "username": "admin",
            "password": admin_pwd
        }, follow_redirects=True)
        self.assertIn(b"Welcome, SmartPark Administrator!", res.data)

        # Admin accessing settings should succeed
        res = self.client.get("/settings")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Category Hourly Rates", res.data)

    def test_03_category_slot_allocation_and_separation(self):
        """Verify two-wheelers get 2W slots and four-wheelers get 4W slots, with strict boundaries."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["username"] = "admin"
            sess["full_name"] = "Admin"

        # 1. Register a Two-Wheeler with AUTO allocation
        res = self.client.post("/entry", data={
            "customer_name": "Rohan Patel",
            "vehicle_number": "MH15 TW 0001",
            "vehicle_category": "two_wheeler",
            "slot_code": "AUTO",
            "advance_amount": "10",
            "advance_method": "cash"
        }, follow_redirects=True)
        self.assertIn(b"Assigned slot S01", res.data)

        # Verify S01 is now occupied by two-wheeler
        with app.db() as con:
            slot_s01 = con.execute("SELECT * FROM slots WHERE slot_code='S01'").fetchone()
            self.assertEqual(slot_s01["status"], "occupied")
            self.assertEqual(slot_s01["category"], "two_wheeler")

        # 2. Register a Four-Wheeler with AUTO allocation
        res = self.client.post("/entry", data={
            "customer_name": "Anita Verma",
            "vehicle_number": "MH15 FW 0002",
            "vehicle_category": "four_wheeler",
            "slot_code": "AUTO",
            "advance_amount": "20",
            "advance_method": "qr_demo"
        }, follow_redirects=True)
        self.assertIn(b"Assigned slot S07", res.data)

        # Verify S07 is now occupied by four-wheeler
        with app.db() as con:
            slot_s07 = con.execute("SELECT * FROM slots WHERE slot_code='S07'").fetchone()
            self.assertEqual(slot_s07["status"], "occupied")
            self.assertEqual(slot_s07["category"], "four_wheeler")

        # 3. Cross-category violation test: Try booking Four-Wheeler slot S08 with Two-Wheeler
        res = self.client.post("/entry", data={
            "customer_name": "Cheater Biker",
            "vehicle_number": "MH15 TW 9999",
            "vehicle_category": "two_wheeler",
            "slot_code": "S08",
            "advance_amount": "0",
            "advance_method": "none"
        }, follow_redirects=True)
        self.assertIn(b"Category mismatch", res.data)

        # 4. Cross-category violation test: Try booking Two-Wheeler slot S02 with Four-Wheeler
        res = self.client.post("/entry", data={
            "customer_name": "Cheater Driver",
            "vehicle_number": "MH15 FW 9999",
            "vehicle_category": "four_wheeler",
            "slot_code": "S02",
            "advance_amount": "0",
            "advance_method": "none"
        }, follow_redirects=True)
        self.assertIn(b"Category mismatch", res.data)

    def test_04_parking_full_rejection(self):
        """Verify system cleanly rejects entries when a category is full without corrupting other slots."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["username"] = "admin"
            sess["full_name"] = "Admin"

        # Occupy all remaining two-wheeler slots (S01 to S06)
        with app.db() as con:
            con.execute("UPDATE slots SET status='occupied' WHERE category='two_wheeler'")

        # Attempt to register another two-wheeler
        res = self.client.post("/entry", data={
            "customer_name": "Late Rider",
            "vehicle_number": "MH15 TW 8888",
            "vehicle_category": "two_wheeler",
            "slot_code": "AUTO",
            "advance_amount": "0",
            "advance_method": "none"
        }, follow_redirects=True)
        self.assertIn(b"Parking is FULL for Two-Wheelers", res.data)

        # Four-wheeler slots should still be available
        stats = app.get_stats()
        self.assertEqual(stats["two_wheeler"]["available"], 0)
        self.assertEqual(stats["four_wheeler"]["available"], 6)

    def test_05_admin_demo_duration_and_billing(self):
        """Verify Admin demo duration adjustment properly adjusts calculation."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["username"] = "admin"
            sess["full_name"] = "Admin"

        # Check in a vehicle
        self.client.post("/entry", data={
            "customer_name": "Demo Tester",
            "vehicle_number": "MH15 AB 5555",
            "vehicle_category": "four_wheeler",
            "slot_code": "S07",
            "advance_amount": "20",
            "advance_method": "cash"
        }, follow_redirects=True)

        with app.db() as con:
            sess_row = con.execute("SELECT id FROM sessions WHERE vehicle_number='MH15 AB 5555'").fetchone()
            sess_id = sess_row["id"]

        # View exit with 0 demo offset -> 1 hour @ Rs 20 = Rs 20. Net balance = 20 - 20 = Rs 0
        res = self.client.get(f"/exit/{sess_id}")
        self.assertIn(b"Net Amount Due at Exit", res.data)

        # Admin adjusts demo extra minutes to 120 minutes (2 hours extra -> total 3 hours)
        self.client.post("/settings", data={
            "action": "demo_duration",
            "extra_minutes": "120"
        }, follow_redirects=True)

        # View exit with 120 demo extra minutes -> 3 hours @ Rs 20 = Rs 60. Net balance = 60 - 20 = Rs 40
        res = self.client.get(f"/exit/{sess_id}")
        self.assertIn(b"DEMO TIME ADJUSTMENT ACTIVE", res.data)
        self.assertIn(b"40.00", res.data) # balance due is Rs 40.00

    def test_06_cash_payment_and_receipt(self):
        """Verify cash payment settlement, slot freeing, and receipt generation."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["username"] = "admin"
            sess["full_name"] = "Admin"

        # Register vehicle
        self.client.post("/entry", data={
            "customer_name": "Kiran Rao",
            "vehicle_number": "MH15 KR 1234",
            "vehicle_category": "four_wheeler",
            "slot_code": "S08",
            "advance_amount": "0",
            "advance_method": "none"
        }, follow_redirects=True)

        with app.db() as con:
            sess_id = con.execute("SELECT id FROM sessions WHERE vehicle_number='MH15 KR 1234'").fetchone()["id"]

        # Complete exit with cash
        res = self.client.post(f"/exit/{sess_id}", data={
            "action": "complete_exit",
            "payment_method": "cash"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Receipt & Payment Summary", res.data)
        self.assertIn(b"MH15 KR 1234", res.data)
        self.assertIn(b"Cash Payment", res.data)

        # Slot S08 must be freed
        with app.db() as con:
            slot = con.execute("SELECT status FROM slots WHERE slot_code='S08'").fetchone()
            self.assertEqual(slot["status"], "available")

            # Session must be completed
            s_record = con.execute("SELECT * FROM sessions WHERE id=?", (sess_id,)).fetchone()
            self.assertEqual(s_record["status"], "completed")
            self.assertEqual(s_record["payment_status"], "paid")
            self.assertIsNotNone(s_record["receipt_number"])

    def test_07_realistic_simulated_qr_payment_flow(self):
        """Verify realistic QR demo payment: failure leaves session active; success completes session."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["username"] = "admin"
            sess["full_name"] = "Admin"

        self.client.post("/entry", data={
            "customer_name": "Priya Sharma",
            "vehicle_number": "MH15 PS 7777",
            "vehicle_category": "two_wheeler",
            "slot_code": "S02",
            "advance_amount": "0",
            "advance_method": "none"
        }, follow_redirects=True)

        with app.db() as con:
            sess_id = con.execute("SELECT id FROM sessions WHERE vehicle_number='MH15 PS 7777'").fetchone()["id"]

        # 1. Simulate Failure
        res = self.client.post(f"/exit/{sess_id}", data={
            "action": "simulate_qr_fail",
            "payment_method": "qr_demo"
        }, follow_redirects=True)
        self.assertIn(b"Simulated Online Demo Payment failed", res.data)

        # Verify session is still active and slot is still occupied
        with app.db() as con:
            s_row = con.execute("SELECT status FROM sessions WHERE id=?", (sess_id,)).fetchone()
            self.assertEqual(s_row["status"], "active")
            slot_row = con.execute("SELECT status FROM slots WHERE slot_code='S02'").fetchone()
            self.assertEqual(slot_row["status"], "occupied")

        # 2. Simulate Success
        res = self.client.post(f"/exit/{sess_id}", data={
            "action": "complete_exit",
            "payment_method": "qr_demo"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"DEMO PAYMENT", res.data)
        self.assertIn(b"Demo Online QR", res.data)

        # Verify session completed & slot released
        with app.db() as con:
            s_row = con.execute("SELECT status, payment_status, payment_method FROM sessions WHERE id=?", (sess_id,)).fetchone()
            self.assertEqual(s_row["status"], "completed")
            self.assertEqual(s_row["payment_status"], "paid")
            self.assertEqual(s_row["payment_method"], "qr_demo")
            slot_row = con.execute("SELECT status FROM slots WHERE slot_code='S02'").fetchone()
            self.assertEqual(slot_row["status"], "available")

    def test_08_duplicate_exit_prevention(self):
        """Verify that an already exited session cannot be exited again."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["username"] = "admin"
            sess["full_name"] = "Admin"

        self.client.post("/entry", data={
            "customer_name": "Duplicate Test",
            "vehicle_number": "MH15 DUP 001",
            "vehicle_category": "two_wheeler",
            "slot_code": "S03",
            "advance_amount": "0",
            "advance_method": "none"
        }, follow_redirects=True)

        with app.db() as con:
            sess_id = con.execute("SELECT id FROM sessions WHERE vehicle_number='MH15 DUP 001'").fetchone()["id"]

        # First exit succeeds
        self.client.post(f"/exit/{sess_id}", data={"action": "complete_exit", "payment_method": "cash"}, follow_redirects=True)

        # Second exit attempt must fail
        res = self.client.post(f"/exit/{sess_id}", data={"action": "complete_exit", "payment_method": "cash"}, follow_redirects=True)
        self.assertIn(b"Active parking session not found", res.data)

    def test_09_receipt_access_authorization(self):
        """Verify normal users cannot view receipts of other users, but admin can view all."""
        # Create user A and user B
        self.client.post("/register", data={"full_name": "User Alpha", "username": "user_a", "password": "Password123!"})
        self.client.post("/register", data={"full_name": "User Beta", "username": "user_b", "password": "Password123!"})

        with app.db() as con:
            id_a = con.execute("SELECT id FROM users WHERE username='user_a'").fetchone()["id"]
            id_b = con.execute("SELECT id FROM users WHERE username='user_b'").fetchone()["id"]

        # User A checks in and exits a vehicle
        with self.client.session_transaction() as sess:
            sess["user_id"] = id_a
            sess["role"] = "user"
            sess["username"] = "user_a"
            sess["full_name"] = "User Alpha"

        self.client.post("/entry", data={
            "customer_name": "Alpha Vehicle",
            "vehicle_number": "MH15 AA 1111",
            "vehicle_category": "four_wheeler",
            "slot_code": "S09",
            "advance_amount": "0",
            "advance_method": "none"
        }, follow_redirects=True)

        with app.db() as con:
            sess_a = con.execute("SELECT id FROM sessions WHERE vehicle_number='MH15 AA 1111'").fetchone()["id"]

        self.client.post(f"/exit/{sess_a}", data={"action": "complete_exit", "payment_method": "cash"}, follow_redirects=True)

        # User A can view their own receipt
        res = self.client.get(f"/receipt/{sess_a}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"MH15 AA 1111", res.data)

        # User B logs in and attempts to access User A's receipt -> denied!
        with self.client.session_transaction() as sess:
            sess["user_id"] = id_b
            sess["role"] = "user"
            sess["username"] = "user_b"
            sess["full_name"] = "User Beta"

        res = self.client.get(f"/receipt/{sess_a}", follow_redirects=True)
        self.assertIn(b"Receipt not found or access denied", res.data)

        # Admin logs in and attempts to access User A's receipt -> allowed!
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["username"] = "admin"
            sess["full_name"] = "Admin"

        res = self.client.get(f"/receipt/{sess_a}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"MH15 AA 1111", res.data)

    def test_10_admin_password_env_sync(self):
        """Verify Admin password dynamically syncs from SMARTPARK_ADMIN_PASSWORD, hashes properly, and rejects old passwords."""
        from werkzeug.security import generate_password_hash

        # Step A: Simulate an existing database that has the legacy hash for Admin@12345
        with app.db() as con:
            con.execute("UPDATE users SET password_hash=? WHERE username='admin'", 
                        (generate_password_hash("Admin@12345"),))
            stored_hash = con.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()["password_hash"]

        # Verify old password would match old hash
        self.assertTrue(app.check_password_hash(stored_hash, "Admin@12345"))

        # Step B: Set SMARTPARK_ADMIN_PASSWORD to Pass@123 and run init_db()
        os.environ["SMARTPARK_ADMIN_PASSWORD"] = "Pass@123"
        app.init_db()

        with app.db() as con:
            new_hash = con.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()["password_hash"]

        # Verify stored value is a valid secure hash, not plaintext
        self.assertNotEqual(new_hash, "Pass@123")
        self.assertTrue(new_hash.startswith("scrypt:") or new_hash.startswith("pbkdf2:"))
        self.assertTrue(app.check_password_hash(new_hash, "Pass@123"))
        self.assertFalse(app.check_password_hash(new_hash, "Admin@12345"))

        # Step C: Verify login with new password succeeds and old password fails
        res_fail = self.client.post("/login", data={"username": "admin", "password": "Admin@12345"}, follow_redirects=True)
        self.assertIn(b"Invalid username or password.", res_fail.data)

        res_ok = self.client.post("/login", data={"username": "admin", "password": "Pass@123"}, follow_redirects=True)
        self.assertIn(b"Welcome, SmartPark Administrator!", res_ok.data)


if __name__ == "__main__":
    unittest.main()

# SmartPark — 3D Smart Parking Management System

A full-stack smart parking management web application built with Python (Flask), SQLite, Vanilla CSS/JS, and an interactive 3D WebGL parking lot powered by Three.js.

Designed for college engineering demonstrations, campus facilities, and smart parking automation simulations.

---

## 🌟 Key Features

1. **Interactive 3D Parking Lot (`Three.js`)**:
   - Visual 3D environment with road lanes, zone demarcations, curbs, and entry/exit markers.
   - **Low-poly 3D models**:
     - 🚗 Sedans / SUVs for occupied Four-Wheeler slots.
     - 🏍 Motorcycles / Scooters for occupied Two-Wheeler slots.
   - Individual floating 3D slot labels (`S01`–`S12`).
   - Orbit controls, mouse/touch interaction, smooth zoom limits, and reset camera.
   - Quick zone focus: `🏍 2W Zone`, `🚗 4W Zone`, and `◫ Top View`.
   - **Responsive 2D Fallback**: Instant switch to high-contrast 2D slot grid when desired or if WebGL is unavailable.

2. **Strict Category Separation (Two-Wheeler & Four-Wheeler)**:
   - **Zone A (Two-Wheeler)**: Dedicated slots `S01`–`S06` (motorcycles, scooters) with independent hourly rate (default ₹10/hr).
   - **Zone B (Four-Wheeler)**: Dedicated slots `S07`–`S12` (cars, SUVs) with independent hourly rate (default ₹20/hr).
   - Strict category enforcement: Motorcycles cannot book car slots; cars cannot book motorcycle slots.
   - Clean "Parking Full" feedback when a category has zero available slots.
   - Atomic slot assignment preventing race-condition double bookings.

3. **Advance Payment & Check-In**:
   - Capture customer name, vehicle registration number, and category.
   - Optional advance payment collection at entry (Cash or Demo QR).
   - Advance payments are recorded, audited, and automatically credited towards the final exit bill.

4. **Realistic Simulated QR Payment Terminal**:
   - Interactive demo checkout modal for college presentations.
   - Clear banner: `DEMO PAYMENT — NO REAL MONEY TRANSFERRED`.
   - Scalable QR graphic and transaction reference.
   - "Simulate Successful Payment" and "Simulate Failed Payment" buttons with in-flight processing animations.
   - Validated state transitions enforced on the backend (failsafe against duplicate exits).

5. **Cash Payment & Refund Handling**:
   - Operator cash confirmation workflow.
   - Automated net balance calculation (Gross Charge − Advance Paid).
   - Explicit refund calculation and display if advance payment exceeds total parking fee.

6. **Official Printable Receipts & History**:
   - Complete billing receipts with unique receipt numbers (`RCP-XXXXXXXX`).
   - Includes actual duration, simulated demo time adjustment indicator, hourly rates, advance credits, net collection, and demo payment warnings.
   - Browser print action (`window.print()`) formatted via clean `@media print` CSS.
   - Role-based privacy: Normal users only see their own history and receipts; administrators see all records.

7. **Admin DEMO TIME ADJUSTMENT**:
   - Dedicated administrator control to add simulated minutes (e.g. `+120 mins`) to demonstrate multi-hour billing without waiting.
   - Clearly flagged as simulated demo time on receipts and summaries.

---

## 🛠 Tech Stack

- **Backend**: Python 3.10+, Flask 3.0+
- **Database**: SQLite 3 (transaction-safe, auto-migrating)
- **Frontend**: HTML5, Vanilla CSS (Dark navy `#0d1117` palette), JavaScript (ES6+)
- **3D Graphics**: Three.js (r128) WebGL canvas with soft shadows and raycasting
- **Testing**: Python `unittest` suite (9 automated end-to-end integration tests)

---

## 🚀 Running Locally

### 1. Install Dependencies

Open Command Prompt or Terminal in the `SmartPark_Management_System` folder:

```bash
pip install -r requirements.txt
```

### 2. Run the Application

```bash
python app.py
```

Open your browser at:
```
http://127.0.0.1:5000
```

### 3. Run Automated Tests

To run the verification test suite covering authentication, permissions, slot collisions, advance billing, and QR payment:

```bash
python test_suite.py
```

---

## 🔐 Demo Credentials

- **Admin Account**:
  - Username: `admin`
  - Password: `Pass@123` (or configured via `SMARTPARK_ADMIN_PASSWORD`)
  - Full access to all active vehicles, all receipts, rate settings, demo time adjustments, and slot reassignments.

- **Normal User Account**:
  - Register freely via the [Create Account](http://127.0.0.1:5000/register) link.
  - Normal accounts can only view and exit their own vehicles and receipts.

---

## 🌐 Production Deployment (e.g. Render)

### Production Startup Command
In your Render web service configuration:

```bash
gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT
```

### Environment Variables
- `SMARTPARK_SECRET_KEY`: Set to a cryptographically secure random string (e.g. `openssl rand -hex 32`).
- `SMARTPARK_ADMIN_PASSWORD`: Secure password for the `admin` account (defaults to `Pass@123` if omitted).
- `PYTHON_VERSION`: `3.10` or higher.

### Database Persistence on Render
- **Notice on SQLite**: Free-tier cloud hosts (such as Render Free Tier) use ephemeral filesystems. When a dyno spins down or restarts, SQLite database files are reset unless attached to a Persistent Disk.
- **Recommendations for Persistent Hosting**:
  1. Attach a **Render Persistent Disk** mounted at `/data` and set `DB_PATH = Path('/data/smartpark.db')`.
  2. Or connect to a managed PostgreSQL database (e.g. Render PostgreSQL or Supabase) using SQLAlchemy if multi-instance autoscaling is needed.

---

## 📁 Project Structure

```
SmartPark_Management_System/
├── app.py               # Main Flask application, routes, and DB models
├── requirements.txt     # Python dependencies (Flask, Gunicorn)
├── README.md            # Comprehensive project documentation
├── test_suite.py        # Automated test suite (9 integration tests)
├── smartpark.db         # SQLite database file (auto-seeded on first run)
├── static/
│   ├── app.js           # Shared utilities and elapsed timers
│   ├── parking3d.js     # Three.js 3D parking lot renderer & interaction
│   └── style.css        # Dark navy design system, 3D overlays, print styles
└── templates/
    ├── base.html        # Shared navigation, sidebar, and layout shell
    ├── dashboard.html   # Main operations dashboard, 6 stat cards, 3D viewer
    ├── entry.html       # Vehicle check-in with category & advance payment
    ├── exit.html        # Exit billing, cash settlement & demo QR terminal
    ├── history.html     # Parking history, search filter, and receipt links
    ├── login.html       # Authentication screen
    ├── receipt.html     # Official printable receipt & payment summary
    ├── register.html    # User registration screen
    └── settings.html    # Admin rates, DEMO TIME ADJUSTMENT, slot mapping
```

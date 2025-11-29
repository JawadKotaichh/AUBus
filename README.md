# AUBus - Desktop Ride-Sharing App

This repository contains the full AUBus project:

- A PyQt6 desktop client in `GUI/`
- A TCP backend server in `server/`
- An SQLite database (`AUBus.db`) and related helpers in `db/`

Use this guide to set up a local environment, install dependencies, and run the app.

---

## Demo

Here are some screenshots of the AUBus application:

### Authentication

#### Sign Up Page
![Sign Up](demo%20images/sign%20up.png)
*New users can create an account by providing their personal information, contact details, and setting up their credentials.*

#### Log In Page
![Log In](demo%20images/log%20in.png)
*Existing users can securely log in to access their account and start using the AUBus ride-sharing service.*

### Main Features

#### Dashboard Page
![Dashboard](demo%20images/dashboard.png)
*The main dashboard provides an overview of the user's ride-sharing activity, including quick access to key features and recent updates.*

#### Request Ride Page
![Request Ride](demo%20images/Request%20ride.png)
*Users can request a ride by specifying their pickup and destination locations, and the system will match them with available drivers.*

#### Drivers Page
![Drivers](demo%20images/Drivers.png)
*Browse and view available drivers, their ratings, vehicle information, and current availability status.*

#### Trips Page
![Trips](demo%20images/Trips.png)
*View your trip history, including past and upcoming rides, with details about routes, drivers, and trip status.*

#### Chats Page
![Chats](demo%20images/Chats.png)
*Communicate with drivers and passengers through the built-in chat feature for real-time coordination during rides.*

#### Update Profile Page
![Update Profile](demo%20images/update%20profile.png)
*Manage your account settings, update personal information, preferences, and profile details.*

---

## 1. Prerequisites

- Python **3.10+**
- Git
- (Optional) A virtual environment tool: `venv` (built into Python)

Check your Python version:

```powershell
python --version
```

---

## 2. Clone the repository

```bash
git clone https://github.com/<your-org>/AUBus.git
cd AUBus
```

If you already have the project, just `cd` into its folder.

---

## 3. Create and activate a virtual environment

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux (bash/zsh):**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` at the start of your terminal prompt when the environment is active.


---

## 4. Install dependencies

With the virtual environment activated:

```bash
pip install -r requirements.txt
```

---

## 5. Run the backend server

From the repository root:

```bash
python -m server.server
```

By default the server listens on `127.0.0.1:5000`. Keep this terminal open while you use the app.

Alternatively:

```bash
python server/server.py
```

---

## 6. Run the GUI client

From the repository root you can launch the GUI in two ways.

**Option A - Use the `GUI/main.py` entry point (recommended):**

```bash
python GUI/main.py
```

You can customize the server connection (host/port):

```bash
python GUI/main.py --server-host 127.0.0.1 --server-port 5000
```

The only available theme is `light` (default).

**Option B - Run `gui.py` directly:**

```bash
python GUI/gui.py
```

---

## 7. Project structure (high level)

- `GUI/` - PyQt6 desktop client (pages, components, services)
- `server/` - TCP server and request handlers
- `db/` - Database utilities and initial DB creation
- `tests/` - Automated tests
- `requirements.txt` - Python dependencies
- `AUBus.db` - SQLite database file used by the server

For more detailed information about the GUI client itself, see `GUI/README.md`.


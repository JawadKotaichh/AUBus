# AUBus PyQt Client

This directory contains a PyQt implementation of the AUBus client UI that follows the
mockups included in `Untitled-2025-11-11-1815.png` and the project requirements from
`AUBus.pdf`.

## Features

- Dedicated authentication page with log-in and registration workflows.
- Dashboard view that surfaces weather data and the latest ride activity.
- Ride request form with a waiting/status panel to cancel or monitor requests.
- Drivers search page with pagination-ready filters (area, rating, ordering).
- Chats view listing past chats and allowing new messages inline.
- Profile editor with schedule button placeholder, theme, and notification settings.
- Trips page to inspect all historical trips with driver/rating/date filters.
- `ServerAPI` abstraction for the JSON-over-socket protocol plus an in-memory
  `MockServerAPI` wired into the GUI for local demos. Swap it with a real backend by
  passing a concrete `ServerAPI` instance to `MainWindow`.

## Running the app

```bash
pip install -r requirements.txt
python main.py
```

The mock backend uses the credentials `guest/guest`. Once real server endpoints are
available, implement them in `ServerAPI` or point the GUI to a subclass that speaks the
final protocol. All UI refresh hooks are already in place and call the API helpers that
should interface with your database-backed server.

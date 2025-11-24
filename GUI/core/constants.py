from __future__ import annotations

from typing import Dict, List, Tuple

# Allowed Beirut regions for filtering and location suggestions.
ALLOWED_ZONES: List[str] = [
    "Hamra",
    "Achrafieh",
    "Bchara el Khoury",
    "Forn El Chebak",
    "Ghobeiry",
    "Hadath",
    "Hazmieh",
    "Dawra",
    "Khalde",
    "Mansourieh",
    "Sin El Fil",
    "Tariq El Jdideh",
    "Verdun",
    "Ain El Remmaneh",
    "Jnah",
    "Chiah",
    "Baabda",
    "Beirut",
    "Jdeideh",
    "Bourj Hammoud",
    "Antelias",
    "Naccache",
    "Zalka",
    "Adma",
    "Dbaye",
    "Keserwan",
    "Jnah",
    "Airport area",
    "Saida",
    "Jounieh",
    "Baabda",
    "Beirut",
]

# User profile defaults
DEFAULT_GENDER = "female"
GENDER_CHOICES: List[Tuple[str, str]] = [
    ("female", "Female"),
    ("male", "Male"),
]
GENDER_LABELS: Dict[str, str] = {value: label for value, label in GENDER_CHOICES}

# Styling snippets
REQUEST_BUTTON_STYLE = """
QPushButton#requestRideAction {
    padding: 10px 18px;
    border-radius: 8px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                      stop:0 #4C51BF, stop:1 #667EEA);
    color: #ffffff;
    font-weight: 600;
    border: 0px;
}
QPushButton#requestRideAction:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                      stop:0 #5A67D8, stop:1 #5465d9);
}
QPushButton#requestRideAction:pressed {
    background-color: #3B4ABA;
}
"""

DRIVER_ROW_BUTTON_STYLE = """
QPushButton#driverRequestBtn {
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid #4C51BF;
    background-color: #EEF1FF;
    color: #1D2671;
}
QPushButton#driverRequestBtn:hover {
    background-color: #E2E7FF;
}
QPushButton#driverRequestBtn:pressed {
    background-color: #D6DCFF;
}
"""

# Email domains allowed for AUB accounts
ALLOWED_AUB_EMAIL_SUFFIXES = ("@mail.aub.edu", "@aub.edu.lb")

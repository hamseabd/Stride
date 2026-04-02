"""Infer IANA timezone from US phone number area code.

Best-guess mapping — not authoritative. Used during onboarding so the agent
can confirm rather than ask open-ended.
"""

# Area code → IANA timezone.  Covers ~90 % of US numbers.
# Unmapped codes fall back to America/New_York.
_AREA_CODE_TZ: dict[str, str] = {
    # Pacific
    "206": "America/Los_Angeles", "209": "America/Los_Angeles",
    "213": "America/Los_Angeles", "253": "America/Los_Angeles",
    "310": "America/Los_Angeles",
    "323": "America/Los_Angeles", "360": "America/Los_Angeles",
    "408": "America/Los_Angeles", "415": "America/Los_Angeles",
    "424": "America/Los_Angeles", "425": "America/Los_Angeles",
    "503": "America/Los_Angeles", "509": "America/Los_Angeles",
    "510": "America/Los_Angeles", "530": "America/Los_Angeles",
    "541": "America/Los_Angeles", "559": "America/Los_Angeles",
    "562": "America/Los_Angeles", "619": "America/Los_Angeles",
    "626": "America/Los_Angeles", "650": "America/Los_Angeles",
    "657": "America/Los_Angeles", "661": "America/Los_Angeles",
    "669": "America/Los_Angeles", "702": "America/Los_Angeles",
    "707": "America/Los_Angeles", "714": "America/Los_Angeles",
    "725": "America/Los_Angeles", "747": "America/Los_Angeles",
    "760": "America/Los_Angeles", "775": "America/Los_Angeles",
    "805": "America/Los_Angeles", "818": "America/Los_Angeles",
    "831": "America/Los_Angeles", "858": "America/Los_Angeles",
    "909": "America/Los_Angeles", "916": "America/Los_Angeles",
    "925": "America/Los_Angeles", "949": "America/Los_Angeles",
    "951": "America/Los_Angeles", "971": "America/Los_Angeles",

    # Arizona (no DST)
    "480": "America/Phoenix", "520": "America/Phoenix",
    "602": "America/Phoenix", "623": "America/Phoenix",
    "928": "America/Phoenix",

    # Mountain
    "303": "America/Denver", "307": "America/Denver",
    "385": "America/Denver", "406": "America/Denver",
    "435": "America/Denver", "505": "America/Denver",
    "575": "America/Denver", "719": "America/Denver",
    "720": "America/Denver", "801": "America/Denver",
    "970": "America/Denver",

    # Central
    "205": "America/Chicago", "210": "America/Chicago",
    "214": "America/Chicago", "217": "America/Chicago",
    "224": "America/Chicago", "225": "America/Chicago",
    "254": "America/Chicago", "262": "America/Chicago",
    "281": "America/Chicago", "309": "America/Chicago",
    "312": "America/Chicago", "314": "America/Chicago",
    "316": "America/Chicago", "318": "America/Chicago",
    "319": "America/Chicago", "320": "America/Chicago",
    "331": "America/Chicago", "346": "America/Chicago",
    "402": "America/Chicago", "405": "America/Chicago",
    "409": "America/Chicago", "414": "America/Chicago",
    "417": "America/Chicago", "430": "America/Chicago",
    "469": "America/Chicago", "479": "America/Chicago",
    "501": "America/Chicago", "504": "America/Chicago",
    "507": "America/Chicago", "512": "America/Chicago",
    "515": "America/Chicago", "563": "America/Chicago",
    "573": "America/Chicago", "601": "America/Chicago",
    "608": "America/Chicago", "612": "America/Chicago",
    "615": "America/Chicago", "630": "America/Chicago",
    "636": "America/Chicago", "651": "America/Chicago",
    "660": "America/Chicago", "662": "America/Chicago",
    "682": "America/Chicago", "708": "America/Chicago",
    "713": "America/Chicago", "715": "America/Chicago",
    "726": "America/Chicago", "731": "America/Chicago",
    "737": "America/Chicago", "763": "America/Chicago",
    "769": "America/Chicago", "773": "America/Chicago",
    "779": "America/Chicago", "806": "America/Chicago",
    "815": "America/Chicago", "816": "America/Chicago",
    "817": "America/Chicago", "830": "America/Chicago",
    "832": "America/Chicago", "847": "America/Chicago",
    "850": "America/Chicago", "856": "America/Chicago",
    "870": "America/Chicago", "901": "America/Chicago",
    "903": "America/Chicago", "913": "America/Chicago",
    "918": "America/Chicago", "920": "America/Chicago",
    "936": "America/Chicago", "940": "America/Chicago",
    "952": "America/Chicago", "956": "America/Chicago",
    "972": "America/Chicago", "979": "America/Chicago",

    # Eastern
    "201": "America/New_York", "202": "America/New_York",
    "203": "America/New_York", "207": "America/New_York",
    "212": "America/New_York", "215": "America/New_York",
    "216": "America/New_York", "219": "America/New_York",
    "229": "America/New_York", "231": "America/New_York",
    "234": "America/New_York", "239": "America/New_York",
    "240": "America/New_York", "248": "America/New_York",
    "252": "America/New_York", "267": "America/New_York",
    "269": "America/New_York", "272": "America/New_York",
    "276": "America/New_York", "301": "America/New_York",
    "302": "America/New_York", "304": "America/New_York",
    "305": "America/New_York", "313": "America/New_York",
    "315": "America/New_York", "317": "America/New_York",
    "321": "America/New_York", "330": "America/New_York",
    "332": "America/New_York", "336": "America/New_York",
    "339": "America/New_York", "347": "America/New_York",
    "351": "America/New_York", "352": "America/New_York",
    "386": "America/New_York", "401": "America/New_York",
    "404": "America/New_York", "407": "America/New_York",
    "410": "America/New_York", "412": "America/New_York",
    "413": "America/New_York", "434": "America/New_York",
    "440": "America/New_York", "443": "America/New_York",
    "470": "America/New_York", "475": "America/New_York",
    "478": "America/New_York", "484": "America/New_York",
    "502": "America/New_York", "508": "America/New_York",
    "513": "America/New_York", "516": "America/New_York",
    "517": "America/New_York", "518": "America/New_York",
    "540": "America/New_York", "551": "America/New_York",
    "567": "America/New_York", "570": "America/New_York",
    "571": "America/New_York", "574": "America/New_York",
    "585": "America/New_York", "586": "America/New_York",
    "603": "America/New_York", "607": "America/New_York",
    "609": "America/New_York", "610": "America/New_York",
    "614": "America/New_York", "616": "America/New_York",
    "617": "America/New_York", "631": "America/New_York",
    "646": "America/New_York", "667": "America/New_York",
    "678": "America/New_York", "680": "America/New_York",
    "681": "America/New_York", "689": "America/New_York",
    "703": "America/New_York", "704": "America/New_York",
    "706": "America/New_York", "716": "America/New_York",
    "717": "America/New_York", "718": "America/New_York",
    "732": "America/New_York", "734": "America/New_York",
    "740": "America/New_York", "743": "America/New_York",
    "754": "America/New_York", "757": "America/New_York",
    "762": "America/New_York", "770": "America/New_York",
    "772": "America/New_York", "774": "America/New_York",
    "781": "America/New_York", "786": "America/New_York",
    "802": "America/New_York", "803": "America/New_York",
    "804": "America/New_York", "810": "America/New_York",
    "813": "America/New_York", "814": "America/New_York",
    "828": "America/New_York", "843": "America/New_York",
    "845": "America/New_York", "848": "America/New_York",
    "857": "America/New_York", "860": "America/New_York",
    "862": "America/New_York", "863": "America/New_York",
    "864": "America/New_York", "878": "America/New_York",
    "904": "America/New_York", "908": "America/New_York",
    "910": "America/New_York", "912": "America/New_York",
    "914": "America/New_York", "917": "America/New_York",
    "919": "America/New_York", "929": "America/New_York",
    "931": "America/New_York", "937": "America/New_York",
    "941": "America/New_York", "947": "America/New_York",
    "954": "America/New_York", "973": "America/New_York",
    "978": "America/New_York", "980": "America/New_York",
    "984": "America/New_York",

    # Alaska
    "907": "America/Anchorage",

    # Hawaii
    "808": "Pacific/Honolulu",
}

# IANA timezone → user-friendly display name (used in agent context)
TZ_DISPLAY_NAMES: dict[str, str] = {
    "America/New_York": "Eastern time",
    "America/Chicago": "Central time",
    "America/Denver": "Mountain time",
    "America/Los_Angeles": "Pacific time",
    "America/Phoenix": "Arizona time",
    "America/Anchorage": "Alaska time",
    "Pacific/Honolulu": "Hawaii time",
}

_DEFAULT_TZ = "America/New_York"


def infer_timezone_from_phone(phone: str) -> str:
    """Infer IANA timezone from US phone number area code. Best guess, not authoritative.

    Args:
        phone: E.164 phone number (e.g. "+14045551234").

    Returns:
        IANA timezone string (e.g. "America/New_York").
        Falls back to America/New_York for unrecognized or non-US numbers.
    """
    # Strip leading '+' and country code '1' → area code is next 3 digits
    digits = phone.lstrip("+")
    if len(digits) >= 4 and digits[0] == "1":
        area_code = digits[1:4]
    elif len(digits) >= 3:
        area_code = digits[:3]
    else:
        return _DEFAULT_TZ

    return _AREA_CODE_TZ.get(area_code, _DEFAULT_TZ)

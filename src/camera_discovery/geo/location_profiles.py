"""Shared location profile data for camera-discovery.

This module is intentionally neutral. It stores country names, aliases, ISO
alpha-2 codes, official/public site scopes, and localized safe public-camera
terms that can be shared by discovery and enrichment layers. It does not
perform target resolution, geocoding, validation, trust decisions, scope checks,
or artifact writing.

Safety boundary: profiles may only describe curated public/official source
search hints. They must not emit exposed device-interface dorks, admin/login
pages, default credential terms, private IP ranges, or internet-asset indexes.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LocationSearchProfile:
    """Search hints derived from a location string or user query."""

    country_name: str | None = None
    country_code: str | None = None
    official_site_scopes: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    localized_terms: dict[str, tuple[str, ...]] | None = None


_BLOCKED_SITE_EXCLUSIONS: tuple[str, ...] = (
    "-site:insecam.org",
    "-site:shodan.io",
    "-site:censys.io",
    "-site:zoomeye.org",
    "-site:fofa.info",
)

# ISO 3166-1 alpha-2 codes for broad location-context extraction. Explicit
# profiles below add language/camera-search details where we have a safe curated
# vocabulary. This table is used only for generic ccTLD expansion and location
# context, not for trust or scope decisions.
_COUNTRY_CODES: dict[str, str] = {
    "afghanistan": "af", "albania": "al", "algeria": "dz", "الجزائر": "dz",
    "andorra": "ad", "angola": "ao", "argentina": "ar", "armenia": "am",
    "australia": "au", "austria": "at", "azerbaijan": "az", "bahamas": "bs",
    "bahrain": "bh", "البحرين": "bh", "bangladesh": "bd", "barbados": "bb",
    "belarus": "by", "belgium": "be", "belize": "bz", "benin": "bj",
    "bhutan": "bt", "bolivia": "bo", "bosnia and herzegovina": "ba",
    "botswana": "bw", "brazil": "br", "brasil": "br", "brunei": "bn",
    "bulgaria": "bg", "burkina faso": "bf", "burundi": "bi", "cambodia": "kh",
    "cameroon": "cm", "canada": "ca", "chile": "cl", "china": "cn", "中国": "cn",
    "colombia": "co", "comoros": "km", "جزر القمر": "km", "costa rica": "cr",
    "croatia": "hr", "cuba": "cu", "cyprus": "cy", "czech republic": "cz",
    "czechia": "cz", "denmark": "dk", "djibouti": "dj", "جيبوتي": "dj",
    "dominican republic": "do", "ecuador": "ec", "egypt": "eg", "مصر": "eg",
    "el salvador": "sv", "estonia": "ee", "finland": "fi", "france": "fr",
    "germany": "de", "deutschland": "de", "ghana": "gh", "greece": "gr",
    "guatemala": "gt", "honduras": "hn", "hong kong": "hk", "hong kong sar": "hk",
    "香港": "hk", "hungary": "hu", "iceland": "is", "india": "in", "indonesia": "id",
    "ireland": "ie", "iraq": "iq", "العراق": "iq", "israel": "il", "italy": "it",
    "japan": "jp", "日本": "jp", "jordan": "jo", "الأردن": "jo", "kazakhstan": "kz",
    "kenya": "ke", "kuwait": "kw", "الكويت": "kw", "latvia": "lv", "lebanon": "lb",
    "لبنان": "lb", "libya": "ly", "ليبيا": "ly", "lithuania": "lt", "luxembourg": "lu",
    "malaysia": "my", "mexico": "mx", "méxico": "mx", "moldova": "md", "morocco": "ma",
    "المغرب": "ma", "mauritania": "mr", "موريتانيا": "mr", "netherlands": "nl",
    "new zealand": "nz", "nicaragua": "ni", "nigeria": "ng", "norway": "no",
    "oman": "om", "عمان": "om", "pakistan": "pk", "palestine": "ps", "فلسطين": "ps",
    "panama": "pa", "peru": "pe", "philippines": "ph", "poland": "pl", "portugal": "pt",
    "qatar": "qa", "قطر": "qa", "romania": "ro", "russia": "ru", "russian federation": "ru",
    "россия": "ru", "saudi arabia": "sa", "السعودية": "sa", "serbia": "rs", "singapore": "sg",
    "slovakia": "sk", "slovenia": "si", "somalia": "so", "الصومال": "so",
    "south africa": "za", "south korea": "kr", "korea": "kr", "대한민국": "kr", "sri lanka": "lk",
    "sudan": "sd", "السودان": "sd", "spain": "es", "españa": "es", "sweden": "se",
    "switzerland": "ch", "syria": "sy", "سوريا": "sy", "taiwan": "tw", "臺灣": "tw", "台湾": "tw",
    "thailand": "th", "tunisia": "tn", "تونس": "tn", "turkey": "tr", "türkiye": "tr",
    "ukraine": "ua", "united arab emirates": "ae", "uae": "ae", "الإمارات": "ae",
    "united kingdom": "gb", "great britain": "gb", "england": "gb", "scotland": "gb", "wales": "gb",
    "united states": "us", "united states of america": "us", "usa": "us", "vietnam": "vn", "viet nam": "vn",
    "yemen": "ye", "اليمن": "ye",
}

# Short aliases that are safe enough to treat as country context in search
# planning. Ambiguous tokens such as "ca" (Canada/California), "in" (India/
# English preposition), "id", "no", "or", "ar", and "co" are intentionally not
# used here.
_COUNTRY_ALIASES: dict[str, str] = {
    "ae": "United Arab Emirates", "bd": "Bangladesh", "bh": "Bahrain", "br": "Brazil",
    "cl": "Chile", "cn": "China", "de": "Germany", "dz": "Algeria", "eg": "Egypt",
    "es": "Spain", "fr": "France", "gb": "United Kingdom", "hk": "Hong Kong", "jp": "Japan",
    "kr": "South Korea", "kw": "Kuwait", "kz": "Kazakhstan", "lk": "Sri Lanka", "ma": "Morocco",
    "mx": "Mexico", "mex": "Mexico", "méxico": "Mexico", "mexico": "Mexico", "my": "Malaysia",
    "np": "Nepal", "nz": "New Zealand", "ph": "Philippines", "pk": "Pakistan", "qa": "Qatar",
    "ru": "Russia", "sa": "Saudi Arabia", "sg": "Singapore", "th": "Thailand", "tw": "Taiwan",
    "ua": "Ukraine", "ukraine": "Ukraine", "україна": "Ukraine", "украина": "Ukraine",
    "uk": "United Kingdom", "usa": "United States", "us": "United States", "united states": "United States",
    "united states of america": "United States", "vn": "Vietnam", "za": "South Africa",
}


def _profile(
    country_name: str,
    country_code: str,
    official_site_scopes: tuple[str, ...],
    languages: tuple[str, ...],
    aliases: tuple[str, ...],
    localized_terms: dict[str, tuple[str, ...]],
) -> LocationSearchProfile:
    return LocationSearchProfile(
        country_name=country_name,
        country_code=country_code,
        official_site_scopes=official_site_scopes,
        languages=languages,
        aliases=aliases,
        localized_terms=localized_terms,
    )


_ENGLISH_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("public cameras", "live cameras", "live webcams", "camera map", "webcam"),
    "traffic": ("traffic cameras", "road cameras", "highway cameras", "traffic camera map", "road conditions cameras"),
    "weather": ("weather cameras", "weather webcam", "live weather camera"),
    "airport": ("airport cameras", "airport weather camera", "runway camera"),
    "beach": ("beach cameras", "surf camera", "beach webcam"),
    "harbor": ("harbor cameras", "port cameras", "marina cameras", "waterfront camera"),
    "city": ("city webcam", "downtown camera", "municipal camera"),
}

_SPANISH_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("cámaras en vivo", "camaras en vivo", "cámaras públicas", "webcams en vivo", "mapa de cámaras"),
    "traffic": ("cámaras de tráfico", "camaras de trafico", "cámaras viales", "monitoreo vial", "cámaras de tránsito", "autopistas cámaras"),
    "weather": ("cámaras meteorológicas", "cámara del clima", "camara del clima"),
    "airport": ("cámara de aeropuerto", "camara de aeropuerto", "cámara de pista"),
    "beach": ("cámara de playa", "camara de playa", "cámara de surf", "playa webcam"),
    "harbor": ("cámara de puerto", "camara de puerto", "cámara de marina"),
    "city": ("cámara de ciudad", "camara de ciudad", "cámara municipal"),
}

_PORTUGUESE_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("câmeras ao vivo", "cameras ao vivo", "webcams ao vivo", "câmeras públicas"),
    "traffic": ("câmeras de trânsito", "cameras de transito", "câmeras rodoviárias", "monitoramento viário"),
    "weather": ("câmeras meteorológicas", "câmera do tempo"),
    "airport": ("câmera de aeroporto", "webcam aeroporto"),
    "beach": ("câmera de praia", "câmera de surf"),
    "harbor": ("câmera do porto", "câmera de marina"),
    "city": ("câmera da cidade", "webcam cidade"),
}

_FRENCH_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("caméras en direct", "webcam en direct", "webcams", "caméras publiques"),
    "traffic": ("caméras de circulation", "caméras routières", "caméras trafic"),
    "weather": ("caméras météo", "webcam météo"),
    "airport": ("caméra aéroport", "webcam aéroport"),
    "beach": ("webcam plage", "caméra plage"),
    "harbor": ("webcam port", "caméra port"),
    "city": ("webcam ville", "caméra municipale"),
}

_GERMAN_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("Webcam", "Livecam", "öffentliche Kameras", "Kamera live"),
    "traffic": ("Verkehrskameras", "Straßenkameras", "Autobahnkameras"),
    "weather": ("Wetterkamera", "Wetterkameras"),
    "airport": ("Flughafen Webcam", "Flughafen Kamera"),
    "beach": ("Strand Webcam", "Surf Webcam"),
    "harbor": ("Hafen Webcam", "Hafen Kamera"),
    "city": ("Stadt Webcam", "Innenstadt Webcam"),
}

_JAPANESE_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("ライブカメラ", "ウェブカメラ", "防災カメラ"),
    "traffic": ("道路カメラ", "交通カメラ", "道路ライブカメラ"),
    "weather": ("気象カメラ", "天気カメラ", "河川カメラ"),
    "airport": ("空港ライブカメラ", "空港カメラ"),
    "beach": ("海岸ライブカメラ", "サーフカメラ"),
    "harbor": ("港 ライブカメラ", "港カメラ"),
    "city": ("市街地ライブカメラ", "街ライブカメラ"),
}

_KOREAN_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("라이브 카메라", "웹캠", "실시간 카메라"),
    "traffic": ("교통 카메라", "도로 카메라", "실시간 CCTV"),
    "weather": ("날씨 카메라", "기상 카메라"),
    "airport": ("공항 카메라", "공항 웹캠"),
    "beach": ("해변 카메라", "바다 웹캠"),
    "harbor": ("항구 카메라", "항만 카메라"),
    "city": ("도시 카메라", "시내 웹캠"),
}

_CHINESE_TRAD_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("即時影像", "即時攝影機", "網路攝影機", "直播攝影機"),
    "traffic": ("路況影像", "交通攝影機", "即時路況", "道路攝影機"),
    "weather": ("天氣攝影機", "氣象攝影機"),
    "airport": ("機場攝影機", "機場即時影像"),
    "beach": ("海灘攝影機", "海岸即時影像"),
    "harbor": ("港口攝影機", "碼頭即時影像"),
    "city": ("城市即時影像", "市區攝影機"),
}

_CHINESE_SIMP_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("实时摄像头", "直播摄像头", "网络摄像头"),
    "traffic": ("交通摄像头", "道路摄像头", "实时路况"),
    "weather": ("天气摄像头", "气象摄像头"),
    "airport": ("机场摄像头", "机场直播"),
    "beach": ("海滩摄像头", "海岸直播"),
    "harbor": ("港口摄像头", "码头直播"),
    "city": ("城市摄像头", "市区直播"),
}

_ARABIC_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("كاميرات مباشرة", "كاميرات حية", "كاميرات عامة", "بث مباشر كاميرا"),
    "traffic": ("كاميرات المرور", "كاميرات الطرق", "كاميرات حركة المرور"),
    "weather": ("كاميرات الطقس", "كاميرا الطقس"),
    "airport": ("كاميرا المطار", "كاميرات المطار"),
    "beach": ("كاميرا الشاطئ", "كاميرات الشاطئ"),
    "harbor": ("كاميرا الميناء", "كاميرات الميناء"),
    "city": ("كاميرا المدينة", "كاميرات المدينة"),
}

_RUSSIAN_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("камеры онлайн", "вебкамеры", "онлайн камеры", "камеры в реальном времени"),
    "traffic": ("дорожные камеры", "камеры дорожного движения", "трафик камеры"),
    "weather": ("погодные камеры", "метеокамеры"),
    "airport": ("камера аэропорта", "вебкамера аэропорта"),
    "beach": ("камера пляжа", "пляжная вебкамера"),
    "harbor": ("камера порта", "вебкамера порта"),
    "city": ("городские камеры", "вебкамеры города"),
}

_UKRAINIAN_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("камери онлайн", "вебкамери", "онлайн камери", "live webcams", "public cameras"),
    "traffic": ("дорожні камери", "камери дорожнього руху", "трафік камери", "traffic cameras"),
    "weather": ("погодні камери", "метеокамери", "weather cameras"),
    "airport": ("камера аеропорту", "airport webcam"),
    "city": ("міські камери", "камери міста", "city webcams"),
}

# Reusable terms for languages with closely related public-camera vocabulary.
_MALAY_INDONESIAN_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("kamera langsung", "kamera live", "webcam", "kamera publik"),
    "traffic": ("kamera trafik", "kamera lalu lintas", "kamera jalan raya", "CCTV trafik"),
    "weather": ("kamera cuaca",),
    "airport": ("kamera bandara", "kamera lapangan terbang"),
    "beach": ("kamera pantai", "webcam pantai"),
    "harbor": ("kamera pelabuhan",),
    "city": ("kamera kota",),
}

_TURKISH_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("canlı kamera", "webcam", "canlı yayın kamera"),
    "traffic": ("trafik kameraları", "yol kameraları", "canlı trafik kameraları"),
    "weather": ("hava durumu kamerası", "meteoroloji kamerası"),
    "airport": ("havaalanı kamerası",),
    "beach": ("plaj kamerası",),
    "harbor": ("liman kamerası",),
    "city": ("şehir kamerası",),
}

_HEBREW_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("מצלמות בשידור חי", "מצלמות אונליין", "מצלמות ציבוריות"),
    "traffic": ("מצלמות תנועה", "מצלמות כבישים"),
    "weather": ("מצלמות מזג אוויר",),
    "airport": ("מצלמת שדה תעופה",),
    "beach": ("מצלמת חוף",),
    "harbor": ("מצלמת נמל",),
    "city": ("מצלמות עירוניות",),
}

_POLISH_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("kamery online", "webcam", "kamera na żywo"),
    "traffic": ("kamery drogowe", "kamery ruchu", "kamery na drogach"),
    "weather": ("kamera pogodowa", "kamery pogodowe"),
    "airport": ("kamera lotnisko",),
    "beach": ("kamera plaża",),
    "harbor": ("kamera port",),
    "city": ("kamera miejska",),
}

_NORDIC_TERMS: dict[str, tuple[str, ...]] = {
    "default": ("webkamera", "livekamera", "webcam"),
    "traffic": ("trafikkamera", "veikamera", "vägkamera", "trafikkameror"),
    "weather": ("værkamera", "väderkamera", "kelikamera", "tiesääkamera"),
    "airport": ("flyplass webkamera", "flygplats kamera"),
    "beach": ("strand webkamera",),
    "harbor": ("hamn webkamera", "havn webkamera"),
    "city": ("stad webkamera", "city webkamera"),
}

_PROFILE_BY_COUNTRY: dict[str, LocationSearchProfile] = {
    # Existing core profiles.
    "mexico": _profile("Mexico", "mx", ("site:.gob.mx", "site:.mx"), ("es", "en"), ("mexico", "méxico", "mx", "ciudad de méxico", "mexico city"), _SPANISH_TERMS),
    "ukraine": _profile("Ukraine", "ua", ("site:.gov.ua", "site:.ua"), ("uk", "en"), ("ukraine", "ua", "україна", "украина"), _UKRAINIAN_TERMS),
    "united states": _profile("United States", "us", ("site:.gov", "site:.edu"), ("en",), ("united states", "usa", "us"), _ENGLISH_TERMS),
    "united kingdom": _profile("United Kingdom", "gb", ("site:.gov.uk", "site:.ac.uk", "site:.uk"), ("en",), ("united kingdom", "uk", "great britain", "england", "scotland", "wales"), _ENGLISH_TERMS),

    # First batch.
    "canada": _profile("Canada", "ca", ("site:.gc.ca", "site:.canada.ca", "site:.ca"), ("en", "fr"), ("canada", "ontario", "québec", "quebec", "british columbia", "alberta"), {**_ENGLISH_TERMS, "traffic": (*_ENGLISH_TERMS["traffic"], "caméras routières"), "weather": (*_ENGLISH_TERMS["weather"], "caméras météo")}),
    "australia": _profile("Australia", "au", ("site:.gov.au", "site:.edu.au", "site:.au"), ("en",), ("australia", "australian", "new south wales", "queensland", "victoria", "western australia", "nsw", "qld"), _ENGLISH_TERMS),
    "new zealand": _profile("New Zealand", "nz", ("site:.govt.nz", "site:.ac.nz", "site:.nz"), ("en",), ("new zealand", "aotearoa", "nz"), _ENGLISH_TERMS),
    "brazil": _profile("Brazil", "br", ("site:.gov.br", "site:.br"), ("pt",), ("brazil", "brasil", "br"), _PORTUGUESE_TERMS),
    "chile": _profile("Chile", "cl", ("site:.gob.cl", "site:.cl"), ("es",), ("chile", "cl"), _SPANISH_TERMS),
    "argentina": _profile("Argentina", "ar", ("site:.gob.ar", "site:.gov.ar", "site:.ar"), ("es",), ("argentina",), _SPANISH_TERMS),
    "colombia": _profile("Colombia", "co", ("site:.gov.co", "site:.co"), ("es",), ("colombia",), _SPANISH_TERMS),
    "spain": _profile("Spain", "es", ("site:.gob.es", "site:.es"), ("es",), ("spain", "españa", "es"), _SPANISH_TERMS),
    "france": _profile("France", "fr", ("site:.gouv.fr", "site:.fr"), ("fr",), ("france", "fr"), _FRENCH_TERMS),
    "germany": _profile("Germany", "de", ("site:.bund.de", "site:.de"), ("de",), ("germany", "deutschland", "de"), _GERMAN_TERMS),
    "japan": _profile("Japan", "jp", ("site:.go.jp", "site:.lg.jp", "site:.jp"), ("ja",), ("japan", "日本", "jp"), _JAPANESE_TERMS),
    "south korea": _profile("South Korea", "kr", ("site:.go.kr", "site:.kr"), ("ko",), ("south korea", "korea", "대한민국", "kr"), _KOREAN_TERMS),
    "taiwan": _profile("Taiwan", "tw", ("site:.gov.tw", "site:.tw"), ("zh-Hant",), ("taiwan", "臺灣", "台湾", "tw"), _CHINESE_TRAD_TERMS),
    "singapore": _profile("Singapore", "sg", ("site:.gov.sg", "site:.sg"), ("en",), ("singapore", "sg"), _ENGLISH_TERMS),
    "india": _profile("India", "in", ("site:.gov.in", "site:.nic.in", "site:.in"), ("en", "hi"), ("india", "भारत"), _ENGLISH_TERMS),

    # Second batch.
    "netherlands": _profile("Netherlands", "nl", ("site:.overheid.nl", "site:.nl"), ("nl", "en"), ("netherlands", "nederland", "holland"), {**_ENGLISH_TERMS, "traffic": ("verkeerscamera", "verkeerscamera's", *_ENGLISH_TERMS["traffic"]), "weather": ("weercamera", *_ENGLISH_TERMS["weather"])}),
    "norway": _profile("Norway", "no", ("site:.vegvesen.no", "site:.no"), ("no",), ("norway", "norge"), _NORDIC_TERMS),
    "sweden": _profile("Sweden", "se", ("site:.trafikverket.se", "site:.se"), ("sv",), ("sweden", "sverige", "se"), _NORDIC_TERMS),
    "finland": _profile("Finland", "fi", ("site:.fintraffic.fi", "site:.fi"), ("fi", "sv"), ("finland", "suomi"), _NORDIC_TERMS),
    "poland": _profile("Poland", "pl", ("site:.gov.pl", "site:.pl"), ("pl",), ("poland", "polska"), _POLISH_TERMS),
    "italy": _profile("Italy", "it", ("site:.gov.it", "site:.it"), ("it",), ("italy", "italia"), {**_ENGLISH_TERMS, "default": ("webcam in diretta", "telecamere in diretta", "webcam"), "traffic": ("telecamere traffico", "telecamere stradali"), "weather": ("webcam meteo", "telecamera meteo")}),
    "portugal": _profile("Portugal", "pt", ("site:.gov.pt", "site:.pt"), ("pt",), ("portugal",), _PORTUGUESE_TERMS),
    "south africa": _profile("South Africa", "za", ("site:.gov.za", "site:.za"), ("en",), ("south africa", "za"), _ENGLISH_TERMS),
    "united arab emirates": _profile("United Arab Emirates", "ae", ("site:.gov.ae", "site:.ae"), ("ar", "en"), ("united arab emirates", "uae", "الإمارات", "ae"), {**_ARABIC_TERMS, "traffic": (*_ARABIC_TERMS["traffic"], "traffic cameras", "road cameras")}),
    "israel": _profile("Israel", "il", ("site:.gov.il", "site:.il"), ("he", "en", "ar"), ("israel", "ישראל"), {**_HEBREW_TERMS, "traffic": (*_HEBREW_TERMS["traffic"], "traffic cameras", "road cameras")}),
    "thailand": _profile("Thailand", "th", ("site:.go.th", "site:.th"), ("th", "en"), ("thailand", "ประเทศไทย", "th"), {**_ENGLISH_TERMS, "default": ("กล้องถ่ายทอดสด", "กล้อง CCTV", "webcam"), "traffic": ("กล้องจราจร", "traffic cameras"), "weather": ("กล้องสภาพอากาศ", "weather cameras")}),
    "indonesia": _profile("Indonesia", "id", ("site:.go.id", "site:.id"), ("id",), ("indonesia",), _MALAY_INDONESIAN_TERMS),
    "philippines": _profile("Philippines", "ph", ("site:.gov.ph", "site:.ph"), ("en", "fil"), ("philippines", "pilipinas", "ph"), _ENGLISH_TERMS),
    "malaysia": _profile("Malaysia", "my", ("site:.gov.my", "site:.my"), ("ms", "en"), ("malaysia", "my"), _MALAY_INDONESIAN_TERMS),

    # Additional Asian profiles.
    "vietnam": _profile("Vietnam", "vn", ("site:.gov.vn", "site:.vn"), ("vi",), ("vietnam", "viet nam", "việt nam", "vn"), {**_ENGLISH_TERMS, "default": ("camera trực tiếp", "camera đường phố", "webcam"), "traffic": ("camera giao thông", "camera đường phố"), "weather": ("camera thời tiết",)}),
    "hong kong": _profile("Hong Kong", "hk", ("site:.gov.hk", "site:.hk"), ("en", "zh-Hant"), ("hong kong", "hong kong sar", "香港", "hk"), {**_ENGLISH_TERMS, **_CHINESE_TRAD_TERMS, "traffic": ("traffic snapshots", "traffic cameras", "路況影像", "交通攝影機")}),
    "china": _profile("China", "cn", ("site:.gov.cn", "site:.cn"), ("zh-Hans",), ("china", "中国", "cn"), _CHINESE_SIMP_TERMS),
    "pakistan": _profile("Pakistan", "pk", ("site:.gov.pk", "site:.pk"), ("en", "ur"), ("pakistan", "pk"), _ENGLISH_TERMS),
    "bangladesh": _profile("Bangladesh", "bd", ("site:.gov.bd", "site:.bd"), ("en", "bn"), ("bangladesh", "bd"), _ENGLISH_TERMS),
    "sri lanka": _profile("Sri Lanka", "lk", ("site:.gov.lk", "site:.lk"), ("en", "si", "ta"), ("sri lanka", "lk"), _ENGLISH_TERMS),
    "nepal": _profile("Nepal", "np", ("site:.gov.np", "site:.np"), ("en", "ne"), ("nepal", "np"), _ENGLISH_TERMS),
    "saudi arabia": _profile("Saudi Arabia", "sa", ("site:.gov.sa", "site:.sa"), ("ar", "en"), ("saudi arabia", "السعودية", "sa"), _ARABIC_TERMS),
    "qatar": _profile("Qatar", "qa", ("site:.gov.qa", "site:.qa"), ("ar", "en"), ("qatar", "قطر", "qa"), _ARABIC_TERMS),
    "kazakhstan": _profile("Kazakhstan", "kz", ("site:.gov.kz", "site:.kz"), ("kk", "ru", "en"), ("kazakhstan", "қазақстан", "казахстан", "kz"), _RUSSIAN_TERMS),
    "turkey": _profile("Turkey", "tr", ("site:.gov.tr", "site:.tr"), ("tr",), ("turkey", "türkiye"), _TURKISH_TERMS),
    "russia": _profile("Russia", "ru", ("site:.gov.ru", "site:.ru"), ("ru",), ("russia", "russian federation", "россия", "ru"), _RUSSIAN_TERMS),

    # Arabic-speaking country profiles.
    "algeria": _profile("Algeria", "dz", ("site:.gov.dz", "site:.dz"), ("ar", "fr"), ("algeria", "الجزائر", "dz"), {**_ARABIC_TERMS, **_FRENCH_TERMS}),
    "bahrain": _profile("Bahrain", "bh", ("site:.gov.bh", "site:.bh"), ("ar", "en"), ("bahrain", "البحرين", "bh"), _ARABIC_TERMS),
    "comoros": _profile("Comoros", "km", ("site:.gouv.km", "site:.km"), ("ar", "fr"), ("comoros", "جزر القمر"), {**_ARABIC_TERMS, **_FRENCH_TERMS}),
    "djibouti": _profile("Djibouti", "dj", ("site:.gouv.dj", "site:.dj"), ("ar", "fr"), ("djibouti", "جيبوتي"), {**_ARABIC_TERMS, **_FRENCH_TERMS}),
    "egypt": _profile("Egypt", "eg", ("site:.gov.eg", "site:.eg"), ("ar", "en"), ("egypt", "مصر", "eg"), _ARABIC_TERMS),
    "iraq": _profile("Iraq", "iq", ("site:.gov.iq", "site:.iq"), ("ar", "ku"), ("iraq", "العراق"), _ARABIC_TERMS),
    "jordan": _profile("Jordan", "jo", ("site:.gov.jo", "site:.jo"), ("ar", "en"), ("jordan", "الأردن"), _ARABIC_TERMS),
    "kuwait": _profile("Kuwait", "kw", ("site:.gov.kw", "site:.kw"), ("ar", "en"), ("kuwait", "الكويت", "kw"), _ARABIC_TERMS),
    "lebanon": _profile("Lebanon", "lb", ("site:.gov.lb", "site:.lb"), ("ar", "fr", "en"), ("lebanon", "لبنان"), _ARABIC_TERMS),
    "libya": _profile("Libya", "ly", ("site:.gov.ly", "site:.ly"), ("ar",), ("libya", "ليبيا"), _ARABIC_TERMS),
    "mauritania": _profile("Mauritania", "mr", ("site:.gov.mr", "site:.mr"), ("ar", "fr"), ("mauritania", "موريتانيا"), _ARABIC_TERMS),
    "morocco": _profile("Morocco", "ma", ("site:.gov.ma", "site:.ma"), ("ar", "fr"), ("morocco", "المغرب", "maroc", "ma"), {**_ARABIC_TERMS, **_FRENCH_TERMS}),
    "oman": _profile("Oman", "om", ("site:.gov.om", "site:.om"), ("ar", "en"), ("oman", "عمان"), _ARABIC_TERMS),
    "palestine": _profile("Palestine", "ps", ("site:.gov.ps", "site:.ps"), ("ar", "en"), ("palestine", "فلسطين"), _ARABIC_TERMS),
    "somalia": _profile("Somalia", "so", ("site:.gov.so", "site:.so"), ("ar", "so", "en"), ("somalia", "الصومال"), _ARABIC_TERMS),
    "sudan": _profile("Sudan", "sd", ("site:.gov.sd", "site:.sd"), ("ar", "en"), ("sudan", "السودان"), _ARABIC_TERMS),
    "syria": _profile("Syria", "sy", ("site:.gov.sy", "site:.sy"), ("ar",), ("syria", "سوريا"), _ARABIC_TERMS),
    "tunisia": _profile("Tunisia", "tn", ("site:.gov.tn", "site:.tn"), ("ar", "fr"), ("tunisia", "تونس"), {**_ARABIC_TERMS, **_FRENCH_TERMS}),
    "yemen": _profile("Yemen", "ye", ("site:.gov.ye", "site:.ye"), ("ar",), ("yemen", "اليمن"), _ARABIC_TERMS),
}

_GENERIC_CAMERA_TERMS_BY_INTENT: dict[str, tuple[str, ...]] = {
    "default": ("public cameras", "live cameras", "live webcams", "camera map", "camera feed json"),
    "traffic": ("traffic cameras", "road cameras", "highway cameras", "traffic camera map", "road conditions cameras"),
    "weather": ("weather cameras", "weather webcam", "live weather camera"),
    "airport": ("airport cameras", "airport weather camera", "runway camera"),
    "beach": ("beach cameras", "surf camera", "beach webcam"),
    "harbor": ("harbor cameras", "port cameras", "marina cameras"),
    "city": ("city webcam", "downtown camera", "municipal camera"),
}

_US_STATES: tuple[str, ...] = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
    "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
)


def country_code_from_location(location: str) -> str | None:
    """Return an ISO alpha-2 country code when a location string names a country."""
    text = _normalize(location)
    if not text:
        return None
    # Longest-name first so "united kingdom" beats shorter substrings.
    for name, code in sorted(_COUNTRY_CODES.items(), key=lambda item: len(item[0]), reverse=True):
        if _contains_phrase(text, name):
            return code
    for token in re.findall(r"\b[a-z]{2,3}\b", text):
        if token in _COUNTRY_ALIASES:
            alias = _COUNTRY_ALIASES[token].casefold()
            return _COUNTRY_CODES.get(alias)
    return None


def location_search_profile(location: str) -> LocationSearchProfile:
    """Infer search hints for a location string without deciding scope/trust."""
    text = _normalize(location)
    if not text:
        return LocationSearchProfile()
    for profile_key, profile in _PROFILE_BY_COUNTRY.items():
        aliases = profile.aliases or (profile_key,)
        if any(_contains_phrase(text, alias) for alias in aliases):
            return profile
    if any(_contains_phrase(text, state) for state in _US_STATES):
        return _PROFILE_BY_COUNTRY["united states"]
    code = country_code_from_location(location)
    if code:
        canonical = next((name.title() for name, cc in _COUNTRY_CODES.items() if cc == code), None)
        scopes = tuple(_dedupe([f"site:.gov.{code}", f"site:.{code}"]))
        return LocationSearchProfile(country_name=canonical, country_code=code, official_site_scopes=scopes, languages=("en",), localized_terms={})
    return LocationSearchProfile()


def country_aliases_for_location(location: str) -> tuple[str, ...]:
    """Return known country/profile aliases for a location string.

    This is shared evidence/context data for downstream modules. It does not
    decide target scope or trust.
    """
    profile = location_search_profile(location)
    values: list[str] = []
    if profile.country_name:
        values.append(profile.country_name)
    if profile.country_code:
        values.append(profile.country_code.upper())
    values.extend(profile.aliases)

    code = country_code_from_location(location)
    if code:
        values.append(code.upper())
        canonical = next((name.title() for name, cc in _COUNTRY_CODES.items() if cc == code), None)
        if canonical:
            values.append(canonical)

    return tuple(_dedupe([value for value in values if value]))


def official_site_scopes_for_location(location: str, *, include_global_fallback: bool = True) -> tuple[str, ...]:
    """Return public-source site scopes ordered from location-specific to generic."""
    profile = location_search_profile(location)
    scopes: list[str] = list(profile.official_site_scopes)
    if include_global_fallback:
        scopes.extend(["site:.gov", "site:.edu"])
    return tuple(_dedupe(scopes))


def localized_camera_terms_for_intent(camera_type_intent: str, location: str, *, include_generic: bool = False) -> tuple[str, ...]:
    """Return localized camera/source terms for a location and camera intent."""
    key = _intent_key(camera_type_intent)
    profile = location_search_profile(location)
    terms: list[str] = []
    localized = profile.localized_terms or {}
    terms.extend(localized.get(key, ()))
    if key != "default":
        terms.extend(localized.get("default", ()))
    if include_generic:
        terms.extend(_GENERIC_CAMERA_TERMS_BY_INTENT.get(key, ()))
        if key != "default":
            terms.extend(_GENERIC_CAMERA_TERMS_BY_INTENT.get("default", ()))
    return tuple(_dedupe([term for term in terms if term]))


def safe_exclusion_fragment() -> str:
    return " " + " ".join(_BLOCKED_SITE_EXCLUSIONS)


def _intent_key(camera_type_intent: str) -> str:
    lowered = (camera_type_intent or "default").replace("_", " ").casefold()
    for key in ("traffic", "weather", "airport", "beach", "harbor", "port", "marina", "city"):
        if key in lowered:
            return key
    return "default"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = _normalize(phrase)
    if not phrase:
        return False
    # Non-Latin scripts and mixed-script aliases often do not use ASCII word
    # boundaries. Substring matching is acceptable here because this module only
    # produces search hints; it never validates scope or trust.
    if any(ord(ch) > 127 for ch in phrase):
        return phrase in text
    return bool(re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", text, flags=re.I | re.UNICODE))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out

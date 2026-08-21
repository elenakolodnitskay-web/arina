import enum

from db.models import Tariff

# Фаза 28: тариф — самоописание/позиционирование Арины и самостоятельно
# выбираемый пользователем набор активных функций, НЕ платная подписка (в MVP
# биллинга нет, см. CLAUDE.md) — переключение через /tariff свободное, в обе
# стороны, без каких-либо ограничений или оплаты. Уже существующие
# бета-пользователи получают тариф trusted (полный набор) при миграции — не
# теряют задним числом доступ к тому, чем уже пользовались (db/models.py,
# server_default='trusted'). Базовые функции (задачи/напоминания, свободный чат,
# память — окно Фазы 19 + семантический поиск Фазы 27) доступны на любом тарифе,
# не входят в Feature ниже — это ядро ассистента, не то, чем можно управлять.


class Feature(str, enum.Enum):
    finance = "finance"
    documents = "documents"
    relay = "relay"
    email = "email"
    voice = "voice"


TARIFF_FEATURES: dict[Tariff, set[Feature]] = {
    Tariff.secretary: set(),
    Tariff.accountant: {Feature.finance, Feature.documents},
    Tariff.trusted: {Feature.finance, Feature.documents, Feature.relay, Feature.email, Feature.voice},
}

TARIFF_LABELS: dict[Tariff, str] = {
    Tariff.secretary: "Секретарь",
    Tariff.accountant: "Бухгалтер",
    Tariff.trusted: "Доверенное лицо",
}

TARIFF_DESCRIPTIONS: dict[Tariff, str] = {
    Tariff.secretary: "Задачи, напоминания и свободный чат с памятью — базовый набор.",
    Tariff.accountant: "То же, что «Секретарь», плюс учёт финансов и генерация документов.",
    Tariff.trusted: (
        "То же, что «Бухгалтер», плюс пересылка сообщений другим пользователям Арины, "
        "email-напоминания и голосовые ответы."
    ),
}

# Порядок для кнопок /tariff — от базового к полному, не влияет на права
# (переключение свободное в любую сторону).
TARIFF_ORDER: list[Tariff] = [Tariff.secretary, Tariff.accountant, Tariff.trusted]

FEATURE_LABELS: dict[Feature, str] = {
    Feature.finance: "учёт финансов",
    Feature.documents: "генерация документов",
    Feature.relay: "пересылка сообщений другим пользователям Арины",
    Feature.email: "email-напоминания",
    Feature.voice: "голосовые ответы",
}


def has_feature(tariff: Tariff, feature: Feature) -> bool:
    return feature in TARIFF_FEATURES[tariff]


def min_tariff_for(feature: Feature) -> Tariff:
    for tariff in TARIFF_ORDER:
        if feature in TARIFF_FEATURES[tariff]:
            return tariff
    raise ValueError(f"Функция {feature} недоступна ни на одном тарифе")


def feature_unavailable_message(feature: Feature) -> str:
    required = min_tariff_for(feature)
    return (
        f"Эта функция ({FEATURE_LABELS[feature]}) доступна начиная с тарифа "
        f"«{TARIFF_LABELS[required]}» — переключиться можно в любой момент и бесплатно "
        f"через /tariff."
    )

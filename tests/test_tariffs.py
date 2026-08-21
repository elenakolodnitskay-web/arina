from core import tariffs
from db.models import Tariff


def test_secretary_has_no_gated_features():
    for feature in tariffs.Feature:
        assert not tariffs.has_feature(Tariff.secretary, feature)


def test_accountant_has_finance_and_documents_only():
    assert tariffs.has_feature(Tariff.accountant, tariffs.Feature.finance)
    assert tariffs.has_feature(Tariff.accountant, tariffs.Feature.documents)
    assert not tariffs.has_feature(Tariff.accountant, tariffs.Feature.relay)
    assert not tariffs.has_feature(Tariff.accountant, tariffs.Feature.email)
    assert not tariffs.has_feature(Tariff.accountant, tariffs.Feature.voice)


def test_trusted_has_all_features():
    for feature in tariffs.Feature:
        assert tariffs.has_feature(Tariff.trusted, feature)


def test_min_tariff_for_finance_is_accountant():
    assert tariffs.min_tariff_for(tariffs.Feature.finance) == Tariff.accountant


def test_min_tariff_for_voice_is_trusted():
    assert tariffs.min_tariff_for(tariffs.Feature.voice) == Tariff.trusted


def test_feature_unavailable_message_mentions_tariff_command():
    message = tariffs.feature_unavailable_message(tariffs.Feature.relay)

    assert "/tariff" in message
    assert "Доверенное лицо" in message


def test_all_tariffs_have_labels_and_descriptions():
    for tariff in Tariff:
        assert tariff in tariffs.TARIFF_LABELS
        assert tariff in tariffs.TARIFF_DESCRIPTIONS
        assert tariff in tariffs.TARIFF_FEATURES

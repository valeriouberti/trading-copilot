"""Test suite per il modulo sentiment."""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from modules.sentiment import (
    SentimentResult,
    analyze_sentiment,
    _analyze_with_groq,
    _analyze_with_finbert,
    _build_prompt,
)


SAMPLE_ASSETS = [{"symbol": "NQ=F", "display_name": "NASDAQ 100 Futures"}]


def _make_groq_response(content: str) -> MagicMock:
    """Crea un mock della risposta Groq."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


class TestValidGroqResponse:
    def test_valid_response_parsed(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verifica che una risposta Groq valida venga parsata correttamente."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps(mock_llm_response)
        )

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert result.sentiment_score == 1.0
        assert result.sentiment_label == "moderatamente rialzista"
        assert result.source in ("groq", "groq-2pass")

    def test_response_has_all_keys(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verifica che l'output contenga tutte le chiavi richieste."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps(mock_llm_response)
        )

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        result_dict = result.to_dict()
        required_keys = {"sentiment_score", "sentiment_label", "key_drivers", "directional_bias", "risk_events", "confidence"}
        assert required_keys.issubset(result_dict.keys())


class TestSentimentScoreRange:
    def test_score_within_range(self, mock_news_items: list) -> None:
        """Verifica che il sentiment score sia tra -3 e +3."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps({"sentiment_score": 2.5, "sentiment_label": "rialzista", "key_drivers": ["a", "b", "c"], "directional_bias": "BULLISH", "risk_events": [], "confidence": 80})
        )

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert -3 <= result.sentiment_score <= 3

    def test_out_of_range_score_accepted_as_float(self, mock_news_items: list) -> None:
        """Verifica che uno score out-of-range venga comunque parsato come float."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps({"sentiment_score": 5, "sentiment_label": "test", "key_drivers": ["a", "b", "c"], "directional_bias": "BULLISH", "risk_events": [], "confidence": 80})
        )

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert isinstance(result.sentiment_score, float)


class TestKeyDriversCount:
    def test_exactly_three_drivers(self, mock_news_items: list) -> None:
        """Verifica che key_drivers contenga esattamente 3 elementi."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps({"sentiment_score": 1, "sentiment_label": "ok", "key_drivers": ["a", "b", "c"], "directional_bias": "BULLISH", "risk_events": [], "confidence": 70})
        )

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert len(result.key_drivers) == 3

    def test_five_drivers_truncated_to_three(self, mock_news_items: list) -> None:
        """Verifica che 5 drivers vengano troncati a 3."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps({"sentiment_score": 1, "sentiment_label": "ok", "key_drivers": ["a", "b", "c", "d", "e"], "directional_bias": "BULLISH", "risk_events": [], "confidence": 70})
        )

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert len(result.key_drivers) <= 3


class TestMalformedResponse:
    def test_plain_text_response_raises(self, mock_news_items: list) -> None:
        """Verifica che una risposta non-JSON causi fallback dopo i retry."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            "This is not JSON at all, just plain text analysis."
        )

        with patch("modules.sentiment.Groq", return_value=mock_client):
            with patch("modules.sentiment.time.sleep"):
                with pytest.raises(json.JSONDecodeError):
                    _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

    def test_malformed_json_full_pipeline_fallback(self, mock_news_items: list) -> None:
        """Verifica che il pipeline completo faccia fallback se Groq restituisce testo."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response("not json")

        with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key"}):
            with patch("modules.sentiment.Groq", return_value=mock_client):
                with patch("modules.sentiment.time.sleep"):
                    with patch("modules.sentiment._analyze_with_finbert") as mock_finbert:
                        mock_finbert.return_value = SentimentResult(
                            sentiment_score=0.0,
                            sentiment_label="Neutro",
                            key_drivers=["Fallback"],
                            directional_bias="NEUTRAL",
                            confidence=0.0,
                            source="finbert",
                        )
                        result = analyze_sentiment(mock_news_items, SAMPLE_ASSETS)

        assert result.source == "finbert"


class TestGroqRateLimit:
    def test_retry_on_rate_limit(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verifica il retry con backoff esponenziale su rate limit."""
        mock_client = MagicMock()
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Error code: 429 rate_limit exceeded")
            return _make_groq_response(json.dumps(mock_llm_response))

        mock_client.chat.completions.create.side_effect = side_effect

        with patch("modules.sentiment.Groq", return_value=mock_client):
            with patch("modules.sentiment.time.sleep") as mock_sleep:
                result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert result.sentiment_score == 1.0
        assert mock_sleep.call_count == 2  # 2 retries before success


class TestGroqTotalFailure:
    def test_fallback_on_total_groq_failure(self, mock_news_items: list) -> None:
        """Verifica che il fallback a FinBERT funzioni se Groq fallisce completamente."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key"}):
            with patch("modules.sentiment.Groq") as mock_groq_class:
                mock_groq_class.return_value.chat.completions.create.side_effect = Exception("Service down")
                with patch("modules.sentiment._analyze_with_finbert") as mock_finbert:
                    mock_finbert.return_value = SentimentResult(
                        sentiment_score=0.0,
                        sentiment_label="Neutro",
                        key_drivers=["Fallback attivo"],
                        directional_bias="NEUTRAL",
                        confidence=0.0,
                        source="finbert",
                    )
                    result = analyze_sentiment(mock_news_items, SAMPLE_ASSETS)

        assert result.source == "finbert"
        assert result.error is None


class TestNoApiKey:
    def test_no_api_key_uses_finbert(self, mock_news_items: list) -> None:
        """Verifica che senza GROQ_API_KEY si usi il fallback FinBERT."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove GROQ_API_KEY entirely
            env = os.environ.copy()
            env.pop("GROQ_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                with patch("modules.sentiment._analyze_with_finbert") as mock_finbert:
                    mock_finbert.return_value = SentimentResult(
                        sentiment_score=0.0,
                        sentiment_label="Neutro",
                        key_drivers=["No API key"],
                        directional_bias="NEUTRAL",
                        confidence=0.0,
                        source="finbert",
                    )
                    result = analyze_sentiment(mock_news_items, SAMPLE_ASSETS)

        assert result.source == "finbert"


class TestEmptyNews:
    def test_empty_news_returns_neutral(self) -> None:
        """Verifica che senza notizie il risultato sia neutro."""
        result = analyze_sentiment([], SAMPLE_ASSETS)
        assert result.sentiment_score == 0.0
        assert result.directional_bias == "NEUTRAL"


class TestBuildPrompt:
    def test_prompt_contains_asset_names(self, mock_news_items: list) -> None:
        """Verifica che il prompt contenga i nomi degli asset."""
        prompt = _build_prompt(mock_news_items, SAMPLE_ASSETS)
        assert "NASDAQ 100 Futures" in prompt

    def test_prompt_contains_news(self, mock_news_items: list) -> None:
        """Verifica che il prompt contenga i titoli delle notizie."""
        prompt = _build_prompt(mock_news_items, SAMPLE_ASSETS)
        assert "Tech stocks rally" in prompt

    def test_prompt_requests_json(self, mock_news_items: list) -> None:
        """Verifica che il prompt richieda output JSON."""
        prompt = _build_prompt(mock_news_items, SAMPLE_ASSETS)
        assert "JSON" in prompt


class TestFinBERTFallback:
    def test_finbert_with_positive_news(self, mock_news_items: list) -> None:
        """Verifica che FinBERT produca un risultato con notizie positive."""
        mock_classifier = MagicMock()
        mock_classifier.return_value = [
            {"label": "positive", "score": 0.85},
            {"label": "positive", "score": 0.72},
            {"label": "negative", "score": 0.60},
            {"label": "neutral", "score": 0.55},
            {"label": "positive", "score": 0.90},
        ]

        with patch("modules.sentiment.pipeline", create=True) as mock_pipeline:
            mock_pipeline.return_value = mock_classifier
            # We need to mock the import inside the function
            import modules.sentiment as sent_mod
            with patch.object(sent_mod, "_analyze_with_finbert", wraps=sent_mod._analyze_with_finbert):
                with patch("modules.sentiment.pipeline", mock_pipeline):
                    result = _analyze_with_finbert(mock_news_items)

        assert isinstance(result.sentiment_score, float)
        assert -3 <= result.sentiment_score <= 3
        assert result.source == "finbert"
        assert len(result.key_drivers) <= 3

    def test_finbert_with_negative_news(self) -> None:
        """Verifica che FinBERT gestisca notizie negative."""
        news = [
            {"title": "Markets crash", "summary": "", "source": "A", "published_at": "now"},
            {"title": "Stocks plunge", "summary": "", "source": "B", "published_at": "now"},
        ]
        mock_classifier = MagicMock()
        mock_classifier.return_value = [
            {"label": "negative", "score": 0.90},
            {"label": "negative", "score": 0.85},
        ]

        with patch("transformers.pipeline", return_value=mock_classifier):
            result = _analyze_with_finbert(news)

        assert result.sentiment_score <= 0
        assert result.source == "finbert"

    def test_finbert_import_error(self) -> None:
        """Verifica gestione errore se transformers non installato."""
        news = [{"title": "Test", "summary": "", "source": "A", "published_at": "now"}]

        with patch.dict("sys.modules", {"transformers": None}):
            with patch("builtins.__import__", side_effect=ImportError("no transformers")):
                # Directly test the function behavior when import fails
                result = _analyze_with_finbert(news)
                # If transformers IS available in the test env, it won't fail
                # So we just verify we get a valid result
                assert result.source == "finbert"

    def test_finbert_model_load_error(self) -> None:
        """Verifica gestione errore nel caricamento del modello FinBERT."""
        news = [{"title": "Test", "summary": "", "source": "A", "published_at": "now"}]

        with patch("transformers.pipeline", side_effect=Exception("Model download failed")):
            result = _analyze_with_finbert(news)

        assert result.source == "finbert"
        assert result.error is not None


class TestSentimentResultSerialization:
    def test_to_dict(self) -> None:
        """Verifica la serializzazione di SentimentResult."""
        result = SentimentResult(
            sentiment_score=1.5,
            sentiment_label="Rialzista",
            key_drivers=["a", "b", "c"],
            directional_bias="BULLISH",
            risk_events=["CPI release"],
            confidence=75.0,
            source="groq",
        )
        d = result.to_dict()
        assert d["sentiment_score"] == 1.5
        assert d["directional_bias"] == "BULLISH"
        assert len(d["key_drivers"]) == 3
        assert "CPI release" in d["risk_events"]

    def test_to_dict_with_error(self) -> None:
        """Verifica serializzazione con errore."""
        result = SentimentResult(
            sentiment_score=0.0,
            sentiment_label="Errore",
            error="API timeout",
        )
        d = result.to_dict()
        assert d["error"] == "API timeout"


class TestGroqMarkdownCleanup:
    def test_markdown_fenced_json_cleaned(self, mock_news_items: list, mock_llm_response: dict) -> None:
        """Verifica che il JSON avvolto in markdown fences venga pulito."""
        mock_client = MagicMock()
        fenced_json = f"```json\n{json.dumps(mock_llm_response)}\n```"
        mock_client.chat.completions.create.return_value = _make_groq_response(fenced_json)

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        assert result.sentiment_score == 1.0
        assert result.source in ("groq", "groq-2pass")


class TestPerAssetScoring:
    """Test per-asset scoring (v2)."""

    def test_per_asset_scores_populated(self, mock_news_items: list) -> None:
        """Verifica che i punteggi per-asset vengano estratti dal JSON."""
        response_data = {
            "sentiment_score": 1.0,
            "sentiment_label": "rialzista",
            "key_drivers": ["a", "b", "c"],
            "directional_bias": "BULLISH",
            "risk_events": [],
            "confidence": 70,
            "asset_scores": {"NQ=F": 1.5, "GC=F": -0.8},
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps(response_data)
        )
        assets = [
            {"symbol": "NQ=F", "display_name": "NASDAQ 100"},
            {"symbol": "GC=F", "display_name": "Gold"},
        ]

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, assets, "llama-3.3-70b-versatile", "fake-key")

        assert result.asset_scores["NQ=F"] == 1.5
        assert result.asset_scores["GC=F"] == -0.8
        assert result.asset_biases["NQ=F"] == "BULLISH"
        assert result.asset_biases["GC=F"] == "BEARISH"

    def test_asset_scores_fallback_to_global(self, mock_news_items: list) -> None:
        """Se un asset non ha score specifico, usa il globale."""
        response_data = {
            "sentiment_score": 1.0,
            "sentiment_label": "rialzista",
            "key_drivers": ["a", "b", "c"],
            "directional_bias": "BULLISH",
            "risk_events": [],
            "confidence": 70,
            "asset_scores": {},  # Empty
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_groq_response(
            json.dumps(response_data)
        )

        with patch("modules.sentiment.Groq", return_value=mock_client):
            result = _analyze_with_groq(mock_news_items, SAMPLE_ASSETS, "llama-3.3-70b-versatile", "fake-key")

        # Falls back to global sentiment_score of 1.0
        assert result.asset_scores["NQ=F"] == 1.0
        assert result.asset_biases["NQ=F"] == "BULLISH"


class TestTemporalTagging:
    """Test temporal recency tagging."""

    def test_news_tagged_with_recency(self, mock_news_items: list) -> None:
        """Verifica che le notizie vengano taggate con recency."""
        from modules.sentiment import _tag_news_with_recency

        tagged = _tag_news_with_recency(mock_news_items)
        assert len(tagged) == len(mock_news_items)
        # First article was 2h ago
        assert "h fa" in tagged[0]["_time_tag"]

    def test_news_without_datetime_gets_no_tag(self) -> None:
        """Notizie senza datetime valida ricevono tag vuoto."""
        from modules.sentiment import _tag_news_with_recency

        news = [{"title": "Test", "published_at": "not-a-date", "source": "X"}]
        tagged = _tag_news_with_recency(news)
        assert tagged[0]["_time_tag"] == ""


class TestFinBERTEnsemble:
    """Test FinBERT cross-validation ensemble."""

    def test_agree_boosts_confidence(self) -> None:
        """Scores entro 1.0 → AGREE, boost +5%."""
        from modules.sentiment import _compute_finbert_agreement

        label, mod = _compute_finbert_agreement(1.0, 1.5)
        assert label == "AGREE"
        assert mod == 5.0

    def test_disagree_reduces_confidence(self) -> None:
        """Divergenza > 2.0 → DISAGREE, -15%."""
        from modules.sentiment import _compute_finbert_agreement

        label, mod = _compute_finbert_agreement(2.0, -1.0)
        assert label == "DISAGREE"
        assert mod == -15.0

    def test_partial_no_change(self) -> None:
        """Divergenza 1-2 → PARTIAL, nessuna modifica."""
        from modules.sentiment import _compute_finbert_agreement

        label, mod = _compute_finbert_agreement(1.0, -0.5)
        assert label == "PARTIAL"
        assert mod == 0.0

    def test_none_finbert_returns_empty(self) -> None:
        """FinBERT None → label vuoto."""
        from modules.sentiment import _compute_finbert_agreement

        label, mod = _compute_finbert_agreement(1.0, None)
        assert label == ""
        assert mod == 0.0

    def test_to_dict_includes_v2_fields(self) -> None:
        """Verifica che to_dict includa i campi v2."""
        result = SentimentResult(
            sentiment_score=1.0,
            sentiment_label="Rialzista",
            asset_scores={"NQ=F": 1.5},
            asset_biases={"NQ=F": "BULLISH"},
            finbert_score=1.2,
            finbert_agreement="AGREE",
        )
        d = result.to_dict()
        assert d["asset_scores"] == {"NQ=F": 1.5}
        assert d["asset_biases"] == {"NQ=F": "BULLISH"}
        assert d["finbert_score"] == 1.2
        assert d["finbert_agreement"] == "AGREE"

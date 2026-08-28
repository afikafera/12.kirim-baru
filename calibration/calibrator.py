import json


class ConfidenceCalibrator:
    """Kalibrasi confidence dengan bucket + multiplier + clamp."""

    BUCKETS = {
        (0.9, 1.0): "0.9-1.0",
        (0.7, 0.9): "0.7-0.9",
        (0.5, 0.7): "0.5-0.7",
        (0.0, 0.5): "0.0-0.5",
    }

    MIDPOINTS = {
        "0.9-1.0": 0.95,
        "0.7-0.9": 0.80,
        "0.5-0.7": 0.60,
        "0.0-0.5": 0.25,
    }

    def __init__(self, memory_manager):
        self.mm = memory_manager

    def get_bucket(self, confidence: float) -> str:
        for (lo, hi), name in self.BUCKETS.items():
            if lo <= confidence < hi or (confidence == 1.0 and name == "0.9-1.0"):
                return name
        return "0.0-0.5"

    def apply_calibration(self, raw_confidence: float, domain: str = "global") -> tuple:
        """Return (calibrated_confidence, metadata)."""
        bucket = self.get_bucket(raw_confidence)

        # Cari kalibrasi domain spesifik
        cal = self.mm.get_calibration(domain, bucket)
        if not cal:
            cal = self.mm.get_calibration("global", bucket)

        if not cal or cal["total_predictions"] < 3:
            return raw_confidence, {
                "raw_confidence": raw_confidence,
                "bucket": bucket,
                "calibrated": False,
                "reason": "insufficient_data"
            }

        multiplier = cal["calibration_multiplier"]
        calibrated = raw_confidence * multiplier

        # BUG FIX: clamp ke [0.0, 1.0]
        calibrated = max(0.0, min(1.0, calibrated))

        return calibrated, {
            "raw_confidence": raw_confidence,
            "bucket": bucket,
            "multiplier": multiplier,
            "calibrated_confidence": calibrated,
            "calibrated": True,
            "domain": cal["calibration_domain"],
            "sample_size": cal["total_predictions"],
            "clamped": (raw_confidence * multiplier) != calibrated
        }

    def record_outcome(self, raw_confidence: float, domain: str, is_success: bool):
        """Catat hasil prediksi untuk kalibrasi."""
        bucket = self.get_bucket(raw_confidence)
        self.mm.record_prediction_outcome(domain, bucket, is_success)

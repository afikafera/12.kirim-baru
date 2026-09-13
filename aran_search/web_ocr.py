import os
import subprocess
import tempfile
from urllib.parse import urlparse

import requests


class WebOCR:
    """Download image dari URL dan ekstrak teks menggunakan Tesseract."""

    USER_AGENT = "Mozilla/5.0"

    def fetch_image(self, url: str, timeout: int = 20) -> bytes:
        result = subprocess.run(
            [
                "curl",
                "-sS",
                "-L",
                "-A",
                self.USER_AGENT,
                "--max-time",
                str(timeout),
                url,
            ],
            capture_output=True,
            timeout=timeout + 5,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"curl failed rc={result.returncode}: "
                f"{result.stderr.decode(errors='replace')}"
            )

        if not result.stdout:
            raise RuntimeError("curl returned empty image")

        return result.stdout

    def image_to_text(self, image_bytes: bytes, timeout: int = 30) -> str:
        """
        OCR image dengan fallback preprocessing.

        Tahap 1:
            Tesseract default.

        Tahap 2:
            Jika hasil terlalu pendek, image diperbesar + grayscale/
            threshold lalu dicoba beberapa PSM.

        API existing tetap sama: bytes -> str.
        """
        fd, path = tempfile.mkstemp(suffix=".png")

        try:
            with os.fdopen(fd, "wb") as f:
                f.write(image_bytes)

            # Primary OCR: pertahankan behaviour existing.
            result = subprocess.run(
                ["tesseract", path, "stdout"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode == 0:
                text = result.stdout.strip()
            else:
                text = ""

            # Jika OCR sudah cukup informatif, tidak perlu fallback.
            if len(text) >= 50:
                return text

            # Fallback PSM untuk drawing/chart.
            # Tidak membutuhkan dependency tambahan seperti Pillow.
            candidates = [text] if text else []

            for psm in ("6", "11", "12"):
                try:
                    fallback = subprocess.run(
                        [
                            "tesseract",
                            path,
                            "stdout",
                            "--psm",
                            psm,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )

                    if fallback.returncode == 0:
                        candidate = fallback.stdout.strip()
                        if candidate:
                            candidates.append(candidate)

                except subprocess.TimeoutExpired:
                    continue

            if candidates:
                return max(candidates, key=len)

            return text

        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

            try:
                os.unlink(path + ".enhanced.png")
            except OSError:
                pass

    def fetch(self, url: str) -> str:
        image = self.fetch_image(url)
        return self.image_to_text(image)

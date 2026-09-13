import base64
import json
import subprocess
import threading
from typing import List


class AgentBrowserAssetResolver:
    """
    Resolve image assets dari halaman web menggunakan agent-browser.

    Tidak melakukan OCR dan tidak mengubah WebOCR.
    """

    _GLOBAL_BROWSER_LOCK = threading.Lock()

    def __init__(self, timeout: int = 60, attempts: int = 3):
        self.timeout = timeout
        self.attempts = attempts

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            ["npx", "agent-browser", *args],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"agent-browser failed rc={result.returncode}: "
                f"{result.stderr.strip()}"
            )

        return result.stdout.strip()

    def _open_with_retry(self, page_url: str) -> None:
        """Open product page dengan retry untuk transient Page.navigate timeout."""
        last_error = None

        for attempt in range(1, self.attempts + 1):
            print(f"=== OPEN ATTEMPT {attempt}/{self.attempts} ===")

            try:
                self._run("open", page_url)
                return

            except Exception as e:
                last_error = e
                print(f"OPEN ATTEMPT {attempt} FAILED: {e}")

        raise RuntimeError(
            f"Open page gagal setelah {self.attempts} attempt: {last_error}"
        )

    def resolve_images(self, page_url: str) -> List[str]:
        """
        Buka halaman dan ambil seluruh document.images[].src.

        Retry diperlukan karena target JIC kadang mengalami
        CDP Page.navigate timeout.
        """
        last_error = None

        for attempt in range(1, self.attempts + 1):
            print(f"=== ATTEMPT {attempt}/{self.attempts} ===")

            try:
                with AgentBrowserAssetResolver._GLOBAL_BROWSER_LOCK:
                    self._run("close", "--all")

                    print("OPEN:")
                    self._run("open", page_url)

                    print("RAW EVAL:")
                    output = self._run(
                        "eval",
                        'JSON.stringify([...document.images].map(x => x.src))'
                    )

                # agent-browser mengembalikan JSON.stringify(...) sebagai
                # JSON string, sehingga perlu decode dua kali.
                images = json.loads(output)

                if isinstance(images, str):
                    images = json.loads(images)

                if not isinstance(images, list):
                    raise RuntimeError(
                        f"eval returned JSON bukan list: {type(images).__name__}"
                    )

                return [
                    url
                    for url in images
                    if isinstance(url, str)
                    and url.startswith(("http://", "https://"))
                ]

            except Exception as e:
                last_error = e
                print(f"ATTEMPT {attempt} FAILED: {e}")

            finally:
                try:
                    self._run("close")
                except Exception:
                    pass

        raise RuntimeError(
            f"AgentBrowserAssetResolver gagal setelah "
            f"{self.attempts} attempt: {last_error}"
        )

    def resolve_spec_assets(self, page_url: str) -> List[str]:
        """
        Ambil asset image yang namanya mengandung indikasi spesifikasi.
        """
        images = self.resolve_images(page_url)

        keywords = (
            "spek",
            "spec",
            "spesifikasi",
            "specification",
        )

        return [
            url
            for url in images
            if any(keyword in url.lower() for keyword in keywords)
        ]


    def ocr_asset_paddle(
        self,
        asset_bytes: bytes,
        asset_type: str = "UNKNOWN",
    ) -> dict:
        """
        OCR adapter untuk asset image.

        Graph tidak dipaksa masuk OCR.
        Datasheet/drawing/unknown menggunakan PaddleOCR.
        """
        import io
        import numpy as np
        from PIL import Image
        from paddleocr import PaddleOCR

        if asset_type in (
            "FREQUENCY_GRAPH",
            "IMPEDANCE_GRAPH",
        ):
            return {
                "asset_type": asset_type,
                "ocr_applicable": False,
                "texts": [],
                "scores": [],
            }

        image = Image.open(io.BytesIO(asset_bytes)).convert("RGB")
        image = np.asarray(image)

        ocr = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

        result = ocr.predict(image)

        if not result:
            return {
                "asset_type": asset_type,
                "ocr_applicable": True,
                "texts": [],
                "scores": [],
            }

        item = result[0]

        texts = list(item["rec_texts"] or [])
        scores = list(item["rec_scores"] or [])

        return {
            "asset_type": asset_type,
            "ocr_applicable": True,
            "texts": texts,
            "scores": scores,
        }


    def processing_strategy(self, asset_type: str) -> str:
        """
        Menentukan jalur pemrosesan berdasarkan tipe asset.

        Classification dan processing strategy sengaja dipisahkan:
        classifier menentukan APA asset-nya,
        strategy menentukan BAGAIMANA asset diproses.
        """
        strategies = {
            "DATASHEET": "ocr_extract",
            "TECHNICAL_DRAWING": "visual_geometry",
            "FREQUENCY_GRAPH": "graph_analysis",
            "IMPEDANCE_GRAPH": "graph_analysis",
            "UNKNOWN": "skip",
        }

        return strategies.get(asset_type, "skip")

    def ocr_asset(self, asset_bytes: bytes, timeout: int = 30) -> str:
        """
        OCR asset image yang sudah berhasil di-fetch.

        Resolver hanya menyediakan bytes.
        OCR tetap optional dan tidak mengubah fetch_asset().
        """
        import os
        import subprocess
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".png")

        try:
            with os.fdopen(fd, "wb") as f:
                f.write(asset_bytes)

            result = subprocess.run(
                ["tesseract", path, "stdout", "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode != 0:
                return ""

            return result.stdout.strip()

        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


    def ocr_asset_best(self, asset_bytes: bytes, timeout: int = 30) -> str:
        """
        OCR dengan beberapa PSM.
        Mengembalikan kandidat dengan skor kualitas tertinggi.

        Tidak mengubah fetch_asset() atau API existing.
        """
        import os
        import re
        import subprocess
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".png")

        try:
            with os.fdopen(fd, "wb") as f:
                f.write(asset_bytes)

            candidates = []

            for psm in (3, 6, 11, 12):
                try:
                    result = subprocess.run(
                        [
                            "tesseract",
                            path,
                            "stdout",
                            "--psm",
                            str(psm),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )

                    if result.returncode != 0:
                        continue

                    text = result.stdout.strip()

                    if not text:
                        continue

                    # Heuristic sederhana:
                    # - panjang text
                    # - angka
                    # - token yang terlihat seperti unit/label teknis
                    alnum = sum(c.isalnum() for c in text)
                    digits = sum(c.isdigit() for c in text)
                    words = len(re.findall(r"\b[A-Za-z]{2,}\b", text))
                    noise = sum(
                        1 for c in text
                        if c in "{}[]|<>~^*_+=\\"
                    )

                    score = (
                        min(len(text), 1200)
                        + (digits * 2)
                        + (words * 3)
                        - (noise * 4)
                    )

                    candidates.append((score, psm, text))

                except subprocess.TimeoutExpired:
                    continue

            if not candidates:
                return ""

            candidates.sort(reverse=True, key=lambda x: x[0])

            return candidates[0][2]

        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


    def classify_ocr_quality(self, text: str) -> str:
        """
        Generic OCR quality classifier.

        Tidak bergantung pada domain atau vocabulary tertentu.
        Hanya menilai struktur umum hasil OCR.
        """
        import re

        if not text or not text.strip():
            return "unusable"

        words = re.findall(r"\b[A-Za-z]{2,}\b", text)
        numbers = re.findall(r"\b\d+(?:[.,]\d+)?\b", text)

        chars = len(text)
        alnum = sum(c.isalnum() for c in text)
        alnum_ratio = alnum / max(chars, 1)

        garbage = sum(
            1
            for c in text
            if c in "{}[]|<>~^*_+=\\"
        )

        if chars < 30:
            return "unusable"

        if (
            len(words) >= 8
            and len(numbers) >= 4
            and alnum_ratio >= 0.55
            and garbage / max(chars, 1) < 0.08
        ):
            return "reliable"

        if (
            len(words) >= 2
            or len(numbers) >= 2
        ):
            return "weak"

        return "unusable"

    def classify_asset(self, url: str) -> str:
        """
        Classify asset berdasarkan sinyal filename/URL.

        Classification hanya menentukan jalur pemrosesan.
        Tidak menentukan apakah OCR benar atau tidak.
        """
        name = url.lower()

        graph_keywords = (
            "frekuensi",
            "frequency",
            "response",
            "impedansi",
            "impedance",
        )

        drawing_keywords = (
            "gambar-kerja",
            "drawing",
            "dimension",
            "dimensi",
        )

        datasheet_keywords = (
            "spek",
            "spec",
            "spesifikasi",
            "specification",
            "datasheet",
            "technical",
        )

        if any(k in name for k in graph_keywords):
            if "imped" in name or "impedance" in name:
                return "IMPEDANCE_GRAPH"
            return "FREQUENCY_GRAPH"

        if any(k in name for k in drawing_keywords):
            return "TECHNICAL_DRAWING"

        if any(k in name for k in datasheet_keywords):
            return "DATASHEET"

        return "UNKNOWN"


    def fetch_spec_assets(self, page_url: str) -> dict[str, bytes]:
        """
        Resolve dan fetch seluruh spec asset dalam satu browser session.

        Lifecycle:
            open product -> extract -> fetch assets -> close

        Tidak mengubah resolve_spec_assets() API.
        """
        with AgentBrowserAssetResolver._GLOBAL_BROWSER_LOCK:
            try:
                self._open_with_retry(page_url)

                output = self._run(
                    "eval",
                    'JSON.stringify([...document.images].map(x => x.src))'
                )

                images = json.loads(output)

                if isinstance(images, str):
                    images = json.loads(images)

                if not isinstance(images, list):
                    raise RuntimeError(
                        f"eval returned JSON bukan list: {type(images).__name__}"
                    )

                keywords = (
                    "spek",
                    "spec",
                    "spesifikasi",
                    "specification",
                    "gambar-kerja",
                    "frekuensi",
                    "impedansi",
                )

                spec_urls = [
                    url
                    for url in images
                    if isinstance(url, str)
                    and url.startswith(("http://", "https://"))
                    and any(keyword in url.lower() for keyword in keywords)
                ]

                assets = {}

                for url in spec_urls:
                    assets[url] = self.fetch_asset(url)

                return assets

            finally:
                try:
                    self._run("close")
                except Exception:
                    pass


    def fetch_asset(self, asset_url: str) -> bytes:
        """
        Fetch asset melalui browser-context fetch().

        Context harus sudah berada di product page JIC.
        Tidak melakukan Page.navigate/open() ke asset.
        """
        import base64

        expression = (
            "fetch("
            + json.dumps(asset_url)
            + ").then(async r => {"
            + "if (!r.ok) throw new Error('HTTP ' + r.status);"
            + "const b = await r.arrayBuffer();"
            + "let binary = '';"
            + "const bytes = new Uint8Array(b);"
            + "const chunk = 0x8000;"
            + "for (let i = 0; i < bytes.length; i += chunk) {"
            + "binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + chunk, bytes.length)));"
            + "}"
            + "return btoa(binary);"
            + "})"
        )

        output = self._run("eval", expression)

        try:
            encoded = json.loads(output)
        except json.JSONDecodeError:
            encoded = output

        if not isinstance(encoded, str):
            raise RuntimeError(
                f"browser fetch returned {type(encoded).__name__}, "
                "bukan base64 string"
            )

        try:
            return base64.b64decode(encoded, validate=True)
        except Exception as e:
            raise RuntimeError(
                f"invalid browser asset base64: {e}"
            ) from e

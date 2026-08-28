import os
from playwright.sync_api import sync_playwright


class BrowserTool:
    """Browser automation untuk fetch konten yang butuh login/JavaScript."""

    PROFILE_DIR = os.path.expanduser("~/research-assistant/browser_profiles")

    def __init__(self):
        self.profiles = {
            "default": os.path.join(self.PROFILE_DIR, "default"),
            "github": os.path.join(self.PROFILE_DIR, "github"),
            "reddit": os.path.join(self.PROFILE_DIR, "reddit"),
            "youtube": os.path.join(self.PROFILE_DIR, "youtube"),
        }
        # Pastikan folder profil ada
        for p in self.profiles.values():
            os.makedirs(p, exist_ok=True)

    def fetch(self, url: str, profile: str = "default") -> str:
        """Buka URL, ambil konten halaman (read-only)."""
        profile_dir = self.profiles.get(profile, self.profiles["default"])

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                profile_dir,
                headless=True,
                args=["--no-sandbox"]
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                # Tunggu konten utama
                page.wait_for_timeout(2000)

                # Ambil teks dari body
                body = page.locator("body")
                text = body.inner_text()
                context.close()
                return text[:3000] if text else "Tidak ada konten"
            except Exception as e:
                context.close()
                return f"Error: {e}"

    def fetch_with_screenshot(self, url: str, profile: str = "default") -> dict:
        """Buka URL, ambil teks + screenshot (untuk debugging)."""
        profile_dir = self.profiles.get(profile, self.profiles["default"])

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                profile_dir,
                headless=True,
                args=["--no-sandbox"]
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)

                text = page.locator("body").inner_text()
                screenshot_path = f"/tmp/screenshot_{hash(url) % 10000}.png"
                page.screenshot(path=screenshot_path)

                context.close()
                return {
                    "text": text[:3000] if text else "",
                    "screenshot": screenshot_path
                }
            except Exception as e:
                context.close()
                return {"text": f"Error: {e}", "screenshot": None}

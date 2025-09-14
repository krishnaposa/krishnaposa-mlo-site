import sys, re, json, asyncio
from playwright.async_api import async_playwright

ZILLOW_URL = "https://www.zillow.com/rental-manager/price-my-rental/"

async def run(address: str):
    print("[INFO] Starting Zillow rent estimate script...")
    async with async_playwright() as p:
        print("[INFO] Launching Chromium browser...")
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width":1280,"height":900})
        page = await context.new_page()

        print(f"[INFO] Navigating to {ZILLOW_URL}")
        await page.goto(ZILLOW_URL, wait_until="domcontentloaded")

        print("[INFO] Typing address into search box...")
        addr_input = page.get_by_role("textbox").first
        await addr_input.fill(address)
        await page.keyboard.press("Enter")

        print("[INFO] Waiting for page to load after entering address...")
        await page.wait_for_load_state("networkidle")

        print("[INFO] Checking for 'Continue' or 'Next' buttons...")
        for label in ["Continue","Next","Get started","Let’s go","Let's go"]:
            btns = page.get_by_role("button", name=label)
            if await btns.count():
                print(f"[INFO] Found button '{label}', clicking it...")
                try:
                    await btns.first.click()
                    await page.wait_for_load_state("networkidle")
                except Exception as e:
                    print(f"[WARN] Could not click '{label}': {e}")

        print("[INFO] Collecting all text from the page...")
        text_handles = await page.locator("body *").all_text_contents()

        print("[INFO] Searching for estimated rent text...")
        estimate = None
        for t in text_handles:
            if "month" in t.lower() or "/mo" in t.lower() or "per month" in t.lower():
                m = re.search(r"\$\s?\d[\d,]*", t)
                if m:
                    estimate = m.group(0).replace(" ", "")
                    print(f"[DEBUG] Found rent candidate: {estimate} in text: {t}")
                    break

        if not estimate:
            print("[INFO] No estimate found yet, scanning for any large dollar amount...")
            for t in text_handles:
                m = re.search(r"\$\s?\d[\d,]{3,}", t)
                if m:
                    estimate = m.group(0).replace(" ", "")
                    print(f"[DEBUG] Fallback rent candidate: {estimate} in text: {t}")
                    break

        chosen_address = None
        print("[INFO] Trying to locate the Zillow-confirmed address...")
        for t in text_handles:
            if "United States" in t or "," in t:
                if address.split()[0].lower()[:3] in t.lower():
                    chosen_address = t.strip()
                    print(f"[DEBUG] Matched confirmed address text: {chosen_address}")
                    break

        print("[INFO] Taking screenshot for debugging (zillow_result.png)...")
        await page.screenshot(path="zillow_result.png", full_page=True)

        result = {
            "input_address": address,
            "zillow_address_text": chosen_address,
            "estimated_rent": estimate,
            "screenshot": "zillow_result.png"
        }

        print("[INFO] Finished. Outputting JSON result below:\n")
        print(json.dumps(result, indent=2))

        await context.close()
        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python zillow_rent_estimate.py '123 Main St, Alpharetta, GA 30004'")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
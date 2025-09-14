import sys, re, json, asyncio
from playwright.async_api import async_playwright

ZILLOW_URL = "https://www.zillow.com/rental-manager/price-my-rental/"

async def run(address: str):
    async with async_playwright() as p:
        # Use headed mode to avoid some bot challenges and let you solve any CAPTCHA if shown
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width":1280,"height":900})
        page = await context.new_page()
        await page.goto(ZILLOW_URL, wait_until="domcontentloaded")

        # Type the address into the main input (use role+placeholder to be resilient)
        # If the selector ever changes, open devtools and adjust the get_by_* calls.
        addr_input = page.get_by_role("textbox").first
        await addr_input.fill(address)
        # Often there is an autocomplete dropdown; press Enter to accept top suggestion
        await page.keyboard.press("Enter")

        # Wait for navigation/results area to load
        # We don’t rely on exact selectors—look for any element containing a $-per-month phrase.
        await page.wait_for_load_state("networkidle")

        # If an interstitial or ZIP step appears, try clicking first visible button labeled Continue/Next
        for label in ["Continue","Next","Get started","Let’s go","Let's go"]:
            btns = page.get_by_role("button", name=label)
            if await btns.count():
                try:
                    await btns.first.click()
                    await page.wait_for_load_state("networkidle")
                except:
                    pass

        # Heuristic: find a block that looks like a monthly rent number
        text_handles = await page.locator("body *").all_text_contents()
        estimate = None
        for t in text_handles:
            if "month" in t.lower() or "/mo" in t.lower() or "per month" in t.lower():
                m = re.search(r"\$\s?\d[\d,]*", t)
                if m:
                    estimate = m.group(0).replace(" ", "")
                    break

        # As a fallback, scan all text for a big dollar number
        if not estimate:
            for t in text_handles:
                m = re.search(r"\$\s?\d[\d,]{3,}", t)
                if m:
                    estimate = m.group(0).replace(" ", "")
                    break

        # Try to capture an address confirmation shown by Zillow
        chosen_address = None
        for t in text_handles:
            if "United States" in t or "," in t:
                # crude heuristic: the typed address (with city/state) often reappears
                if address.split()[0].lower()[:3] in t.lower():
                    chosen_address = t.strip()
                    break

        # Screenshot for debugging
        await page.screenshot(path="zillow_result.png", full_page=True)

        print(json.dumps({
            "input_address": address,
            "zillow_address_text": chosen_address,
            "estimated_rent": estimate,
            "screenshot": "zillow_result.png"
        }, indent=2))

        await context.close()
        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python zillow_rent_estimate.py '123 Main St, Alpharetta, GA 30004'")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
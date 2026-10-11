import asyncio
import logging
import os
import re

import discord
from discord.ext import commands
from playwright.async_api import async_playwright

TOKEN = os.getenv("DISCORD_TOKEN")

PRO_CHANNEL_ID = 1556478983049187378
DEAL_CHANNEL_ID = 1556484507366850652

SCAN_INTERVAL = 120
REGULAR_DELAY = 600
MIN_DISCOUNT = 20

FANATICS_URL = "https://www.fanaticscollect.com/vault-marketplace?type=FIXED"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

scanner_task = None
seen_urls = set()


def parse_prices(text):
    listing_price = None
    guide_price = None

    listing_match = re.search(
        r"(?:Good Deal|Great Deal)\s*\$([\d,]+(?:\.\d{2})?)",
        text,
        re.IGNORECASE,
    )

    guide_match = re.search(
        r"Guide Price by Card Ladder.{0,200}?\$([\d,]+(?:\.\d{2})?)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if listing_match:
        listing_price = float(listing_match.group(1).replace(",", ""))

    if guide_match:
        guide_price = float(guide_match.group(1).replace(",", ""))

    return listing_price, guide_price


async def send_deal(title, price, guide, discount, url):
    pro_channel = bot.get_channel(PRO_CHANNEL_ID)
    deal_channel = bot.get_channel(DEAL_CHANNEL_ID)

    if pro_channel is None or deal_channel is None:
        logging.error("A Discord channel could not be found.")
        return

    message = (
        "**CardAI Deal Alert**\n"
        f"**Card:** {title}\n"
        f"**Listing price:** ${price:,.2f}\n"
        f"**Guide price:** ${guide:,.2f}\n"
        f"**Below guide:** {discount:.1f}%\n"
        f"[View Listing]({url})"
    )

    try:
        await pro_channel.send(message)
        logging.info("Deal sent to Pro channel: %s", title)
    except discord.DiscordException:
        logging.exception("Could not send deal to Pro channel.")
        return

    await asyncio.sleep(REGULAR_DELAY)

    try:
        await deal_channel.send(message)
        logging.info("Deal sent to regular channel after 10 minutes.")
    except discord.DiscordException:
        logging.exception("Could not send deal to regular channel.")


async def scan_fanatics():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        try:
            page = await browser.new_page()
            response = await page.goto(
                FANATICS_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response is None or response.status >= 400:
                logging.warning("Fanatics page did not load successfully.")
                return

            await page.wait_for_timeout(3000)

            links = await page.locator("a[href]").evaluate_all(
                """elements => elements.map(a => ({
                    href: a.href,
                    text: (a.innerText || "").trim()
                }))"""
            )

            candidates = []
            for item in links:
                href = item["href"]
                title = item["text"]

                if (
                    "pokemon" in title.lower()
                    and href.startswith("https://")
                    and "fanaticscollect.com" in href
                    and href not in seen_urls
                ):
                    if not any(x["href"] == href for x in candidates):
                        candidates.append(item)

            logging.info(
                "Fanatics loaded. Pokemon candidates: %s",
                len(candidates),
            )

            for item in candidates[:10]:
                detail_page = await browser.new_page()

                try:
                    detail_response = await detail_page.goto(
                        item["href"],
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )

                    if (
                        detail_response is None
                        or detail_response.status >= 400
                    ):
                        continue

                    await detail_page.wait_for_timeout(2000)
                    text = await detail_page.locator("body").inner_text()

                    title = (await detail_page.title()).strip()
                    price, guide = parse_prices(text)

                    if price is None or guide is None or guide <= 0:
                        logging.info(
                            "Could not verify prices for: %s",
                            title,
                        )
                        continue

                    discount = ((guide - price) / guide) * 100
                    seen_urls.add(item["href"])

                    logging.info(
                        "Checked %s: price=$%.2f guide=$%.2f discount=%.1f%%",
                        title,
                        price,
                        guide,
                        discount,
                    )

                    if discount >= MIN_DISCOUNT:
                        asyncio.create_task(
                            send_deal(
                                title,
                                price,
                                guide,
                                discount,
                                item["href"],
                            )
                        )

                except Exception:
                    logging.exception("Could not check a listing.")
                finally:
                    await detail_page.close()

        finally:
            await browser.close()


async def scanner_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            logging.info("Scanning Fanatics...")
            await scan_fanatics()
        except Exception:
            logging.exception("Scanner error.")

        await asyncio.sleep(SCAN_INTERVAL)


@bot.event
async def on_ready():
    global scanner_task

    logging.info("CardAI is online as %s", bot.user)
    logging.info("Scan interval: %s seconds", SCAN_INTERVAL)
    logging.info("Minimum discount: %s%%", MIN_DISCOUNT)
    logging.info("Regular channel delay: %s seconds", REGULAR_DELAY)

    if scanner_task is None or scanner_task.done():
        scanner_task = asyncio.create_task(scanner_loop())


@bot.command()
async def status(ctx):
    await ctx.send(
        "CardAI is online. Scans every 2 minutes. "
        "Minimum discount: 20 percent."
    )


async def main():
    if not TOKEN:
        raise RuntimeError(
            "Missing DISCORD_TOKEN environment variable."
        )

    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

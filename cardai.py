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

SCAN_INTERVAL = 30
MIN_DISCOUNT = 20
FREE_DELAY = 600

FANATICS_URL = (
    "https://www.fanaticscollect.com/vault-marketplace?type=FIXED"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

seen_urls = set()
pending_urls = set()


def extract_price(text):
    matches = re.findall(
        r"\$\s*([\d,]+(?:\.\d{1,2})?)",
        text,
    )
    return [float(value.replace(",", "")) for value in matches]


def find_discount(price, market_value):
    if market_value <= 0:
        return 0
    return (market_value - price) / market_value * 100


async def scan_fanatics():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
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
                """els => els.map(a => ({
                    href: a.href,
                    text: (a.innerText || "").trim()
                }))"""
            )

            pokemon_links = []
            for item in links:
                text = item["text"]
                url = item["href"]

                if (
                    "pokemon" in text.lower()
                    and url.startswith("https://")
                    and url not in seen_urls
                ):
                    pokemon_links.append(item)

            logging.info(
                "Fanatics loaded. Found %s new Pokemon links.",
                len(pokemon_links),
            )

            for item in pokemon_links:
                url = item["href"]

                if url in pending_urls:
                    continue

                try:
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    await page.wait_for_timeout(1000)

                    text = await page.locator("body").inner_text()
                    prices = extract_price(text)

                    logging.info(
                        "Listing checked: %s | Prices found: %s",
                        item["text"][:100],
                        prices[:8],
                    )

                    seen_urls.add(url)

                except Exception as exc:
                    logging.warning(
                        "Could not inspect listing: %s",
                        str(exc)[:200],
                    )

        finally:
            await browser.close()


@bot.event
async def on_ready():
    logging.info("CardAI is online as %s", bot.user)
    logging.info("Scanner interval: %s seconds", SCAN_INTERVAL)
    logging.info("Minimum discount: %s%%", MIN_DISCOUNT)

    if not getattr(bot, "scanner_started", False):
        bot.scanner_started = True
        bot.loop.create_task(scanner_loop())


async def scanner_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            await scan_fanatics()
        except Exception:
            logging.exception("Scanner encountered an error.")

        await asyncio.sleep(SCAN_INTERVAL)


@bot.command()
async def status(ctx):
    await ctx.send(
        "CardAI is online. Fanatics scan interval: 30 seconds."
    )


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable.")

bot.run(TOKEN)

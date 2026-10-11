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

FANATICS_URL = "https://www.fanaticscollect.com/vault-marketplace?type=FIXED"

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


async def scan_fanatics():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            response = await page.goto(
                FANATICS_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response is None or response.status >= 400:
                logging.warning("Fanatics page failed to load.")
                return

            await page.wait_for_timeout(3000)

            links = await page.locator("a[href]").evaluate_all(
                """elements => elements.map(a => ({
                    href: a.href,
                    text: (a.innerText || "").trim()
                }))"""
            )

            pokemon_links = [
                item for item in links
                if "pokemon" in item["text"].lower()
                and item["href"].startswith("https://")
            ]

            logging.info(
                "Fanatics loaded. Pokemon links found: %s",
                len(pokemon_links),
            )

        finally:
            await browser.close()


@bot.event
async def on_ready():
    logging.info("CardAI is online as %s", bot.user)


@bot.command()
async def status(ctx):
    await ctx.send("CardAI is online. Scanner interval: 30 seconds.")


async def scanner_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            await scan_fanatics()
        except Exception:
            logging.exception("Scanner error.")

        await asyncio.sleep(SCAN_INTERVAL)


async def main():
    if not TOKEN:
        raise RuntimeError("Missing DISCORD_TOKEN environment variable.")

    async with bot:
        bot.loop.create_task(scanner_loop())
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

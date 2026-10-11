import asyncio
import logging
import os

import discord
from discord.ext import commands
from playwright.async_api import async_playwright

TOKEN = os.getenv("DISCORD_TOKEN")
SCAN_INTERVAL = 120
FANATICS_URL = "https://www.fanaticscollect.com/vault-marketplace?type=FIXED"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
scanner_task = None


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
            pokemon_links = [
                item for item in links
                if "pokemon" in item["text"].lower()
                and item["href"].startswith("https://")
            ]
            logging.info("Fanatics loaded. Pokemon links found: %s", len(pokemon_links))
            for item in pokemon_links[:10]:
                logging.info("Listing candidate: %s | %s", item["text"][:100], item["href"])
        finally:
            await browser.close()


async def scanner_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await scan_fanatics()
        except Exception:
            logging.exception("Scanner error.")
        await asyncio.sleep(SCAN_INTERVAL)


@bot.event
async def on_ready():
    global scanner_task
    logging.info("CardAI is online as %s", bot.user)
    logging.info("Scanner interval: %s seconds", SCAN_INTERVAL)
    if scanner_task is None or scanner_task.done():
        scanner_task = asyncio.create_task(scanner_loop())


@bot.command()
async def status(ctx):
    await ctx.send("CardAI is online. Fanatics scan interval: 30 seconds.")


async def main():
    if not TOKEN:
        raise RuntimeError("Missing DISCORD_TOKEN environment variable.")
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

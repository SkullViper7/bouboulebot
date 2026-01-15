import discord
from discord.ext import commands
import aiohttp
import random
import os
from flask import Flask
from threading import Thread
from dotenv import load_dotenv

# 1. Chargement des secrets
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GIPHY_TOKEN = os.getenv("GIPHY_KEY")

# 2. Serveur Web fictif pour maintenir le bot en vie
app = Flask('')
@app.route('/')
def home():
    return "Bot en ligne !"

def run_web():
    app.run(host='0.0.0.0', port=os.getenv("PORT", 8080))

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# 3. Configuration du Bot Discord
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def get_giphy_gif(search_term):
    url = "https://api.giphy.com/v1/gifs/search"
    params = {
        "api_key": GIPHY_TOKEN,
        "q": search_term,
        "limit": 10,
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data['data']:
                    gif_data = random.choice(data['data'])
                    return gif_data['images']['original']['url']
            return None

@bot.command()
async def shit(ctx, membre: discord.Member):
    gif_url = await get_giphy_gif("pooping")
    if gif_url:
        await ctx.send(f"Bouboule a chié sur {membre.mention} !")
        await ctx.send(gif_url) # Discord intègre automatiquement le lien
    else:
        await ctx.send("Pas de chiasse pour cette fois...")

# 4. Lancement
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
import discord
from discord.ext import commands
import aiohttp
import random
import os
from flask import Flask
from threading import Thread
from dotenv import load_dotenv
from keep_alive import keep_alive

const express = require('express');
const app = express();
const port = process.env.PORT || 3000;

app.get('/', (req, res) => {
  res.send('Le bot est en ligne !');
});

app.listen(port, () => {
  console.log(`Serveur web lancé sur le port ${port}`);
});

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

async def get_giphy_gif(tag_term):
    """Cherche un GIF UNIQUE et ALÉATOIRE sur Giphy via l'endpoint random"""
    url = "https://api.giphy.com/v1/gifs/random"
    params = {
        "api_key": GIPHY_TOKEN,
        "tag": tag_term, # On utilise 'tag' au lieu de 'q'
        "limit": 100,    # Limitation de 100 GIFs par requête
        "rating": "r"    # Pour garder le contenu non filtré comme demandé
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data['data']:
                    # L'endpoint random renvoie directement UN seul objet
                    return data['data']['images']['original']['url']
            return None

@bot.command()
async def shit(ctx, membre: discord.Member):
    gif_url = await get_giphy_gif("poop")
    if gif_url:
        await ctx.send(f"Bouboule a chié sur {membre.mention} !")
        await ctx.send(gif_url) # Discord intègre automatiquement le lien
    else:
        await ctx.send("Pas de chiasse pour cette fois...")

# 4. Lancement
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
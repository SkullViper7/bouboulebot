import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import aiohttp
import random
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Remplacez par votre clé Giphy
GIPHY_TOKEN = os.getenv("GIPHY_KEY")

async def get_giphy_gif(search_term):
    """Cherche un GIF sur Giphy et renvoie l'URL d'un résultat aléatoire"""
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
                    # On choisit un GIF au hasard dans les 10 résultats
                    gif_data = random.choice(data['data'])
                    return gif_data['images']['original']['url']
            return None

@bot.command()
async def shit(ctx, membre: discord.Member):
    """Commande !shit @pseudo pour chier sur un membre"""
    gif_url = await get_giphy_gif("pooping") # Mot-clé forcé pour cette commande
    
    if gif_url:
        # On mentionne l'auteur et la cible pour que tout le monde comprenne l'action
        await ctx.send(f"Bouboule a chié sur {membre.mention} !")
        await ctx.send(gif_url)
    else:
        await ctx.send("Pas de chiasse cette fois-ci...")

bot.run(os.getenv("DISCORD_TOKEN"))
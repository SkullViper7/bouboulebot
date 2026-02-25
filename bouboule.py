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

@bot.command()
async def crack(ctx, *, jeu: str):
    """Cherche un jeu sur Online-fix et FreeTP"""
    await ctx.send(f"🔍 Je cherche **{jeu}** sur les réseaux russes... (ça peut prendre 2-3 sec)")

    # 1. Préparer les URLS de recherche
    query = urllib.parse.quote(jeu) # Transforme "Call of Duty" en "Call%20of%20Duty"
    
    # URLS de recherche directe (marche toujours)
    url_onlinefix = f"https://online-fix.me/index.php?do=search&subaction=search&story={query}"
    url_freetp = f"https://freetp.org/index.php?do=search&subaction=search&story={query}"

    # Headers pour faire croire qu'on est un vrai navigateur (Firefox)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0'
    }

    found_links = []

    async with aiohttp.ClientSession(headers=headers) as session:
        # --- RECHERCHE SUR ONLINE-FIX ---
        try:
            async with session.get(url_onlinefix) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    # Sélecteur spécifique à Online-fix (peut changer si le site change)
                    results = soup.select(".article-content h2 a") 
                    
                    for link in results[:3]: # On prend les 3 premiers
                        found_links.append(f"🏴‍☠️ [Online-Fix] {link.text} -> {link['href']}")
        except Exception as e:
            print(f"Erreur Online-fix: {e}")

        # --- RECHERCHE SUR FREETP ---
        try:
            async with session.get(url_freetp) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    # Sélecteur spécifique à FreeTP
                    results = soup.select(".entry-title a") 
                    
                    for link in results[:3]:
                        found_links.append(f"🎮 [FreeTP] {link.text} -> {link['href']}")
        except Exception as e:
            print(f"Erreur FreeTP: {e}")

    # --- CRÉATION DE LA RÉPONSE ---
    embed = discord.Embed(title=f"Résultats pour : {jeu}", color=discord.Color.dark_red())
    
    if found_links:
        description = "\n\n".join(found_links)
        embed.description = description
    else:
        embed.description = "Je n'ai pas réussi à extraire les liens précis (protection anti-bot ?)."

    # On ajoute toujours les liens de recherche globaux au cas où le bot n'a rien trouvé
    embed.add_field(name="Liens de recherche manuelle", value=f"[Voir sur Online-Fix]({url_onlinefix})\n[Voir sur FreeTP]({url_freetp})", inline=False)
    
    await ctx.send(embed=embed)

# 4. Lancement
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
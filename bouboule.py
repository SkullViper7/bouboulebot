import discord
from discord.ext import commands
import aiohttp
import random
import os
from flask import Flask
from threading import Thread
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import urllib.parse
from motor.motor_asyncio import AsyncIOMotorClient
import random
from collections import Counter
import json
import asyncio
import math
from collections import Counter
import time

#region Init
# 1. Chargement des secrets
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GIPHY_TOKEN = os.getenv("GIPHY_KEY")
MONGO_URI = os.getenv("MONGO_URI")

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["bouboule_cars"]
collection_inventaires = db["inventaires"]

with open('cars.json', 'r', encoding='utf-8') as f:
    VOITURES = json.load(f)

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
#endregion

# --- ÉCONOMIE ---
PRIX_REVENTE = {
    "Commune ⚪": 100,
    "Atypique 🟢": 200,
    "Rare 🔵": 500,
    "Épique 🟣": 1000,
    "Légendaire 🟡": 2500,
    "Mythique 🟣": 5000,
    "GOAT 👑": 20000
}

#region gifhy
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
#endregion

#region shit
@bot.command()
async def shit(ctx, membre: discord.Member):
    gif_url = await get_giphy_gif("poop")
    if gif_url:
        await ctx.send(f"Bouboule a chié sur {membre.mention} !")
        await ctx.send(gif_url) # Discord intègre automatiquement le lien
    else:
        await ctx.send("Pas de chiasse pour cette fois...")
#endregion

#region crack
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
#endregion

#region roll
@bot.command()
async def roll(ctx):
    user_id = str(ctx.author.id)
    maintenant = time.time()
    cooldown_secondes = 43200 # 12 heures

    # 1. Récupérer le profil du joueur
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    # 2. Vérifier le temps d'attente
    if profil and "last_roll" in profil:
        temps_ecoule = maintenant - profil["last_roll"]
        if temps_ecoule < cooldown_secondes:
            temps_restant = int(cooldown_secondes - temps_ecoule)
            heures = temps_restant // 3600
            minutes = (temps_restant % 3600) // 60
            await ctx.send(f"⏳ Doucement {ctx.author.mention} ! Ton prochain tirage est dispo dans **{heures}h et {minutes}m**.")
            return

    # 3. Filtrer les voitures possédées
    voitures_possedees = profil.get("garage", []) if profil else []
    voitures_disponibles = []
    poids_disponibles = []

    for voiture in VOITURES:
        nom_complet = f"{voiture['marque']} {voiture['nom']}"
        if nom_complet not in voitures_possedees:
            voitures_disponibles.append(voiture)
            poids_disponibles.append(voiture.get("poids", 10))

    if not voitures_disponibles:
        await ctx.send(f"🏆 Incroyable {ctx.author.mention}, tu possèdes déjà **TOUTES** les voitures du jeu ! Attends une mise à jour.")
        return

    # 4. Tirage de la voiture
    voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
    nom_complet_gagnee = f"{voiture_gagnee['marque']} {voiture_gagnee['nom']}"

    # --- NOUVEAU : CALCUL DU BONUS D'ARGENT ---
    rarete = voiture_gagnee['rareté']
    # On cherche le prix de base dans notre dictionnaire (50 par défaut si non trouvé)
    prix_base = PRIX_REVENTE.get(rarete, 50)
    
    # On calcule le bonus (ici 20%, soit 0.20. Tu peux changer ce chiffre !)
    bonus_coins = int(prix_base * 0.20) 

    # 5. Sauvegarder dans MongoDB (L'inventaire, l'heure ET l'argent !)
    await collection_inventaires.update_one(
        {"_id": user_id},
        {
            "$push": {"garage": nom_complet_gagnee},
            "$set": {"last_roll": maintenant},
            "$inc": {"coins": bonus_coins} # On ajoute l'argent gagné au solde
        },
        upsert=True
    )

    # 6. Création de l'Embed
    embed = discord.Embed(
        title=f"🎰 Tu as obtenu : {nom_complet_gagnee} !", 
        description=f"🎁 Bonus de tirage : **+{bonus_coins} 🪙** ajoutés à ton solde !",
        color=discord.Color.gold()
    )
    embed.set_image(url=voiture_gagnee['image'])
    
    total_poids = sum(poids_disponibles)
    chance_pourcent = (voiture_gagnee.get("poids", 10) / total_poids) * 100
    
    embed.set_footer(text=f"Rareté : {rarete} (Drop rate : {chance_pourcent:.1f}%) | Appartient à {ctx.author.display_name}")
    
    await ctx.send(embed=embed)

# --- Gestion de l'erreur si le joueur spam la commande ---
@roll.error
async def roll_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        minutes_restantes = int(error.retry_after // 60)
        await ctx.send(f"⏳ Doucement {ctx.author.mention} ! Ton prochain tirage est dispo dans **{minutes_restantes} minutes**.")
#endregion

#region garage
# 1. La Vue mise à jour avec le paramètre "solde"
class GaragePagination(discord.ui.View):
    def __init__(self, ctx, pages, total_voitures, target_member, solde): # <-- On ajoute 'solde' ici
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.total_voitures = total_voitures
        self.target_member = target_member
        self.solde = solde # <-- On le sauvegarde pour l'utiliser plus bas
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.bouton_prec.disabled = self.current_page == 0
        self.bouton_suiv.disabled = self.current_page == len(self.pages) - 1

    def get_embed(self):
        voiture_actuelle = self.pages[self.current_page]
        
        # On intègre le solde et la voiture dans la description
        description = f"**💳 Solde :** {self.solde} 🪙\n\n### {voiture_actuelle['nom_complet']}"
        
        if voiture_actuelle['quantite'] > 1:
            description += f" **(x{voiture_actuelle['quantite']})**"
            
        embed = discord.Embed(
            title=f"🚗 Le Garage de {self.target_member.display_name}", 
            description=description, 
            color=discord.Color.blue()
        )
        
        if voiture_actuelle['image']:
            embed.set_image(url=voiture_actuelle['image'])
            
        embed.add_field(name="Rareté", value=voiture_actuelle['rareté'])
        
        embed.set_footer(text=f"Modèle {self.current_page + 1}/{len(self.pages)} | Total : {self.total_voitures} voitures")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, custom_id="prec")
    async def bouton_prec(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("Ce n'est pas toi qui as demandé à voir ce garage !", ephemeral=True)
            return
            
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, custom_id="suiv")
    async def bouton_suiv(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("Ce n'est pas toi qui as demandé à voir ce garage !", ephemeral=True)
            return
            
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


# 2. La nouvelle commande !garage
@bot.command()
async def garage(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    user_id = str(cible.id)
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    # On récupère le solde du joueur (0 s'il n'a rien)
    solde = profil.get("coins", 0) if profil else 0
    
    # Modification ici : si le garage est vide, on affiche quand même un bel Embed avec son argent
    if not profil or not profil.get("garage"):
        embed_vide = discord.Embed(
            title=f"🚗 Le Garage de {cible.display_name}", 
            description=f"**💳 Solde :** {solde} 🪙\n\nCe garage est complètement vide pour le moment ! Fais un `!roll`.", 
            color=discord.Color.light_grey()
        )
        await ctx.send(embed=embed_vide)
        return
    
    mes_voitures = profil["garage"]
    inventaire_compte = Counter(mes_voitures)
    
    pages_voitures = []
    
    for nom_complet, quantite in inventaire_compte.items():
        voiture_info = next((v for v in VOITURES if f"{v['marque']} {v['nom']}" == nom_complet), None)
        
        if voiture_info:
            pages_voitures.append({
                "nom_complet": nom_complet,
                "quantite": quantite,
                "image": voiture_info["image"],
                "rareté": voiture_info["rareté"]
            })
        else:
            pages_voitures.append({
                "nom_complet": nom_complet,
                "quantite": quantite,
                "image": None,
                "rareté": "Inconnue (Supprimée du catalogue)"
            })
            
    # On passe le paramètre 'solde' à notre vue !
    view = GaragePagination(ctx, pages_voitures, len(mes_voitures), cible, solde)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region trade
@bot.command()
async def trade(ctx, membre: discord.Member, ma_voiture: str, sa_voiture: str):
    # On empêche de s'échanger à soi-même
    if ctx.author == membre:
        await ctx.send("Tu ne peux pas faire un échange avec toi-même !")
        return

    user_id = str(ctx.author.id)
    target_id = str(membre.id)

    # 1. Récupérer les profils dans la base de données
    profil_user = await collection_inventaires.find_one({"_id": user_id})
    profil_target = await collection_inventaires.find_one({"_id": target_id})

    # Vérifications de base (Est-ce qu'ils ont un garage ?)
    if not profil_user or ma_voiture not in profil_user.get("garage", []):
        await ctx.send(f"❌ Tu ne possèdes pas la voiture **{ma_voiture}** !")
        return
    if not profil_target or sa_voiture not in profil_target.get("garage", []):
        await ctx.send(f"❌ {membre.display_name} ne possède pas la voiture **{sa_voiture}** !")
        return

    # 2. Demander confirmation à l'autre joueur
    msg = await ctx.send(f"Hey {membre.mention} ! {ctx.author.mention} te propose d'échanger sa **{ma_voiture}** contre ta **{sa_voiture}**.\nRéagis avec ✅ pour accepter ou ❌ pour refuser.")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    # Fonction pour vérifier que c'est bien la bonne personne qui clique sur la réaction
    def check(reaction, user):
        return user == membre and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

    try:
        # On attend la réaction pendant 60 secondes
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
        
        if str(reaction.emoji) == "✅":
            # 3. L'échange est accepté, on modifie les inventaires en Python
            garage_user = profil_user["garage"]
            garage_target = profil_target["garage"]

            # On retire les voitures (une seule fois au cas où il y a des doublons)
            garage_user.remove(ma_voiture)
            garage_target.remove(sa_voiture)

            # On ajoute les nouvelles voitures
            garage_user.append(sa_voiture)
            garage_target.append(ma_voiture)

            # 4. On sauvegarde les nouveaux garages dans MongoDB
            await collection_inventaires.update_one({"_id": user_id}, {"$set": {"garage": garage_user}})
            await collection_inventaires.update_one({"_id": target_id}, {"$set": {"garage": garage_target}})

            await ctx.send(f"🎉 Échange réussi entre {ctx.author.mention} et {membre.mention} !")
        else:
            await ctx.send(f"❌ {membre.display_name} a refusé l'échange.")

    except asyncio.TimeoutError:
        await ctx.send(f"⏳ Temps écoulé, l'échange proposé par {ctx.author.mention} est annulé.")
#endregion

#region sell
@bot.command(aliases=["jeter", "poubelle", "vendre"])
async def sell(ctx, *, voiture_a_vendre: str):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})

    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est complètement vide, {ctx.author.mention} !")
        return

    garage = profil["garage"]

    if voiture_a_vendre not in garage:
        await ctx.send(f"❌ Tu ne possèdes pas la voiture **{voiture_a_vendre}** !")
        return

    # NOUVEAU : On cherche les infos de la voiture pour connaître sa rareté
    voiture_info = next((v for v in VOITURES if f"{v['marque']} {v['nom']}" == voiture_a_vendre), None)
    
    if not voiture_info:
        await ctx.send("❌ Erreur : Cette voiture n'existe plus dans le catalogue.")
        return
        
    rarete = voiture_info["rareté"]
    # On va chercher le prix dans notre dictionnaire (50 par défaut s'il ne trouve pas la rareté)
    prix_vente = PRIX_REVENTE.get(rarete, 50)

    # On modifie le message pour afficher le prix
    msg = await ctx.send(f"⚠️ {ctx.author.mention}, veux-tu vendre ta **{voiture_a_vendre}** ?\nLe concessionnaire t'en offre **{prix_vente} 🪙**.\n\n*Réagis avec ✅ pour vendre ou ❌ pour annuler.*")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=30.0, check=check)
        
        if str(reaction.emoji) == "✅":
            garage.remove(voiture_a_vendre)

            # On met à jour le garage ET on ajoute les pièces
            await collection_inventaires.update_one(
                {"_id": user_id},
                {
                    "$set": {"garage": garage},
                    "$inc": {"coins": prix_vente}
                }
            )

            await ctx.send(f"💵 Vente conclue {ctx.author.mention} ! Tu as gagné **{prix_vente} 🪙** en vendant ta {voiture_a_vendre}.")
        else:
            await ctx.send(f"❌ Vente annulée. Tu gardes ta **{voiture_a_vendre}**.")

    except asyncio.TimeoutError:
        await ctx.send(f"⏳ Temps écoulé, la vente est annulée.")
#endregion

#region search
@bot.command()
async def search(ctx, *, recherche: str):
    # On met tout en minuscules pour faciliter la recherche (insensible à la casse)
    recherche_lower = recherche.lower()

    # 1. Vérifier si c'est une MARQUE
    # On cherche toutes les voitures dont la marque correspond exactement
    voitures_marque = [v for v in VOITURES if v["marque"].lower() == recherche_lower]
    
    if voitures_marque:
        # Si on a trouvé des voitures pour cette marque, on crée une liste
        description = ""
        for v in voitures_marque:
            description += f"• **{v['nom']}** ({v['rareté']})\n"
        
        embed = discord.Embed(
            title=f"🏢 Modèles disponibles chez {voitures_marque[0]['marque']}", 
            description=description, 
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return # On arrête la commande ici puisque c'était une marque

    # 2. Vérifier si c'est un MODÈLE
    # On cherche le premier modèle dont le nom contient ce que l'utilisateur a tapé
    modele_trouve = next((v for v in VOITURES if recherche_lower in v["nom"].lower()), None)

    if modele_trouve:
        # Le nom exact tel qu'il est sauvegardé dans la base de données
        nom_complet = f"{modele_trouve['marque']} {modele_trouve['nom']}"
        
        # On demande à MongoDB de trouver tous les joueurs qui ont ce nom exact dans leur liste "garage"
        curseur = collection_inventaires.find({"garage": nom_complet})
        docs = await curseur.to_list(length=100) # On limite à 100 au cas où tout le serveur l'aurait
        
        proprietaires_mentions = []
        for doc in docs:
            # En Discord, écrire <@ID_DU_JOUEUR> affiche directement sa mention/son pseudo !
            proprietaires_mentions.append(f"<@{doc['_id']}>")

        # On formate le texte des propriétaires
        if proprietaires_mentions:
            texte_proprietaires = ", ".join(proprietaires_mentions)
        else:
            texte_proprietaires = "Personne ne possède ce bijou pour le moment... 😢"

        # On crée l'Embed final pour la voiture
        embed = discord.Embed(
            title=f"🔍 {nom_complet}", 
            color=discord.Color.green()
        )
        embed.set_image(url=modele_trouve['image'])
        embed.add_field(name="Rareté", value=modele_trouve['rareté'], inline=True)
        embed.add_field(name="Propriétaires", value=texte_proprietaires, inline=False)
        
        await ctx.send(embed=embed)
        return

    # 3. Si la recherche n'a rien donné du tout
    await ctx.send(f"❌ Je n'ai trouvé aucune marque ni aucun modèle correspondant à **{recherche}** dans le catalogue.")
#endregion

#region catalogue
# 1. La Vue (View) pour les boutons du catalogue
class CataloguePagination(discord.ui.View):
    def __init__(self, ctx, pages):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        # Désactive le bouton Précédent sur la première page, et Suivant sur la dernière
        self.bouton_prec.disabled = self.current_page == 0
        self.bouton_suiv.disabled = self.current_page == len(self.pages) - 1

    def get_embed(self):
        embed = discord.Embed(
            title="📖 Catalogue officiel du Garage", 
            description=self.pages[self.current_page], 
            color=discord.Color.dark_theme()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} | Total : {len(VOITURES)} modèles disponibles")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, custom_id="cat_prec")
    async def bouton_prec(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, custom_id="cat_suiv")
    async def bouton_suiv(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


# 2. La commande pour lancer le catalogue
@bot.command(aliases=["catalog", "liste", "voitures"])
async def catalogue(ctx):
    if not VOITURES:
        await ctx.send("Le catalogue est vide pour le moment !")
        return

    # On trie les voitures par Marque, puis par Nom (ordre alphabétique)
    voitures_triees = sorted(VOITURES, key=lambda x: (x['marque'], x['nom']))
    
    lignes_catalogue = []
    for v in voitures_triees:
        # Format de l'affichage : **Renault** Twingo 1 - Commun ⚪
        lignes_catalogue.append(f"**{v['marque']}** {v['nom']} - *{v['rareté']}*")

    # On découpe en pages de 15 voitures
    lignes_par_page = 15
    pages = []
    for i in range(0, len(lignes_catalogue), lignes_par_page):
        morceau = "\n".join(lignes_catalogue[i:i + lignes_par_page])
        pages.append(morceau)
        
    # On envoie le message avec les boutons
    view = CataloguePagination(ctx, pages)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region commandes
@bot.command(aliases=["commandes", "menu", "aide"])
async def cmd(ctx):
    embed = discord.Embed(
        title="🛠️ Liste des commandes de Bouboule",
        description="Voici tout ce que je peux faire pour l'instant :",
        color=discord.Color.blurple()
    )
    
    # --- Section Gacha / Voitures ---
    embed.add_field(
        name="🎰 `!roll`", 
        value="Tire une voiture au hasard pour l'ajouter à ton garage (1 fois par heure).", 
        inline=False
    )
    embed.add_field(
        name="🚗 `!garage [@pseudo]`", 
        value="Affiche ton garage. Tu peux mentionner quelqu'un pour voir le sien !", 
        inline=False
    )
    embed.add_field(
        name="🛒 `!sell [Ma voiture]`", 
        value="Vends ta voiture. *Pas de guillemets !*", 
        inline=False
    )
    embed.add_field(
        name="🤝 `!trade @pseudo \"Ma Voiture\" \"Sa Voiture\"`", 
        value="Propose un échange avec un joueur. *N'oublie pas les guillemets !*", 
        inline=False
    )
    embed.add_field(
        name="🔍 `!voiture [modèle ou marque]`", 
        value="Cherche une voiture pour voir à quoi elle ressemble et qui la possède. *(Alias: `!search`)*", 
        inline=False
    )
    embed.add_field(
        name="📖 `!catalogue`", 
        value="Affiche la liste complète de toutes les voitures disponibles dans le jeu. *(Alias: `!liste`)*", 
        inline=False
    )

    # --- Section Fun & Utilitaires (Tes anciennes commandes) ---
    embed.add_field(
        name="💩 `!shit @pseudo`", 
        value="Bouboule lâche une caisse sur la personne mentionnée avec un GIF aléatoire.", 
        inline=False
    )
    embed.add_field(
        name="🏴‍☠️ `!crack [nom du jeu]`", 
        value="Cherche un jeu cracké sur les réseaux russes (Online-fix / FreeTP).", 
        inline=False
    )
    
    embed.set_footer(text="Développé avec amour (et un peu de cambouis) ⚙️")
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None) # Ajoute la photo de profil de ton bot en haut à droite !

    await ctx.send(embed=embed)
#endregion

#region timer
@bot.command(aliases=["cd", "cooldown", "temps"])
async def timer(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil or "last_roll" not in profil:
        await ctx.send(f"✅ C'est bon {ctx.author.mention}, ton tirage est prêt ! Fais `!roll` pour tenter ta chance.")
        return

    maintenant = time.time()
    cooldown_secondes = 43200 # 12 heures en secondes
    temps_ecoule = maintenant - profil["last_roll"]
    
    if temps_ecoule < cooldown_secondes:
        temps_restant = int(cooldown_secondes - temps_ecoule)
        
        # Le calcul magique
        heures = temps_restant // 3600
        minutes = (temps_restant % 3600) // 60
        
        await ctx.send(f"⏳ Patience {ctx.author.mention} ! Ton prochain tirage sera disponible dans **{heures}h et {minutes}m**.")
    else:
        await ctx.send(f"✅ C'est bon {ctx.author.mention}, ton tirage est prêt ! Fais `!roll` pour tenter ta chance.")
#endregion

#region argent
@bot.command(aliases=["bal", "balance", "argent", "money"])
async def solde(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    profil = await collection_inventaires.find_one({"_id": str(cible.id)})
    
    # Si le joueur n'a pas de profil ou pas de pièces, il a 0
    coins = profil.get("coins", 0) if profil else 0
    await ctx.send(f"💳 Le solde de **{cible.display_name}** est de **{coins} 🪙**.")

@bot.command()
async def daily(ctx):
    user_id = str(ctx.author.id)
    maintenant = time.time()
    cooldown_daily = 86400 # 24 heures en secondes
    salaire = 500 # Le montant gagné chaque jour

    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if profil and "last_daily" in profil:
        temps_ecoule = maintenant - profil["last_daily"]
        if temps_ecoule < cooldown_daily:
            temps_restant = int(cooldown_daily - temps_ecoule)
            heures = temps_restant // 3600
            minutes = (temps_restant % 3600) // 60
            await ctx.send(f"⏳ Reviens demain {ctx.author.mention} ! Ton prochain salaire sera disponible dans **{heures}h et {minutes}m**.")
            return

    # On ajoute l'argent ($inc) et on met à jour l'heure du daily ($set)
    await collection_inventaires.update_one(
        {"_id": user_id},
        {
            "$inc": {"coins": salaire},
            "$set": {"last_daily": maintenant}
        },
        upsert=True
    )

    # On récupère le nouveau solde pour l'afficher
    nouveau_profil = await collection_inventaires.find_one({"_id": user_id})
    solde_actuel = nouveau_profil.get("coins", salaire)

    await ctx.send(f"💸 Bien joué {ctx.author.mention} ! Tu as récupéré ton salaire de **{salaire} 🪙**.\nTon nouveau solde est de **{solde_actuel} 🪙**.")
#endregion

#region buyroll
@bot.command()
async def buyroll(ctx):
    user_id = str(ctx.author.id)
    prix_roll = 1500 # Le prix que tu veux pour un tirage payant
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    solde = profil.get("coins", 0) if profil else 0
    
    if solde < prix_roll:
        await ctx.send(f"❌ Désolé {ctx.author.mention}, il te faut **{prix_roll} 🪙** pour faire un tirage payant. Il te manque **{prix_roll - solde} 🪙** !")
        return

    # On filtre les voitures comme dans le roll normal
    voitures_possedees = profil.get("garage", []) if profil else []
    voitures_disponibles = []
    poids_disponibles = []

    for voiture in VOITURES:
        nom_complet = f"{voiture['marque']} {voiture['nom']}"
        if nom_complet not in voitures_possedees:
            voitures_disponibles.append(voiture)
            poids_disponibles.append(voiture.get("poids", 10))

    if not voitures_disponibles:
        await ctx.send(f"🏆 Tu possèdes déjà **TOUTES** les voitures du jeu ! Garde ton argent.")
        return

    # Le tirage
    voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
    nom_complet_gagnee = f"{voiture_gagnee['marque']} {voiture_gagnee['nom']}"

    # On sauvegarde la voiture ET on débite l'argent ($inc avec un nombre négatif)
    await collection_inventaires.update_one(
        {"_id": user_id},
        {
            "$push": {"garage": nom_complet_gagnee},
            "$inc": {"coins": -prix_roll}
        }
    )

    nouveau_solde = solde - prix_roll
    
    embed = discord.Embed(
        title=f"🎰 Tirage Payant : {nom_complet_gagnee} !", 
        description=f"Transaction acceptée : -{prix_roll} 🪙\nNouveau solde : **{nouveau_solde} 🪙**",
        color=discord.Color.purple()
    )
    embed.set_image(url=voiture_gagnee['image'])
    embed.set_footer(text=f"Rareté : {voiture_gagnee['rareté']} | Appartient à {ctx.author.display_name}")
    
    await ctx.send(embed=embed)
#endregion

#region leaderboard
@bot.command(aliases=["top", "lb", "classement", "leaderboard"])
async def toplist(ctx):
    # 1. On récupère tous les profils de la base de données (limité à 1000 joueurs pour éviter les crashs)
    profils = await collection_inventaires.find({}).to_list(length=1000)

    if not profils:
        await ctx.send("❌ Aucun joueur n'est enregistré dans la base de données pour le moment !")
        return

    # 2. On trie les joueurs pour l'Argent (les plus riches en premier)
    # On prend les 10 premiers ([:10])
    top_coins = sorted(profils, key=lambda x: x.get("coins", 0), reverse=True)[:10]
    
    # 3. On trie les joueurs pour le Garage (ceux qui ont le plus de voitures)
    # len() permet de compter la taille de la liste "garage"
    top_garage = sorted(profils, key=lambda x: len(x.get("garage", [])), reverse=True)[:10]

    # --- Préparation du texte de la colonne ARGENT ---
    texte_coins = ""
    for i, profil in enumerate(top_coins, 1):
        solde = profil.get('coins', 0)
        if solde > 0: # On n'affiche que ceux qui ont au moins 1 pièce
            texte_coins += f"**{i}.** <@{profil['_id']}> : {solde} 🪙\n"
            
    if not texte_coins:
        texte_coins = "Tout le monde est fauché ! 💸"

    # --- Préparation du texte de la colonne GARAGE ---
    texte_garage = ""
    for i, profil in enumerate(top_garage, 1):
        taille = len(profil.get("garage", []))
        if taille > 0: # On n'affiche que ceux qui ont au moins 1 voiture
            texte_garage += f"**{i}.** <@{profil['_id']}> : {taille} 🚗\n"
            
    if not texte_garage:
        texte_garage = "Tous les garages sont vides ! 🚶‍♂️"

    # 4. Création de l'Embed final
    embed = discord.Embed(
        title="🏆 Classement Officiel du Serveur",
        description="Qui dominera le marché automobile ?",
        color=discord.Color.gold()
    )
    
    # inline=True permet de mettre les deux classements côte à côte !
    embed.add_field(name="💰 Top Richesse", value=texte_coins, inline=True)
    embed.add_field(name="🚗 Top Collection", value=texte_garage, inline=True)
    
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None) # Met l'icône de ton serveur Discord en haut à droite
    
    await ctx.send(embed=embed)
#endregion

# 4. Lancement
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
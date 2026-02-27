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
# On a supprimé le @commands.cooldown d'ici !
async def roll(ctx):
    user_id = str(ctx.author.id)
    maintenant = time.time() # L'heure exacte actuelle en secondes
    cooldown_secondes = 43200 # 1 heure

    # 1. Récupérer le profil du joueur
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    # 2. VÉRIFIER LE TEMPS D'ATTENTE DANS MONGODB
    if profil and "last_roll" in profil:
        temps_ecoule = maintenant - profil["last_roll"]
        if temps_ecoule < cooldown_secondes:
            temps_restant = int(cooldown_secondes - temps_ecoule)
            minutes = temps_restant // 3600
            secondes = (temps_restant % 3600) // 60
            await ctx.send(f"⏳ Doucement {ctx.author.mention} ! Ton prochain tirage est dispo dans **{minutes} minutes et {secondes} secondes**.")
            return # On arrête la commande ici

    # 3. La suite du code (Filtrer les voitures possédées)
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

    # 5. Sauvegarder dans MongoDB (L'inventaire ET l'heure du tirage !)
    await collection_inventaires.update_one(
        {"_id": user_id},
        {
            "$push": {"garage": nom_complet_gagnee},
            "$set": {"last_roll": maintenant} # On ajoute cette ligne magique
        },
        upsert=True
    )

    # 6. Création de l'Embed
    embed = discord.Embed(
        title=f"🎰 Tu as obtenu : {nom_complet_gagnee} !", 
        color=discord.Color.gold()
    )
    embed.set_image(url=voiture_gagnee['image'])
    
    total_poids = sum(poids_disponibles)
    chance_pourcent = (voiture_gagnee.get("poids", 10) / total_poids) * 100
    
    embed.set_footer(text=f"Rareté : {voiture_gagnee['rareté']} (Drop rate actuel : {chance_pourcent:.1f}%) | Appartient à {ctx.author.display_name}")
    
    await ctx.send(embed=embed)

# --- Gestion de l'erreur si le joueur spam la commande ---
@roll.error
async def roll_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        minutes_restantes = int(error.retry_after // 60)
        await ctx.send(f"⏳ Doucement {ctx.author.mention} ! Ton prochain tirage est dispo dans **{minutes_restantes} minutes**.")
#endregion

#region garage
# 1. La Vue mise à jour pour afficher 1 voiture par page
class GaragePagination(discord.ui.View):
    def __init__(self, ctx, pages, total_voitures, target_member):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages # 'pages' contient maintenant une liste de dictionnaires (les infos de chaque voiture)
        self.total_voitures = total_voitures
        self.target_member = target_member
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.bouton_prec.disabled = self.current_page == 0
        self.bouton_suiv.disabled = self.current_page == len(self.pages) - 1

    def get_embed(self):
        # On récupère les infos de la voiture sur la page actuelle
        voiture_actuelle = self.pages[self.current_page]
        
        # On prépare le titre
        description = f"### {voiture_actuelle['nom_complet']}"
        if voiture_actuelle['quantite'] > 1:
            description += f" **(x{voiture_actuelle['quantite']})**"
            
        embed = discord.Embed(
            title=f"🚗 Le Garage de {self.target_member.display_name}", 
            description=description, 
            color=discord.Color.blue()
        )
        
        # On affiche l'image si elle a été trouvée
        if voiture_actuelle['image']:
            embed.set_image(url=voiture_actuelle['image'])
            
        embed.add_field(name="Rareté", value=voiture_actuelle['rareté'])
        
        # Le footer indique le modèle en cours sur le total de modèles différents
        embed.set_footer(text=f"Modèle {self.current_page + 1}/{len(self.pages)} | Total dans le garage : {self.total_voitures} voitures")
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
    
    if not profil or not profil.get("garage"):
        if cible == ctx.author:
            await ctx.send(f"Ton garage est vide, {ctx.author.mention} ! Fais `!roll` pour gagner ta première voiture.")
        else:
            await ctx.send(f"Le garage de **{cible.display_name}** est complètement vide pour le moment !")
        return
    
    mes_voitures = profil["garage"]
    inventaire_compte = Counter(mes_voitures) # Compte les doublons
    
    pages_voitures = []
    
    # On reconstruit les informations pour chaque modèle possédé
    for nom_complet, quantite in inventaire_compte.items():
        # On cherche cette voiture dans le catalogue global VOITURES pour récupérer son image
        voiture_info = next((v for v in VOITURES if f"{v['marque']} {v['nom']}" == nom_complet), None)
        
        if voiture_info:
            pages_voitures.append({
                "nom_complet": nom_complet,
                "quantite": quantite,
                "image": voiture_info["image"],
                "rareté": voiture_info["rareté"]
            })
        else:
            # Sécurité : si la voiture a été supprimée du fichier JSON entre temps
            pages_voitures.append({
                "nom_complet": nom_complet,
                "quantite": quantite,
                "image": None,
                "rareté": "Inconnue (Supprimée du catalogue)"
            })
            
    # On initialise la vue avec notre nouvelle liste d'objets "voiture"
    view = GaragePagination(ctx, pages_voitures, len(mes_voitures), cible)
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

    # 1. On va chercher l'inventaire du joueur
    profil = await collection_inventaires.find_one({"_id": user_id})

    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est complètement vide, {ctx.author.mention} !")
        return

    garage = profil["garage"]

    if voiture_a_vendre not in garage:
        await ctx.send(f"❌ Tu ne possèdes pas la voiture **{voiture_a_vendre}** ! (Vérifie bien les majuscules et les espaces en faisant `!garage`)")
        return

    # 2. Demande de confirmation avec un message clair
    msg = await ctx.send(f"⚠️ {ctx.author.mention}, es-tu **sûr et certain** de vouloir jeter ta **{voiture_a_vendre}** ?\nElle retournera dans la pioche globale.\n\n*Réagis avec ✅ pour confirmer ou ❌ pour annuler.*")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    # Fonction pour s'assurer que seul l'auteur de la commande peut cliquer
    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

    try:
        # 3. On attend la réaction du joueur (timeout de 30 secondes)
        reaction, user = await bot.wait_for('reaction_add', timeout=30.0, check=check)
        
        if str(reaction.emoji) == "✅":
            # Le joueur a confirmé, on supprime !
            garage.remove(voiture_a_vendre)

            await collection_inventaires.update_one(
                {"_id": user_id},
                {"$set": {"garage": garage}}
            )

            await ctx.send(f"🗑️ C'est fait {ctx.author.mention} ! Tu t'es débarrassé de ta **{voiture_a_vendre}**.")
        else:
            # Le joueur a cliqué sur la croix
            await ctx.send(f"❌ Vente annulée. Tu gardes ta **{voiture_a_vendre}** bien au chaud !")

    except asyncio.TimeoutError:
        # Le joueur a mis trop de temps à répondre
        await ctx.send(f"⏳ Temps écoulé, la vente de ta **{voiture_a_vendre}** est annulée.")
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

# 4. Lancement
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
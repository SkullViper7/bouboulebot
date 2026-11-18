import discord
from discord.ext import commands
import aiohttp
import random
import os
import re
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import urllib.parse
from motor.motor_asyncio import AsyncIOMotorClient
from collections import Counter
import json
import asyncio
import math
import time
from flask import Flask
from phrases import PHRASES_RACE, PHRASES_VICTOIRE, PHRASES_INTRO
from threading import Thread
from datetime import datetime, timedelta
from typing import Union, Optional
try:
    from zoneinfo import ZoneInfo
except ImportError:
    pass
from logos import LOGOS

#region Init
# 1. Chargement des secrets
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GIPHY_TOKEN = os.getenv("GIPHY_KEY")
MONGO_URI = os.getenv("MONGO_URI")

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["bouboule_cars"]
collection_inventaires = db["inventaires"]
collection_suggestions = db["suggestions_voitures"]

# 2. Chargement du catalogue et création des dictionnaires de recherche
with open('cars.json', 'r', encoding='utf-8') as f:
    VOITURES = json.load(f)

# NOUVEAU : Dictionnaire pour trouver instantanément une voiture grâce à son ID
VOITURES_BY_ID = {v["id"]: v for v in VOITURES if "id" in v}

# NOUVEAU : Fonction utilitaire pour toujours afficher le nom proprement
def get_nom_complet(voiture):
    if not voiture: return "Voiture Inconnue"
    return f"{voiture.get('marque', '')} {voiture.get('nom', '')} {voiture.get('annee', '')}".strip()

# --- Faux Serveur Web pour Render ---
app = Flask('')
@app.route('/')
def home():
    return "Bot en ligne !"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# 3. Configuration du Bot Discord
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
#endregion

# --- Événement de démarrage ---
@bot.event
async def on_ready():
    print("="*30)
    print(f"✅ CONNECTÉ AVEC SUCCÈS !")
    print(f"🤖 Nom du bot : {bot.user.name}")
    print(f"🆔 ID du bot  : {bot.user.id}")
    
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Commandes Slash synchronisées : {len(synced)}")
    except Exception as e:
        print(f"❌ Erreur de synchro slash : {e}")
        
    print("="*30)

# --- ÉCONOMIE & RARETÉS ---
PRIX_REVENTE = {
    "Commun ⚪": 100,
    "Rare 🔵": 500,
    "Mythique 🟣": 2500,
    "Légendaire 🟡": 5000,
    "GOAT 🔴": 20000
}
COULEURS_RARETE = {
    "Commun ⚪": discord.Color.light_grey(),
    "Rare 🔵": discord.Color.blue(),
    "Mythique 🟣": discord.Color.dark_purple(),
    "Légendaire 🟡": discord.Color.gold(),
    "GOAT 🔴": discord.Color.red()
}
    
#region time
def get_reset_timestamps():
    try:
        tz = ZoneInfo("Europe/Paris") 
    except:
        from datetime import timezone
        tz = timezone(timedelta(hours=1)) 
        
    now = datetime.now(tz)
    heure_dernier_reset = now.hour
    heure_prochain_reset = heure_dernier_reset + 1
    last_reset = now.replace(hour=heure_dernier_reset, minute=0, second=0, microsecond=0)
    
    if heure_prochain_reset == 24:
        next_reset = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        next_reset = now.replace(hour=heure_prochain_reset, minute=0, second=0, microsecond=0)
        
    return last_reset.timestamp(), next_reset.timestamp(), next_reset
#endregion

#region succes
async def verifier_succes_marque(ctx, user_id, marque):
    voitures_de_la_marque_ids = [v["id"] for v in VOITURES if v['marque'] == marque]
    
    if len(voitures_de_la_marque_ids) < 2:
        return
    
    profil = await collection_inventaires.find_one({"_id": str(user_id)})
    if not profil:
        return
        
    succes_debloques = profil.get("succes_marques", [])
    if marque in succes_debloques:
        return 
        
    garage = profil.get("garage", [])
    possede_toutes = all(vid in garage for vid in voitures_de_la_marque_ids)
    
    if possede_toutes:
        recompense = len(voitures_de_la_marque_ids) * 1000 
        await collection_inventaires.update_one(
            {"_id": str(user_id)},
            {
                "$push": {"succes_marques": marque},
                "$inc": {"coins": recompense}
            }
        )
        
        ancien_solde = profil.get("coins", 0)
        nouveau_solde = ancien_solde + recompense
        embed = discord.Embed(
            title="🏆 NOUVEAU SUCCÈS DÉBLOQUÉ !",
            description=f"Incroyable ! <@{user_id}> vient de collectionner **absolument tous** les modèles de la marque **{marque}** !\n\n🎁 **Bonus de collectionnneur : +{recompense} 🪙**",
            color=discord.Color.brand_green()
        )
        embed.set_footer(text=f"Nouveau solde : {nouveau_solde} 🪙")
        await ctx.channel.send(embed=embed)
#endregion

#region sort
def appliquer_tri_garage(garage_ids, preference):
    if not preference or not garage_ids:
        return garage_ids
        
    if preference == "rarity":
        ordre_rarete = {"GOAT 🔴": 1, "Légendaire 🟡": 2, "Mythique 🟣": 3, "Rare 🔵": 4, "Commun ⚪": 5}
        garage_ids.sort(key=lambda vid: (
            ordre_rarete.get(VOITURES_BY_ID.get(vid, {}).get("rareté", "Commun ⚪"), 99),
            VOITURES_BY_ID.get(vid, {}).get("marque", ""),
            VOITURES_BY_ID.get(vid, {}).get("nom", "")
        ))
    elif preference == "brand":
        garage_ids.sort(key=lambda vid: (
            VOITURES_BY_ID.get(vid, {}).get("marque", ""),
            VOITURES_BY_ID.get(vid, {}).get("nom", "")
        ))
    elif preference == "year":
        def get_year(vid):
            try: return int(VOITURES_BY_ID.get(vid, {}).get("annee", ""))
            except (ValueError, TypeError): return 9999
        garage_ids.sort(key=lambda vid: (
            get_year(vid),
            VOITURES_BY_ID.get(vid, {}).get("marque", ""),
            VOITURES_BY_ID.get(vid, {}).get("nom", "")
        ))
    elif preference == "power":
        def get_power(vid):
            puissance_str = VOITURES_BY_ID.get(vid, {}).get("puissance", "")
            if not puissance_str or puissance_str.lower() in ["inconnu", "inconnue"]: return -1 
            nombres = re.findall(r'\d+', puissance_str.replace(' ', ''))
            return int(nombres[0]) if nombres else -1
            
        garage_ids.sort(key=lambda vid: (
            -get_power(vid),
            VOITURES_BY_ID.get(vid, {}).get("marque", ""),
            VOITURES_BY_ID.get(vid, {}).get("nom", "")
        ))
    elif preference == "class":
        def get_ratio(vid):
            voiture = VOITURES_BY_ID.get(vid, {})
            puissance_str = voiture.get('puissance', '')
            masse_str = str(voiture.get('masse_kg', ''))
            puissance = None
            if puissance_str and puissance_str.lower() not in ["inconnu", "inconnue"]:
                nombres_p = re.findall(r'\d+', puissance_str.replace(' ', ''))
                if nombres_p: puissance = int(nombres_p[0])
            masse = None
            if masse_str and masse_str.lower() not in ["inconnu", "inconnue"]:
                nombres_m = re.findall(r'\d+', masse_str.replace(' ', ''))
                if nombres_m: masse = int(nombres_m[0])
            if not puissance or not masse or puissance == 0: return 999.0
            return masse / puissance

        garage_ids.sort(key=lambda vid: (
            get_ratio(vid),
            VOITURES_BY_ID.get(vid, {}).get("marque", ""),
            VOITURES_BY_ID.get(vid, {}).get("nom", "")
        ))
        
    return garage_ids

@bot.hybrid_command(name="sortrarity", description="Trie ton garage par ordre de rareté.", aliases=["sortr", "trierrarte", "trier_rarete"])
async def sortrarity(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    if not profil or not profil.get("garage"): return await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
    garage = appliquer_tri_garage(profil["garage"], "rarity")
    await collection_inventaires.update_one({"_id": user_id}, {"$set": {"garage": garage, "sort_preference": "rarity"}})
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par rareté**.")

@bot.hybrid_command(name="sortbrand", description="Trie ton garage par ordre alphabétique des marques.", aliases=["sortb"])
async def sortbrand(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    if not profil or not profil.get("garage"): return await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
    garage = appliquer_tri_garage(profil["garage"], "brand")
    await collection_inventaires.update_one({"_id": user_id}, {"$set": {"garage": garage, "sort_preference": "brand"}})
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par marque**.")

@bot.hybrid_command(name="sortyear", description="Trie ton garage par ordre chronologique.", aliases=["sorty"])
async def sortyear(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    if not profil or not profil.get("garage"): return await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
    garage = appliquer_tri_garage(profil["garage"], "year")
    await collection_inventaires.update_one({"_id": user_id}, {"$set": {"garage": garage, "sort_preference": "year"}})
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **chronologiquement**.")

@bot.hybrid_command(name="sortpower", description="Trie ton garage par ordre de puissance.", aliases=["sortp"])
async def sortpower(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    if not profil or not profil.get("garage"): return await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
    garage = appliquer_tri_garage(profil["garage"], "power")
    await collection_inventaires.update_one({"_id": user_id}, {"$set": {"garage": garage, "sort_preference": "power"}})
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par puissance**.")

@bot.hybrid_command(name="sortclass", description="Trie ton garage par classe de performance.", aliases=["sortc"])
async def sortclass(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    if not profil or not profil.get("garage"): return await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
    garage = appliquer_tri_garage(profil["garage"], "class")
    await collection_inventaires.update_one({"_id": user_id}, {"$set": {"garage": garage, "sort_preference": "class"}})
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par classe**.")
#endregion

#region grade
def obtenir_nom_classe_simple(voiture):
    puissance_str = voiture.get('puissance', '')
    masse_str = str(voiture.get('masse_kg', ''))
    puissance = None
    if puissance_str and puissance_str.lower() not in ["inconnu", "inconnue"]:
        nombres_p = re.findall(r'\d+', puissance_str.replace(' ', ''))
        if nombres_p: puissance = int(nombres_p[0])
    masse = None
    if masse_str and masse_str.lower() not in ["inconnu", "inconnue"]:
        nombres_m = re.findall(r'\d+', masse_str.replace(' ', ''))
        if nombres_m: masse = int(nombres_m[0])
    if not puissance or not masse or puissance == 0: return None
    ratio = masse / puissance
    if ratio >= 10.0: return "D"
    elif ratio >= 7.0: return "C"
    elif ratio >= 4.5: return "B"
    elif ratio >= 3.0: return "A"
    elif ratio >= 2.0: return "S1"
    elif ratio >= 1.2: return "S2"
    else: return "X"

def calculer_classe_forza(voiture):
    puissance_str = voiture.get('puissance', '')
    masse_str = str(voiture.get('masse_kg', ''))
    puissance = None
    if puissance_str and puissance_str.lower() not in ["inconnu", "inconnue"]:
        nombres_p = re.findall(r'\d+', puissance_str.replace(' ', ''))
        if nombres_p: puissance = int(nombres_p[0])
    masse = None
    if masse_str and masse_str.lower() not in ["inconnu", "inconnue"]:
        nombres_m = re.findall(r'\d+', masse_str.replace(' ', ''))
        if nombres_m: masse = int(nombres_m[0])
    if not puissance or not masse or puissance == 0: return LOGOS.get("Classe Inconnue", "❓ Non classé")
    ratio = masse / puissance
    if ratio >= 10.0: return LOGOS.get("Classe D", "🟩 **Classe D**")
    elif ratio >= 7.0: return LOGOS.get("Classe C", "🟦 **Classe C**")
    elif ratio >= 4.5: return LOGOS.get("Classe B", "🟪 **Classe B**")
    elif ratio >= 3.0: return LOGOS.get("Classe A", "🟧 **Classe A**")
    elif ratio >= 2.0: return LOGOS.get("Classe S1", "🟥 **Classe S1**")
    elif ratio >= 1.2: return LOGOS.get("Classe S2", "💎 **Classe S2**")
    else: return LOGOS.get("Classe X", "👑 **Classe X**")
#endregion

#region roll
@bot.hybrid_command(name="roll", description="Tire une voiture au hasard toutes les heures.")
async def roll(ctx):
    user_id = str(ctx.author.id)
    last_reset_ts, next_reset_ts, next_reset_dt = get_reset_timestamps()
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if profil and "last_roll" in profil:
        if profil["last_roll"] >= last_reset_ts:
            temps_restant = int(next_reset_ts - time.time())
            heures = temps_restant // 3600
            minutes = (temps_restant % 3600) // 60
            heure_cible = next_reset_dt.strftime("%Hh00")
            await ctx.send(f"⏳ Doucement {ctx.author.mention} ! Tu as déjà fait ton tirage pour ce créneau.\nLe prochain sera dispo à **{heure_cible}** (dans {heures}h et {minutes}m).")
            return

    voitures_possedees_ids = profil.get("garage", []) if profil else []
    wishlist_joueur_ids = profil.get("wishlist", []) if profil else []
    marque_favorite = profil.get("favorite_brand") if profil else None
    
    voitures_disponibles = []
    poids_disponibles = []

    for voiture in VOITURES:
        if voiture["id"] not in voitures_possedees_ids:
            voitures_disponibles.append(voiture)
            poids_calc = voiture.get("poids", 10)
            if marque_favorite and voiture['marque'] == marque_favorite:
                poids_calc *= 1.5
            if voiture["id"] in wishlist_joueur_ids:
                poids_calc *= 2
            poids_disponibles.append(poids_calc)

    if not voitures_disponibles:
        await ctx.send(f"🏆 Incroyable {ctx.author.mention}, tu possèdes déjà **TOUTES** les voitures du jeu !")
        return

    voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
    nom_complet_gagnee = get_nom_complet(voiture_gagnee)
    print(f"[LOG 🎰] {ctx.author.name} a obtenu l'ID {voiture_gagnee['id']} : {nom_complet_gagnee}")

    rarete = voiture_gagnee['rareté']
    prix_base = PRIX_REVENTE.get(rarete, 50)
    bonus_coins = int(prix_base * 0.20) 
    maintenant = time.time()
    
    voitures_possedees_ids.append(voiture_gagnee["id"])
    sort_preference = profil.get("sort_preference") if profil else None
    if sort_preference: voitures_possedees_ids = appliquer_tri_garage(voitures_possedees_ids, sort_preference)
    
    update_query = {
        "$set": {"garage": voitures_possedees_ids, "last_roll": maintenant},
        "$inc": {"coins": bonus_coins}
    }
    if voiture_gagnee["id"] in wishlist_joueur_ids:
        update_query["$pull"] = {"wishlist": voiture_gagnee["id"]}

    await collection_inventaires.update_one({"_id": user_id}, update_query, upsert=True)

    membres_serveur_ids = [str(m.id) for m in ctx.guild.members]
    curseur = collection_inventaires.find({"garage": voiture_gagnee["id"], "_id": {"$in": membres_serveur_ids}})
    docs = await curseur.to_list(length=100)
    proprietaires_mentions = [f"<@{doc['_id']}>" for doc in docs]
    texte_proprietaires = ", ".join(proprietaires_mentions) if proprietaires_mentions else f"<@{user_id}>"

    classe_forza = calculer_classe_forza(voiture_gagnee)
    masse = voiture_gagnee.get('masse_kg', 'Inconnu')
    logo = LOGOS.get(voiture_gagnee['marque'], "")
    
    lignes = [voiture_gagnee['nom'], f"{logo} **{voiture_gagnee['marque']}**"]
    if voiture_gagnee.get('annee'): lignes.append(str(voiture_gagnee['annee']))
    lignes.extend([voiture_gagnee.get('pays', '🏁'), "", "**Rareté**", rarete, "", "**⚙️ Spécifications**", 
                   f"Moteur : {voiture_gagnee.get('moteur', 'Inconnu')}", f"Puissance : {voiture_gagnee.get('puissance', 'Inconnue')}", 
                   f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu", classe_forza, "", "**Propriétaires :**", 
                   texte_proprietaires, "", f"🎁 *Bonus de drop : +{bonus_coins} 🪙*"])

    embed = discord.Embed(title=f"🎰 Vous avez eu : {nom_complet_gagnee}", description="\n".join(lignes), color=COULEURS_RARETE.get(rarete, discord.Color.gold()))
    image_url = (voiture_gagnee.get('image') or '').strip()
    if image_url.startswith(('http://', 'https://')): embed.set_image(url=image_url)
    else: embed.add_field(name="⚠️ Image indisponible", value="Lien cassé dans le catalogue.", inline=False)

    phrase = {"Commun ⚪": "Ouais basique", "Rare 🔵": "Eh pas mal", "Mythique 🟣": "Eh beh mon salaud", "Légendaire 🟡": "Oh pétard", "GOAT 🔴": "WAAAAAAAA"}.get(rarete, "Bien joué")
    voeu_exauce = "\n\n🌟 **VŒU EXAUCÉ !** Retirée de la wishlist." if voiture_gagnee["id"] in wishlist_joueur_ids else ("\n\n⭐ **BINGO !** Modèle de ta marque favorite !" if marque_favorite and voiture_gagnee['marque'] == marque_favorite else "")

    await ctx.send(content=f"{ctx.author.mention} **{phrase} !**{voeu_exauce}", embed=embed)
    await verifier_succes_marque(ctx, user_id, voiture_gagnee['marque'])

@roll.error
async def roll_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown): await ctx.send(f"⏳ Doucement {ctx.author.mention} ! Trop de commandes.")
#endregion

#region garage
class GaragePagination(discord.ui.View):
    def __init__(self, ctx, pages, total_voitures, target_member, solde, start_page=0):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.total_voitures = total_voitures
        self.target_member = target_member
        self.solde = solde 
        self.current_page = max(0, min(start_page, len(self.pages) - 1)) if self.pages else 0
        self.update_buttons()

    def update_buttons(self):
        self.bouton_prec.disabled = len(self.pages) <= 1
        self.bouton_suiv.disabled = len(self.pages) <= 1

    def get_embed(self):
        voiture = self.pages[self.current_page]
        rarete = voiture['rareté']
        classe_forza = calculer_classe_forza(voiture)
        masse = voiture.get('masse_kg', 'Inconnu')
        logo = LOGOS.get(voiture['marque'], "")
        
        lignes = [voiture['nom'], f"{logo} **{voiture['marque']}**"]
        if voiture.get('annee'): lignes.append(str(voiture['annee']))
        lignes.extend([voiture.get('pays', '🏁'), "", "**Rareté**", rarete, "", "**⚙️ Spécifications**", 
                       f"Moteur : {voiture.get('moteur', 'Inconnu')}", f"Puissance : {voiture.get('puissance', 'Inconnue')}", 
                       f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu", classe_forza, "", f"💳 *Solde : {self.solde} 🪙*"])
        
        embed = discord.Embed(title=f"🚗 Le Garage de {self.target_member.display_name}", description="\n".join(lignes), color=COULEURS_RARETE.get(rarete, discord.Color.blue()))
        if voiture.get('image', '').startswith(('http://', 'https://')): embed.set_image(url=voiture['image'])
        else: embed.add_field(name="⚠️ Image indisponible", value="Lien invalide.", inline=False)
        embed.set_footer(text=f"Modèle {self.current_page + 1}/{len(self.pages)} | Total : {self.total_voitures} voitures")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, custom_id="prec")
    async def bouton_prec(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return await interaction.response.send_message("Pas ton menu !", ephemeral=True)
        self.current_page = (self.current_page - 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, custom_id="suiv")
    async def bouton_suiv(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return await interaction.response.send_message("Pas ton menu !", ephemeral=True)
        self.current_page = (self.current_page + 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.hybrid_command(name="garage", description="Affiche ton garage ou celui d'un autre joueur.")
async def garage(ctx, membre: discord.Member = None, page: int = 1):
    cible = membre or ctx.author
    page_cible = max(1, page) 
    profil = await collection_inventaires.find_one({"_id": str(cible.id)})
    solde = profil.get("coins", 0) if profil else 0
    
    if not profil or not profil.get("garage"):
        embed_vide = discord.Embed(title=f"🚗 Le Garage de {cible.display_name}", description=f"💳 *Solde : {solde} 🪙*\n\nCe garage est vide ! Fais un `!roll`.", color=discord.Color.light_grey())
        return await ctx.send(embed=embed_vide)
    
    mes_voitures_ids = profil["garage"]
    inventaire_compte = Counter(mes_voitures_ids)
    pages_voitures = []
    
    vus = set()
    for vid in mes_voitures_ids:
        if vid in vus: continue
        vus.add(vid)
        quantite = inventaire_compte[vid]
        v_info = VOITURES_BY_ID.get(vid)
        
        if v_info:
            pages_voitures.append({
                "nom": v_info["nom"], "marque": v_info["marque"], "annee": v_info.get("annee", ""), "pays": v_info.get("pays", "🏁"),
                "quantite": quantite, "image": v_info["image"], "rareté": v_info["rareté"], "moteur": v_info.get("moteur", "Inconnu"),
                "puissance": v_info.get("puissance", "Inconnue"), "masse_kg": v_info.get("masse_kg", "Inconnu")
            })
            
    view = GaragePagination(ctx, pages_voitures, len(mes_voitures_ids), cible, solde, start_page=page_cible - 1)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region trade
@bot.hybrid_command(name="trade", description="Propose un échange de voiture à un autre joueur.")
async def trade(ctx, membre: discord.Member, ma_voiture: str, sa_voiture: str):
    if ctx.author == membre: return await ctx.send("Tu ne peux pas échanger avec toi-même !")
    user_id, target_id = str(ctx.author.id), str(membre.id)
    profil_user = await collection_inventaires.find_one({"_id": user_id}) or {}
    profil_target = await collection_inventaires.find_one({"_id": target_id}) or {}
    garage_user = profil_user.get("garage", [])
    garage_target = profil_target.get("garage", [])

    ma_voiture_id = next((vid for vid in garage_user if ma_voiture.lower() in get_nom_complet(VOITURES_BY_ID.get(vid)).lower()), None)
    sa_voiture_id = next((vid for vid in garage_target if sa_voiture.lower() in get_nom_complet(VOITURES_BY_ID.get(vid)).lower()), None)

    if not ma_voiture_id: return await ctx.send(f"❌ Tu ne possèdes pas la voiture **{ma_voiture}** !")
    if not sa_voiture_id: return await ctx.send(f"❌ {membre.display_name} ne possède pas la voiture **{sa_voiture}** !")

    info_ma = VOITURES_BY_ID.get(ma_voiture_id)
    info_sa = VOITURES_BY_ID.get(sa_voiture_id)

    prix_ma = PRIX_REVENTE.get(info_ma["rareté"], 50)
    prix_sa = PRIX_REVENTE.get(info_sa["rareté"], 50)
    diff = abs(prix_ma - prix_sa)
    solde_user = profil_user.get("coins", 0)
    solde_target = profil_target.get("coins", 0)
    
    payeur_id = None
    msg_compensation = "\n⚖️ **Échange équitable** : Aucun argent ne sera échangé."

    if prix_ma > prix_sa:
        if solde_target < diff: return await ctx.send(f"❌ **Échange annulé** : {membre.mention} n'a pas assez d'argent pour la compensation (manque {diff - solde_target} 🪙) !")
        payeur_id = target_id
        msg_compensation = f"\n⚠️ **Compensation :** {membre.display_name} devra payer **{diff} 🪙** à {ctx.author.display_name}."
    elif prix_sa > prix_ma:
        if solde_user < diff: return await ctx.send(f"❌ **Échange annulé** : {ctx.author.mention} n'a pas assez d'argent pour la compensation (manque {diff - solde_user} 🪙) !")
        payeur_id = user_id
        msg_compensation = f"\n⚠️ **Compensation :** {ctx.author.display_name} devra payer **{diff} 🪙** à {membre.display_name}."

    nom_ma_voiture = get_nom_complet(info_ma)
    nom_sa_voiture = get_nom_complet(info_sa)

    msg = await ctx.send(f"Hey {membre.mention} ! {ctx.author.mention} te propose d'échanger sa **{nom_ma_voiture}** contre ta **{nom_sa_voiture}**.{msg_compensation}\n\n*Réagis avec ✅ pour accepter ou ❌ pour refuser.*")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    def check(reaction, user): return user == membre and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
        if str(reaction.emoji) == "✅":
            garage_user.remove(ma_voiture_id)
            garage_target.remove(sa_voiture_id)
            garage_user.append(sa_voiture_id)
            garage_target.append(ma_voiture_id)

            pref_user = profil_user.get("sort_preference")
            pref_target = profil_target.get("sort_preference")
            if pref_user: garage_user = appliquer_tri_garage(garage_user, pref_user)
            if pref_target: garage_target = appliquer_tri_garage(garage_target, pref_target)

            update_user = {"$set": {"garage": garage_user}}
            update_target = {"$set": {"garage": garage_target}}

            if diff > 0:
                if payeur_id == user_id:
                    update_user["$inc"] = {"coins": -diff}; update_target["$inc"] = {"coins": diff}
                else:
                    update_user["$inc"] = {"coins": diff}; update_target["$inc"] = {"coins": -diff}

            await collection_inventaires.update_one({"_id": user_id}, update_user)
            await collection_inventaires.update_one({"_id": target_id}, update_target)
            await ctx.send(f"🎉 **Échange réussi** entre {ctx.author.mention} et {membre.mention} !")
            await verifier_succes_marque(ctx, user_id, info_sa['marque'])
            await verifier_succes_marque(ctx, target_id, info_ma['marque'])
        else: await ctx.send(f"❌ {membre.display_name} a refusé l'échange.")
    except asyncio.TimeoutError: await ctx.send(f"⏳ Temps écoulé, l'échange proposé par {ctx.author.mention} est annulé.")
#endregion

#region tradeup
class TradeUpSelectionView(discord.ui.View):
    def __init__(self, ctx, eligible_cars_ids, rarete_base, rarete_gagne, profil, garage_ids):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.user = ctx.author
        self.eligible_cars_ids = eligible_cars_ids
        self.rarete_base = rarete_base
        self.rarete_gagne = rarete_gagne
        self.profil = profil
        self.garage_ids = garage_ids
        
        self.selected_indices = set()
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, math.ceil(len(eligible_cars_ids) / self.items_per_page))
        self.number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        self.update_view_state()

    def update_view_state(self):
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page >= self.total_pages - 1)
        self.btn_confirm.disabled = (len(self.selected_indices) != 5)
        boutons_nombres = [self.btn_1, self.btn_2, self.btn_3, self.btn_4, self.btn_5]
        for i, btn in enumerate(boutons_nombres):
            abs_index = self.current_page * self.items_per_page + i
            if abs_index >= len(self.eligible_cars_ids):
                btn.disabled, btn.style = True, discord.ButtonStyle.secondary
            else:
                btn.disabled = False
                btn.style = discord.ButtonStyle.success if abs_index in self.selected_indices else discord.ButtonStyle.secondary

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.eligible_cars_ids[start:end]
        
        lignes = []
        for i, vid in enumerate(page_items):
            abs_index = start + i
            check = " ✅" if abs_index in self.selected_indices else ""
            nom = get_nom_complet(VOITURES_BY_ID.get(vid))
            lignes.append(f"{self.number_emojis[i]} **{nom}**{check}")
            
        embed = discord.Embed(title=f"⚠️ TRADE-UP {self.rarete_base} ➔ {self.rarete_gagne}", description=f"Sélectionne **5 voitures** à sacrifier.\n\n" + "\n".join(lignes), color=discord.Color.orange())
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} | Sélectionnées : {len(self.selected_indices)}/5")
        return embed

    async def toggle_item(self, interaction: discord.Interaction, idx_offset: int):
        if interaction.user != self.user: return await interaction.response.send_message("Pas ton menu !", ephemeral=True)
        abs_index = self.current_page * self.items_per_page + idx_offset
        if abs_index >= len(self.eligible_cars_ids): return await interaction.response.defer()
        
        if abs_index in self.selected_indices: self.selected_indices.remove(abs_index)
        else:
            if len(self.selected_indices) >= 5: return await interaction.response.send_message("❌ Déjà 5 !", ephemeral=True)
            self.selected_indices.add(abs_index)
        self.update_view_state()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="1️⃣", style=discord.ButtonStyle.secondary, row=0)
    async def btn_1(self, interaction, button): await self.toggle_item(interaction, 0)
    @discord.ui.button(label="2️⃣", style=discord.ButtonStyle.secondary, row=0)
    async def btn_2(self, interaction, button): await self.toggle_item(interaction, 1)
    @discord.ui.button(label="3️⃣", style=discord.ButtonStyle.secondary, row=0)
    async def btn_3(self, interaction, button): await self.toggle_item(interaction, 2)
    @discord.ui.button(label="4️⃣", style=discord.ButtonStyle.secondary, row=0)
    async def btn_4(self, interaction, button): await self.toggle_item(interaction, 3)
    @discord.ui.button(label="5️⃣", style=discord.ButtonStyle.secondary, row=0)
    async def btn_5(self, interaction, button): await self.toggle_item(interaction, 4)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, row=1)
    async def btn_prev(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page -= 1; self.update_view_state()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, row=1)
    async def btn_next(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page += 1; self.update_view_state()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="✅ CONFIRMER", style=discord.ButtonStyle.success, row=1, disabled=True)
    async def btn_confirm(self, interaction, button):
        if interaction.user != self.user: return
        await self.execute_tradeup(interaction)

    async def execute_tradeup(self, interaction: discord.Interaction):
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(view=self)

        ids_a_retirer = [self.eligible_cars_ids[i] for i in self.selected_indices]
        nouveau_garage = list(self.garage_ids)
        for vid in ids_a_retirer:
            if vid in nouveau_garage: nouveau_garage.remove(vid)

        wishlist_joueur_ids = self.profil.get("wishlist", [])
        voitures_possibles = [v for v in VOITURES if v['rareté'] == self.rarete_gagne]
        
        voitures_disponibles, poids_disponibles = [], []
        for v in voitures_possibles:
            if v["id"] not in nouveau_garage:
                voitures_disponibles.append(v)
                poids_disponibles.append(v.get("poids", 10) * (2 if v["id"] in wishlist_joueur_ids else 1))

        if not voitures_disponibles:
            voitures_disponibles = voitures_possibles
            poids_disponibles = [v.get("poids", 10) for v in voitures_possibles]

        voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
        nouveau_garage.append(voiture_gagnee["id"])
        
        pref = self.profil.get("sort_preference")
        if pref: nouveau_garage = appliquer_tri_garage(nouveau_garage, pref)

        update_query = {"$set": {"garage": nouveau_garage}}
        if voiture_gagnee["id"] in wishlist_joueur_ids: update_query["$pull"] = {"wishlist": voiture_gagnee["id"]}

        user_id = str(self.user.id)
        await collection_inventaires.update_one({"_id": user_id}, update_query)

        membres_serveur_ids = [str(m.id) for m in self.ctx.guild.members]
        curseur = collection_inventaires.find({"garage": voiture_gagnee["id"], "_id": {"$in": membres_serveur_ids}})
        docs = await curseur.to_list(length=100)
        proprietaires_mentions = [f"<@{doc['_id']}>" for doc in docs]
        texte_proprietaires = ", ".join(proprietaires_mentions) if proprietaires_mentions else f"<@{user_id}>"

        classe_forza = calculer_classe_forza(voiture_gagnee)
        masse = voiture_gagnee.get('masse_kg', 'Inconnu')
        logo = LOGOS.get(voiture_gagnee['marque'], "")
        nom_complet = get_nom_complet(voiture_gagnee)
        
        lignes = [voiture_gagnee['nom'], f"{logo} **{voiture_gagnee['marque']}**"]
        if voiture_gagnee.get('annee'): lignes.append(str(voiture_gagnee['annee']))
        lignes.extend([voiture_gagnee.get('pays', '🏁'), "", "**Nouvelle Rareté**", self.rarete_gagne, "", "**⚙️ Spécifications**", f"Moteur : {voiture_gagnee.get('moteur', 'Inconnu')}", f"Puissance : {voiture_gagnee.get('puissance', 'Inconnue')}", f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu", classe_forza, "", "**Propriétaires :**", texte_proprietaires])

        embed = discord.Embed(title=f"✨ FUSION RÉUSSIE : {nom_complet}", description="\n".join(lignes), color=COULEURS_RARETE.get(self.rarete_gagne, discord.Color.purple()))
        if voiture_gagnee.get('image', '').startswith(('http://', 'https://')): embed.set_image(url=voiture_gagnee['image'])

        voeu_exauce = "\n🌟 **VŒU EXAUCÉ !**" if voiture_gagnee["id"] in wishlist_joueur_ids else ""
        await interaction.followup.send(content=f"🎉 {self.user.mention} **L'amélioration a fonctionné !**{voeu_exauce}", embed=embed)
        await verifier_succes_marque(self.ctx, user_id, voiture_gagnee['marque'])


@bot.hybrid_command(name="tradeup", description="Sacrifie 5 voitures de même rareté contre une de rang supérieur.")
async def tradeup(ctx, rarete: str):
    rarete_lower = rarete.lower().strip()
    map_rarete = {"commun": ("Commun ⚪", "Rare 🔵"), "commune": ("Commun ⚪", "Rare 🔵"), "blanc": ("Commun ⚪", "Rare 🔵"), "rare": ("Rare 🔵", "Mythique 🟣"), "bleu": ("Rare 🔵", "Mythique 🟣")}
    if rarete_lower not in map_rarete: return await ctx.send(f"❌ {ctx.author.mention}, le trade-up est pour **Commun** ou **Rare**.")

    rarete_base, rarete_gagne = map_rarete[rarete_lower]
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    garage_ids = profil.get("garage", []) if profil else []
    
    voitures_eligibles_ids = sorted([vid for vid in garage_ids if VOITURES_BY_ID.get(vid, {}).get('rareté') == rarete_base], key=lambda x: get_nom_complet(VOITURES_BY_ID.get(x)))
    if len(voitures_eligibles_ids) < 5: return await ctx.send(f"❌ {ctx.author.mention}, il te faut au moins **5 voitures {rarete_base}**.")

    view = TradeUpSelectionView(ctx, voitures_eligibles_ids, rarete_base, rarete_gagne, profil, garage_ids)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region sell
@bot.hybrid_command(name="sell", description="Vends une de tes voitures au concessionnaire.", aliases=["jeter", "poubelle", "vendre"])
async def sell(ctx, *, recherche: str):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    if not profil or not profil.get("garage"): return await ctx.send(f"❌ Ton garage est complètement vide, {ctx.author.mention} !")

    garage_ids = profil["garage"]
    recherche_lower = recherche.lower().strip()
    voitures_trouvees_ids = [vid for vid in garage_ids if recherche_lower in get_nom_complet(VOITURES_BY_ID.get(vid)).lower()]

    if not voitures_trouvees_ids: return await ctx.send(f"❌ Tu ne possèdes aucune voiture correspondant à **{recherche}** !")
    if len(voitures_trouvees_ids) > 1:
        liste_conflits = "\n".join([f"• {get_nom_complet(VOITURES_BY_ID.get(vid))}" for vid in voitures_trouvees_ids[:5]]) 
        if len(voitures_trouvees_ids) > 5: liste_conflits += "\n..."
        return await ctx.send(f"⚠️ {ctx.author.mention}, sois plus précis ! Plusieurs correspondances :\n{liste_conflits}")

    voiture_exacte_id = voitures_trouvees_ids[0]
    voiture_info = VOITURES_BY_ID.get(voiture_exacte_id)
    nom_voiture = get_nom_complet(voiture_info)
    prix_vente = PRIX_REVENTE.get(voiture_info["rareté"], 50)

    msg = await ctx.send(f"⚠️ {ctx.author.mention}, veux-tu vendre ta **{nom_voiture}** pour **{prix_vente} 🪙** ?\n*✅ pour vendre ou ❌ pour annuler.*")
    await msg.add_reaction("✅"); await msg.add_reaction("❌")

    def check(reaction, user): return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=30.0, check=check)
        if str(reaction.emoji) == "✅":
            garage_ids.remove(voiture_exacte_id) 
            await collection_inventaires.update_one({"_id": user_id}, {"$set": {"garage": garage_ids}, "$inc": {"coins": prix_vente}})
            await ctx.send(f"💵 Vente conclue {ctx.author.mention} ! Tu as gagné **{prix_vente} 🪙**.")
        else: await ctx.send(f"❌ Vente annulée.")
    except asyncio.TimeoutError: await ctx.send(f"⏳ Temps écoulé, vente annulée.")

@bot.hybrid_command(name="sellall", description="Vend absolument TOUTES tes voitures (action irréversible).", aliases=["liquider", "pieton"])
async def sellall(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    if not profil or not profil.get("garage"): return await ctx.send(f"❌ Ton garage est déjà vide !")

    garage_ids = profil["garage"]
    valeur_totale = sum(PRIX_REVENTE.get(VOITURES_BY_ID.get(vid, {}).get('rareté'), 50) for vid in garage_ids)

    msg1 = await ctx.send(f"⚠️ **ATTENTION {ctx.author.mention} !**\nVendre tes **{len(garage_ids)} voitures** pour **{valeur_totale} 🪙** ?\n*✅ pour continuer, ❌ pour annuler.*")
    await msg1.add_reaction("✅"); await msg1.add_reaction("❌")
    def check1(reaction, user): return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg1.id
    try:
        r1, u1 = await bot.wait_for('reaction_add', timeout=30.0, check=check1)
        if str(r1.emoji) == "❌": return await ctx.send("Vente annulée.")
    except asyncio.TimeoutError: return await ctx.send("⏳ Vente annulée.")

    msg2 = await ctx.send(f"🤨 **Hé, attends...** T'es vraiment sûr ? Tu vas finir en bus.\n*✅ pour continuer, ❌ pour annuler.*")
    await msg2.add_reaction("✅"); await msg2.add_reaction("❌")
    def check2(reaction, user): return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg2.id
    try:
        r2, u2 = await bot.wait_for('reaction_add', timeout=30.0, check=check2)
        if str(r2.emoji) == "❌": return await ctx.send("Excellente décision. Vente annulée.")
    except asyncio.TimeoutError: return await ctx.send("⏳ Vente annulée.")

    msg3 = await ctx.send(f"🚨 **DERNIÈRE CHANCE** 🚨\nAction **IRRÉVERSIBLE**. Tu valides ? ✅ / ❌")
    await msg3.add_reaction("✅"); await msg3.add_reaction("❌")
    def check3(reaction, user): return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg3.id
    try:
        r3, u3 = await bot.wait_for('reaction_add', timeout=30.0, check=check3)
        if str(r3.emoji) == "❌": return await ctx.send("Vente annulée.")
        await collection_inventaires.update_one({"_id": user_id}, {"$set": {"garage": []}, "$inc": {"coins": valeur_totale}})
        await ctx.send(f"💥 **VENDU !** Tu as liquidé **{len(garage_ids)} voitures** pour **{valeur_totale} 🪙** ! Félicitations piéton. 🚶‍♂️")
    except asyncio.TimeoutError: await ctx.send("⏳ Vente annulée.")
#endregion

#region search
class SearchResultView(discord.ui.View):
    def __init__(self, ctx, user, eligible_cars, titre, couleur, profil):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.user = user
        self.eligible_cars = eligible_cars
        self.titre = titre
        self.couleur = couleur
        self.profil = profil
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, math.ceil(len(eligible_cars) / self.items_per_page))
        self.number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        self.update_buttons()

    def update_buttons(self):
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page >= self.total_pages - 1)
        boutons_nombres = [self.btn_1, self.btn_2, self.btn_3, self.btn_4, self.btn_5]
        for i, btn in enumerate(boutons_nombres):
            abs_index = self.current_page * self.items_per_page + i
            if abs_index >= len(self.eligible_cars): btn.disabled, btn.style = True, discord.ButtonStyle.secondary
            else: btn.disabled, btn.style = False, discord.ButtonStyle.primary

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.eligible_cars[start:end]
        
        mon_garage = self.profil.get("garage", []) if self.profil else []
        lignes = []
        for i, voiture in enumerate(page_items):
            possede = " ✅" if voiture["id"] in mon_garage else ""
            logo = LOGOS.get(voiture['marque'], "")
            lignes.append(f"{self.number_emojis[i]} {logo} **{voiture['marque']}** {voiture['nom']} {voiture.get('annee', '')} ({voiture['rareté']}){possede}")
            
        embed = discord.Embed(title=self.titre, description="Clique sur le numéro :\n\n" + "\n".join(lignes), color=self.couleur)
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} | Total : {len(self.eligible_cars)} modèles")
        return embed

    async def display_car(self, interaction: discord.Interaction, idx_offset: int):
        if interaction.user != self.user: return await interaction.response.send_message("Pas ta recherche !", ephemeral=True)
        abs_index = self.current_page * self.items_per_page + idx_offset
        if abs_index >= len(self.eligible_cars): return await interaction.response.defer()
            
        voiture_choisie = self.eligible_cars[abs_index]
        nom_complet = get_nom_complet(voiture_choisie)
        
        membres_serveur_ids = [str(m.id) for m in self.ctx.guild.members]
        curseur = collection_inventaires.find({"garage": voiture_choisie["id"], "_id": {"$in": membres_serveur_ids}})
        docs = await curseur.to_list(length=100)
        proprietaires_mentions = [f"<@{doc['_id']}>" for doc in docs]
        texte_proprietaires = ", ".join(proprietaires_mentions) if proprietaires_mentions else "Personne ne possède ce bijou... 😢"

        rarete = voiture_choisie['rareté']
        mon_garage = self.profil.get("garage", []) if self.profil else []
        titre_possede = " ✅" if voiture_choisie["id"] in mon_garage else ""

        masse = voiture_choisie.get('masse_kg', 'Inconnu')
        lignes = [voiture_choisie['nom'], f"{LOGOS.get(voiture_choisie['marque'], '')}**{voiture_choisie['marque']}**"]
        if voiture_choisie.get('annee'): lignes.append(str(voiture_choisie['annee']))
        lignes.extend([voiture_choisie.get('pays', '🏁'), "", "**Rareté**", rarete, "", "**⚙️ Spécifications**", f"Moteur : {voiture_choisie.get('moteur', 'Inconnu')}", f"Puissance : {voiture_choisie.get('puissance', 'Inconnue')}", f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu", calculer_classe_forza(voiture_choisie), "", "**Propriétaires :**", texte_proprietaires])

        embed_voiture = discord.Embed(title=f"🔍 {nom_complet}{titre_possede}", description="\n".join(lignes), color=COULEURS_RARETE.get(rarete, discord.Color.green()))
        if voiture_choisie.get('image', '').startswith(('http://', 'https://')): embed_voiture.set_image(url=voiture_choisie['image'])
        await interaction.response.send_message(embed=embed_voiture)

    @discord.ui.button(label="1️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_1(self, interaction, button): await self.display_car(interaction, 0)
    @discord.ui.button(label="2️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_2(self, interaction, button): await self.display_car(interaction, 1)
    @discord.ui.button(label="3️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_3(self, interaction, button): await self.display_car(interaction, 2)
    @discord.ui.button(label="4️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_4(self, interaction, button): await self.display_car(interaction, 3)
    @discord.ui.button(label="5️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_5(self, interaction, button): await self.display_car(interaction, 4)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page -= 1; self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page += 1; self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.hybrid_command(name="search", description="Cherche un modèle précis, une marque, un pays ou une rareté.")
async def search(ctx, *, recherche: str):
    recherche_lower = recherche.lower().strip()
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})

    MOTS_RARETES = {"commun": "Commun ⚪", "rare": "Rare 🔵", "mythique": "Mythique 🟣", "legendaire": "Légendaire 🟡", "goat": "GOAT 🔴"}
    NOMS_PAYS = {"france": "🇫🇷", "allemagne": "🇩🇪", "italie": "🇮🇹", "royaume-uni": "🇬🇧", "japon": "🇯🇵", "usa": "🇺🇸"}

    resultats = []
    titre_recherche = f"🔍 Résultats pour : {recherche}"
    couleur_embed = discord.Color.teal()

    if recherche_lower in MOTS_RARETES:
        rc = MOTS_RARETES[recherche_lower]
        resultats = [v for v in VOITURES if v.get("rareté") == rc]
        titre_recherche = f"🔮 Modèles de rareté : {rc}"
    elif recherche_lower in NOMS_PAYS or any(recherche_lower == p for p in NOMS_PAYS.values()):
        dc = NOMS_PAYS.get(recherche_lower, recherche_lower)
        resultats = [v for v in VOITURES if dc in v.get("pays", "🏁")]
        titre_recherche = f"🌍 Modèles du pays : {dc}"
    elif any(v.get("marque", "").lower() == recherche_lower for v in VOITURES):
        resultats = [v for v in VOITURES if v.get("marque", "").lower() == recherche_lower]
        titre_recherche = f"Modèles de la marque : {resultats[0]['marque']}"
    else:
        recherche_nettoyee = re.sub(r'[^a-z0-9]', '', recherche_lower)
        for v in VOITURES:
            if recherche_nettoyee in re.sub(r'[^a-z0-9]', '', get_nom_complet(v).lower()): resultats.append(v)

    if not resultats: return await ctx.send(f"❌ Aucun résultat pour **{recherche}**.")
    resultats_tries = sorted(resultats, key=lambda x: (x.get('marque',''), x.get('nom','')))

    if len(resultats_tries) == 1:
        voiture_choisie = resultats_tries[0]
        nom_complet = get_nom_complet(voiture_choisie)
        membres_serveur_ids = [str(m.id) for m in ctx.guild.members]
        curseur = collection_inventaires.find({"garage": voiture_choisie["id"], "_id": {"$in": membres_serveur_ids}})
        docs = await curseur.to_list(length=100)
        
        proprietaires = ", ".join([f"<@{doc['_id']}>" for doc in docs]) if docs else "Personne... 😢"
        rarete = voiture_choisie.get('rareté', 'Commun ⚪')
        titre_possede = " ✅" if profil and voiture_choisie["id"] in profil.get("garage", []) else ""
        masse = voiture_choisie.get('masse_kg', 'Inconnu')
        
        lignes = [voiture_choisie['nom'], f"{LOGOS.get(voiture_choisie['marque'], '')}**{voiture_choisie['marque']}**"]
        if voiture_choisie.get('annee'): lignes.append(str(voiture_choisie['annee']))
        lignes.extend([voiture_choisie.get('pays', '🏁'), "", "**Rareté**", rarete, "", "**⚙️ Spécifications**", f"Moteur : {voiture_choisie.get('moteur', 'Inconnu')}", f"Puissance : {voiture_choisie.get('puissance', 'Inconnue')}", f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu", calculer_classe_forza(voiture_choisie), "", "**Propriétaires :**", proprietaires])

        embed = discord.Embed(title=f"🔍 {nom_complet}{titre_possede}", description="\n".join(lignes), color=COULEURS_RARETE.get(rarete, discord.Color.green()))
        if voiture_choisie.get('image', '').startswith(('http://', 'https://')): embed.set_image(url=voiture_choisie['image'])
        return await ctx.send(embed=embed)

    view = SearchResultView(ctx, ctx.author, resultats_tries, titre_recherche, couleur_embed, profil)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region catalogue
class CataloguePagination(discord.ui.View):
    def __init__(self, ctx, pages):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.bouton_prec.disabled = len(self.pages) <= 1
        self.bouton_suiv.disabled = len(self.pages) <= 1

    def get_embed(self):
        embed = discord.Embed(title="📖 Catalogue officiel du Garage", description=self.pages[self.current_page], color=discord.Color.dark_theme())
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} | Total : {len(VOITURES)} modèles")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, custom_id="cat_prec")
    async def bouton_prec(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        self.current_page = (self.current_page - 1) % len(self.pages); self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, custom_id="cat_suiv")
    async def bouton_suiv(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        self.current_page = (self.current_page + 1) % len(self.pages); self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.hybrid_command(name="catalogue", description="Affiche la liste complète des voitures disponibles.")
async def catalogue(ctx):
    if not VOITURES: return await ctx.send("Le catalogue est vide !")
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    mon_garage = profil.get("garage", []) if profil else []

    voitures_triees = sorted(VOITURES, key=lambda x: (x.get('marque', ''), x.get('nom', '')))
    lignes_catalogue = []
    for v in voitures_triees:
        possede = " ✅" if v["id"] in mon_garage else ""
        logo = LOGOS.get(v.get('marque', ''), "")
        lignes_catalogue.append(f"{logo} **{v.get('marque', '')}** {v.get('nom', '')} {v.get('annee', '')} - *{v.get('rareté', '')}*{possede}")

    pages = ["\n".join(lignes_catalogue[i:i + 15]) for i in range(0, len(lignes_catalogue), 15)]
    view = CataloguePagination(ctx, pages)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region favori
@bot.hybrid_command(name="fav", description="Définit ta marque favorite pour ton profil.")
async def fav(ctx, *, marque: str):
    marque_lower = marque.lower().strip()
    marque_trouvee = next((v.get("marque") for v in VOITURES if v.get("marque", "").lower() == marque_lower), None)
    if not marque_trouvee: return await ctx.send(f"❌ Marque introuvable : **{marque}**.")
    await collection_inventaires.update_one({"_id": str(ctx.author.id)}, {"$set": {"favorite_brand": marque_trouvee}}, upsert=True)
    await ctx.send(f"⭐ C'est noté ! Ta marque favorite est **{marque_trouvee}**.")
#endregion

def get_elo_rank(elo):
    if elo >= 1900:
        return f"{LOGOS.get('Ruby', '🔴')} **Ruby**"
    elif elo >= 1700:
        return f"{LOGOS.get('Diamant', '💎')} **Diamant**"
    elif elo >= 1500:
        return f"{LOGOS.get('Platine', '🟦')} **Platine**"
    elif elo >= 1300:
        return f"{LOGOS.get('Or', '🟨')} **Or**"
    elif elo >= 1100:
        return f"{LOGOS.get('Argent', '⬜')} **Argent**"
    else:
        return f"{LOGOS.get('Bronze', '🟫')} **Bronze**"

#region profil
@bot.hybrid_command(name="profil", description="Affiche la carte de joueur et les statistiques.")
async def profil(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    profil = await collection_inventaires.find_one({"_id": str(cible.id)})
    if not profil: return await ctx.send(f"❌ **{cible.display_name}** n'a pas encore de profil !")
        
    solde, elo, favorite_brand = profil.get("coins", 0), profil.get("elo", 1000), profil.get("favorite_brand")
    garage = profil.get("garage", [])
    
    valeur_totale = 0
    comptes = {"🔴": 0, "🟡": 0, "🟣": 0, "🔵": 0, "⚪": 0}
    compte_marque_fav = 0
    
    for vid in garage:
        info = VOITURES_BY_ID.get(vid, {})
        valeur_totale += PRIX_REVENTE.get(info.get("rareté", "Commun ⚪"), 50)
        emj = info.get("rareté", "Commun ⚪")[-1]
        if emj in comptes: comptes[emj] += 1
        if favorite_brand and info.get("marque") == favorite_brand: compte_marque_fav += 1
            
    details = " ".join([f"**{comptes[emj]}** {emj}" for emj in ["🔴", "🟡", "🟣", "🔵", "⚪"] if comptes[emj] > 0]) or "Aucune voiture"
    succes = profil.get("succes_marques", [])
    marques_totales = len(set(v.get("marque") for v in VOITURES if v.get("marque")))
    texte_succes = f"**{len(succes)}/{marques_totales}** marques"
    
    texte_favori = f"{LOGOS.get(favorite_brand, '')} **{favorite_brand}** ({compte_marque_fav} possédés)" if favorite_brand else "*Aucune marque (`!fav`)*"
        
    embed = discord.Embed(title=f"👤 Profil de {cible.display_name}", color=cible.color)
    if cible.avatar: embed.set_thumbnail(url=cible.avatar.url)
    embed.add_field(name="💰 Portefeuille", value=f"**{solde}** 🪙", inline=True)
    embed.add_field(name="💎 Valeur du Garage", value=f"**{valeur_totale}** 🪙", inline=True)
    embed.add_field(name="🏎️ Rang Compétitif", value=get_elo_rank(elo), inline=False)
    embed.add_field(name="📊 Score ELO", value=f"**{elo}** points", inline=True)
    embed.add_field(name="⭐ Marque Favorite", value=texte_favori, inline=False)
    embed.add_field(name="🚗 Collection", value=f"**{len(garage)}** véhicules\n*{details}*", inline=False)
    embed.add_field(name="🎖️ Succès Débloqués", value=texte_succes, inline=False)
    await ctx.send(embed=embed)
#endregion

#region commandes
@bot.hybrid_command(name="cmd", description="Affiche la liste de toutes les commandes du bot.", aliases=["commandes", "menu", "aide", "help"])
async def cmd(ctx):
    embed = discord.Embed(
        title="🛠️ Liste des commandes de Bouboule",
        description="Voici tout ce que je peux faire pour t'aider à bâtir le garage ultime :",
        color=discord.Color.blurple()
    )
    embed.add_field(name="🎰 Tirages, Souhaits & Suggestions", value="**`/roll`** : Tire une voiture au hasard toutes les heures (*`/timer`*).\n**`/buyroll`** : Achète un tirage immédiat (5000 🪙).\n**`/wish`** : Ajoute à ta wishlist.\n**`/unwish`** : Retire de ta wishlist.\n**`/wishlist`** : Affiche tes souhaits.\n**`/form`** : Suggère une voiture.", inline=False)
    embed.add_field(name="💰 Économie & Échanges", value="**`/daily`** : Salaire de 500 🪙/24h (*`/dtimer`*).\n**`/solde`** : Affiche l'argent.\n**`/sell`** : Vends une voiture.\n**`/sellall`** : Vend TOUT.\n**`/trade`** : Échange avec un joueur.\n**`/tradeup`** : Sacrifie 5 voitures pour 1 supérieure.", inline=False)
    embed.add_field(name="🚗 Gestion du Garage", value="**`/garage`** : Affiche ta collection.\n**`/sortrarity` / `/sortbrand` / `/sortyear` / `/sortpower` / `/sortclass`** : Trie ton garage.\n**`/search`** : Cherche un modèle.\n**`/catalogue`** : Affiche le catalogue.\n**`/fav`** : Mets en avant ta marque favorite.", inline=False)
    embed.add_field(name="🏁 Compétition & Classements", value="**`/profil`** : Affiche les stats.\n**`/toplist`** : Classements du serveur.\n**`/race`** : Provoque un joueur en duel.\n**`/ranks`** : Liste les grades.", inline=False)
    if bot.user.avatar: embed.set_thumbnail(url=bot.user.avatar.url)
    await ctx.send(embed=embed)
#endregion

#region timer
@bot.hybrid_command(name="timer", description="Affiche le temps restant avant ton prochain !roll gratuit.", aliases=["cd", "cooldown"])
async def timer(ctx):
    user_id = str(ctx.author.id)
    last_reset_ts, next_reset_ts, next_reset_dt = get_reset_timestamps()
    profil = await collection_inventaires.find_one({"_id": user_id})
    if not profil or "last_roll" not in profil or profil["last_roll"] < last_reset_ts: return await ctx.send(f"✅ C'est bon {ctx.author.mention}, ton tirage est prêt ! Fais `!roll`.")
    temps_restant = int(next_reset_ts - time.time())
    await ctx.send(f"⏳ Patience {ctx.author.mention} ! Prochain tirage à **{next_reset_dt.strftime('%Hh00')}** (dans {temps_restant // 3600}h et {(temps_restant % 3600) // 60}m).")
#endregion

#region dailytimer
@bot.hybrid_command(name="dailytimer", description="Affiche le temps restant avant ton prochain salaire.", aliases=["dtimer", "dailycd"])
async def dailytimer(ctx):
    profil = await collection_inventaires.find_one({"_id": str(ctx.author.id)})
    if not profil or "last_daily" not in profil: return await ctx.send(f"✅ Ton salaire est prêt ! Fais `!daily`.")
    temps_ecoule = time.time() - profil["last_daily"]
    if temps_ecoule < 72000:
        temps_restant = int(72000 - temps_ecoule)
        await ctx.send(f"⏳ Patience ! Prochain salaire dans **{temps_restant // 3600}h et {(temps_restant % 3600) // 60}m**.")
    else: await ctx.send(f"✅ Ton salaire est prêt ! Fais `!daily`.")
#endregion

#region argent
@bot.hybrid_command(name="solde", description="Affiche l'argent en banque d'un joueur.", aliases=["bal", "argent"])
async def solde(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    profil = await collection_inventaires.find_one({"_id": str(cible.id)})
    await ctx.send(f"💳 Le solde de **{cible.display_name}** est de **{profil.get('coins', 0) if profil else 0} 🪙**.")

@bot.hybrid_command(name="daily", description="Récupère ton salaire de 500 pièces toutes les 24h.")
async def daily(ctx):
    user_id = str(ctx.author.id)
    maintenant = time.time()
    profil = await collection_inventaires.find_one({"_id": user_id})
    if profil and "last_daily" in profil and maintenant - profil["last_daily"] < 72000:
        tr = int(72000 - (maintenant - profil["last_daily"]))
        return await ctx.send(f"⏳ Reviens dans **{tr // 3600}h et {(tr % 3600) // 60}m**.")
    await collection_inventaires.update_one({"_id": user_id}, {"$inc": {"coins": 500}, "$set": {"last_daily": maintenant}}, upsert=True)
    n_profil = await collection_inventaires.find_one({"_id": user_id})
    await ctx.send(f"💸 Bien joué {ctx.author.mention} ! Tu as récupéré **500 🪙** (Solde : {n_profil.get('coins', 500)} 🪙).")
#endregion

#region buyroll
@bot.hybrid_command(name="buyroll", description="Achète un tirage supplémentaire immédiat pour 5000 pièces.")
async def buyroll(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    solde = profil.get("coins", 0) if profil else 0
    if solde < 5000: return await ctx.send(f"❌ Désolé {ctx.author.mention}, il te manque **{5000 - solde} 🪙** !")

    voitures_possedees_ids = profil.get("garage", []) if profil else []
    wishlist_joueur_ids = profil.get("wishlist", []) if profil else []
    marque_favorite = profil.get("favorite_brand") if profil else None
    
    voitures_disponibles, poids_disponibles = [], []
    for voiture in VOITURES:
        if voiture["id"] not in voitures_possedees_ids:
            voitures_disponibles.append(voiture)
            p = voiture.get("poids", 10) * (1.5 if marque_favorite == voiture.get('marque') else 1) * (2 if voiture["id"] in wishlist_joueur_ids else 1)
            poids_disponibles.append(p)

    if not voitures_disponibles: return await ctx.send(f"🏆 Tu possèdes déjà **TOUTES** les voitures du jeu !")

    voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
    voitures_possedees_ids.append(voiture_gagnee["id"])
    if profil and profil.get("sort_preference"): voitures_possedees_ids = appliquer_tri_garage(voitures_possedees_ids, profil.get("sort_preference"))

    update_query = {"$set": {"garage": voitures_possedees_ids}, "$inc": {"coins": -5000}}
    if voiture_gagnee["id"] in wishlist_joueur_ids: update_query["$pull"] = {"wishlist": voiture_gagnee["id"]}
    await collection_inventaires.update_one({"_id": user_id}, update_query)

    curseur = collection_inventaires.find({"garage": voiture_gagnee["id"], "_id": {"$in": [str(m.id) for m in ctx.guild.members]}})
    docs = await curseur.to_list(length=100)
    proprietaires_mentions = ", ".join([f"<@{doc['_id']}>" for doc in docs]) or f"<@{user_id}>"

    rarete = voiture_gagnee['rareté']
    masse = voiture_gagnee.get('masse_kg', 'Inconnu')
    lignes = [voiture_gagnee['nom'], f"{LOGOS.get(voiture_gagnee['marque'], '')} **{voiture_gagnee['marque']}**"]
    if voiture_gagnee.get('annee'): lignes.append(str(voiture_gagnee['annee']))
    lignes.extend([voiture_gagnee.get('pays', '🏁'), "", "**Rareté**", rarete, "", "**⚙️ Spécifications**", f"Moteur : {voiture_gagnee.get('moteur', 'Inconnu')}", f"Puissance : {voiture_gagnee.get('puissance', 'Inconnue')}", f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu", calculer_classe_forza(voiture_gagnee), "", "**Propriétaires :**", proprietaires_mentions, "", f"💸 *Nouveau solde : {solde - 5000} 🪙*"])

    embed = discord.Embed(title=f"🎰 Vous avez eu : {get_nom_complet(voiture_gagnee)}", description="\n".join(lignes), color=COULEURS_RARETE.get(rarete, discord.Color.purple()))
    image_url = (voiture_gagnee.get('image') or '').strip()
    if image_url.startswith(('http://', 'https://')): embed.set_image(url=image_url)

    voeu_exauce = "\n🌟 **VŒU EXAUCÉ !** Retirée de la wishlist." if voiture_gagnee["id"] in wishlist_joueur_ids else ("\n⭐ **BINGO !** Ta marque favorite !" if marque_favorite == voiture_gagnee.get('marque') else "")
    await ctx.send(content=f"{ctx.author.mention} **Bien joué !**{voeu_exauce}", embed=embed)
    await verifier_succes_marque(ctx, user_id, voiture_gagnee.get('marque'))
#endregion

#region leaderboard
@bot.hybrid_command(name="toplist", description="Affiche le classement officiel du serveur.", aliases=["top", "lb", "classement"])
async def toplist(ctx):
    membres_serveur_ids = [str(membre.id) for membre in ctx.guild.members]
    profils = await collection_inventaires.find({"_id": {"$in": membres_serveur_ids}}).to_list(length=1000)
    if not profils: return await ctx.send("❌ Aucun joueur n'est enregistré ici !")

    for profil in profils:
        profil["valeur_garage"] = sum(PRIX_REVENTE.get(VOITURES_BY_ID.get(vid, {}).get("rareté"), 50) for vid in profil.get("garage", []))

    top_coins = sorted(profils, key=lambda x: x.get("coins", 0), reverse=True)[:10]
    top_garage = sorted(profils, key=lambda x: len(x.get("garage", [])), reverse=True)[:10]
    top_valeur = sorted(profils, key=lambda x: x.get("valeur_garage", 0), reverse=True)[:10]
    top_elo = sorted(profils, key=lambda x: x.get("elo", 1000), reverse=True)[:10]

    texte_coins = "".join([f"**{i}.** <@{p['_id']}> : **{p.get('coins', 0)}** 🪙\n" for i, p in enumerate(top_coins, 1) if p.get('coins', 0) > 0]) or "Tout le monde est fauché ! 💸\n"
    
    texte_garage = ""
    for i, p in enumerate(top_garage, 1):
        if len(p.get("garage", [])) > 0:
            c = Counter(VOITURES_BY_ID.get(vid, {}).get("rareté", "Commun ⚪")[-1] for vid in p["garage"])
            d = " ".join([f"**{c[emj]}** {emj}" for emj in ["🔴", "🟡", "🟣", "🔵", "⚪"] if c[emj] > 0])
            texte_garage += f"**{i}.** <@{p['_id']}> : **{len(p['garage'])}** 🚗 *({d})*\n"
    if not texte_garage: texte_garage = "Garages vides ! 🚶‍♂️\n"

    texte_valeur = "".join([f"**{i}.** <@{p['_id']}> : **{p.get('valeur_garage', 0)}** 💎\n" for i, p in enumerate(top_valeur, 1) if p.get('valeur_garage', 0) > 0]) or "Aucun patrimoine ! 📉\n"
    texte_elo = "".join([f"**{i}.** {get_elo_rank(p.get('elo', 1000)).split('**')[0].strip()} <@{p['_id']}> : **{p.get('elo', 1000)}**\n" for i, p in enumerate(top_elo, 1) if p.get('elo', 1000) > 1000]) or "Personne n'a de score Elo ! 🛣️\n"

    embed = discord.Embed(title=f"🏆 Classement Officiel - {ctx.guild.name}", color=discord.Color.gold())
    embed.add_field(name="💰 Top Richesse", value=texte_coins, inline=False)
    embed.add_field(name="🏁 Top Pilotes (Elo)", value=texte_elo, inline=False)
    embed.add_field(name="🚗 Top Collection", value=texte_garage, inline=False)
    embed.add_field(name="💎 Valeur Garage", value=texte_valeur, inline=False)
    if ctx.guild.icon: embed.set_thumbnail(url=ctx.guild.icon.url)
    await ctx.send(embed=embed)
#endregion

#region wishlist
class WishSelectionView(discord.ui.View):
    def __init__(self, ctx, user, eligible_cars, profil, titre="🌟 Gestion de la Wishlist"):
        super().__init__(timeout=120)
        self.ctx, self.user, self.eligible_cars, self.profil, self.titre = ctx, user, eligible_cars, profil, titre
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, math.ceil(len(eligible_cars) / self.items_per_page))
        self.number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        self.update_buttons()

    def update_buttons(self):
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page >= self.total_pages - 1)
        wishlist = self.profil.get("wishlist", [])
        for i, btn in enumerate([self.btn_1, self.btn_2, self.btn_3, self.btn_4, self.btn_5]):
            idx = self.current_page * self.items_per_page + i
            if idx >= len(self.eligible_cars): btn.disabled, btn.style = True, discord.ButtonStyle.secondary
            else:
                btn.disabled = False
                btn.style = discord.ButtonStyle.success if self.eligible_cars[idx]["id"] in wishlist else discord.ButtonStyle.primary

    def get_embed(self):
        start = self.current_page * self.items_per_page
        page_items = self.eligible_cars[start:start + self.items_per_page]
        wishlist, garage = self.profil.get("wishlist", []), self.profil.get("garage", [])
        
        lignes = []
        for i, v in enumerate(page_items):
            etat = " 🌟 *(Dans la wishlist)*" if v["id"] in wishlist else (" ✅ *(Déjà possédé)*" if v["id"] in garage else "")
            lignes.append(f"{self.number_emojis[i]} {LOGOS.get(v.get('marque', ''), '')} **{v.get('marque', '')}** {v.get('nom', '')} {v.get('annee', '')} ({v.get('rareté', '')}){etat}")
            
        embed = discord.Embed(title=self.titre, description="Clique sur un numéro pour l'ajouter/retirer :\n\n" + "\n".join(lignes), color=discord.Color.gold())
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} | Ta wishlist : {len(wishlist)}/10")
        return embed

    async def toggle_wishlist(self, interaction: discord.Interaction, idx_offset: int):
        if interaction.user != self.user: return await interaction.response.send_message("Pas pour toi !", ephemeral=True)
        idx = self.current_page * self.items_per_page + idx_offset
        if idx >= len(self.eligible_cars): return await interaction.response.defer()
            
        voiture_choisie = self.eligible_cars[idx]
        self.profil = await collection_inventaires.find_one({"_id": str(self.user.id)}) or {}
        wishlist, garage = self.profil.get("wishlist", []), self.profil.get("garage", [])
        
        if voiture_choisie["id"] in garage: return await interaction.response.send_message(f"❌ Déjà possédé !", ephemeral=True)
            
        if voiture_choisie["id"] in wishlist:
            await collection_inventaires.update_one({"_id": str(self.user.id)}, {"$pull": {"wishlist": voiture_choisie["id"]}})
            self.profil["wishlist"].remove(voiture_choisie["id"])
            await interaction.response.send_message(f"🗑️ Retirée de la wishlist.", ephemeral=True)
        else:
            if len(wishlist) >= 10: return await interaction.response.send_message(f"❌ Wishlist pleine (10/10) !", ephemeral=True)
            await collection_inventaires.update_one({"_id": str(self.user.id)}, {"$push": {"wishlist": voiture_choisie["id"]}}, upsert=True)
            if "wishlist" not in self.profil: self.profil["wishlist"] = []
            self.profil["wishlist"].append(voiture_choisie["id"])
            await interaction.response.send_message(f"🌟 Ajoutée à ta wishlist !", ephemeral=True)

        self.update_buttons()
        await interaction.message.edit(embed=self.get_embed(), view=self)

    @discord.ui.button(label="1️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_1(self, interaction, button): await self.toggle_wishlist(interaction, 0)
    @discord.ui.button(label="2️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_2(self, interaction, button): await self.toggle_wishlist(interaction, 1)
    @discord.ui.button(label="3️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_3(self, interaction, button): await self.toggle_wishlist(interaction, 2)
    @discord.ui.button(label="4️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_4(self, interaction, button): await self.toggle_wishlist(interaction, 3)
    @discord.ui.button(label="5️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_5(self, interaction, button): await self.toggle_wishlist(interaction, 4)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page -= 1; self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page += 1; self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.hybrid_command(name="wish", description="Ajoute une voiture à ta liste de souhaits.")
async def wish(ctx, *, recherche: str):
    user_id = str(ctx.author.id)
    recherche_nettoyee = re.sub(r'[^a-z0-9]', '', recherche.lower().strip())
    
    resultats = [v for v in VOITURES if recherche_nettoyee in re.sub(r'[^a-z0-9]', '', get_nom_complet(v).lower())]
    if not resultats: return await ctx.send(f"❌ Aucune correspondance pour **{recherche}**.")
        
    profil = await collection_inventaires.find_one({"_id": user_id}) or {}
    if len(resultats) == 1:
        voiture_choisie = resultats[0]
        if voiture_choisie["id"] in profil.get("garage", []): return await ctx.send(f"❌ Tu possèdes déjà la **{get_nom_complet(voiture_choisie)}** !")
        if voiture_choisie["id"] in profil.get("wishlist", []): return await ctx.send(f"⚠️ Déjà dans ta wishlist !")
        if len(profil.get("wishlist", [])) >= 10: return await ctx.send(f"❌ Wishlist pleine (10/10).")
        await collection_inventaires.update_one({"_id": user_id}, {"$push": {"wishlist": voiture_choisie["id"]}}, upsert=True)
        return await ctx.send(f"🌟 **{get_nom_complet(voiture_choisie)}** ajoutée (chances x2).")

    view = WishSelectionView(ctx, ctx.author, sorted(resultats, key=lambda x: (x.get('marque',''), x.get('nom',''))), profil, titre="🌟 Ajout à la Wishlist")
    await ctx.send(embed=view.get_embed(), view=view)

@bot.hybrid_command(name="unwish", description="Retire une voiture de ta liste de souhaits.")
async def unwish(ctx, *, recherche: Optional[str] = None):
    profil = await collection_inventaires.find_one({"_id": str(ctx.author.id)}) or {}
    wishlist_ids = profil.get("wishlist", [])
    if not wishlist_ids: return await ctx.send("❌ Wishlist déjà vide !")
        
    voitures_wishlist = [VOITURES_BY_ID[vid] for vid in wishlist_ids if vid in VOITURES_BY_ID]
            
    if recherche:
        recherche_nettoyee = re.sub(r'[^a-z0-9]', '', recherche.lower().strip())
        resultats = [v for v in voitures_wishlist if recherche_nettoyee in re.sub(r'[^a-z0-9]', '', get_nom_complet(v).lower())]
        if not resultats: return await ctx.send(f"❌ Rien trouvé pour **{recherche}**.")
        if len(resultats) == 1:
            await collection_inventaires.update_one({"_id": str(ctx.author.id)}, {"$pull": {"wishlist": resultats[0]["id"]}})
            return await ctx.send(f"🗑️ **{get_nom_complet(resultats[0])}** retirée.")
        voitures_a_afficher = resultats
    else: voitures_a_afficher = voitures_wishlist
        
    view = WishSelectionView(ctx, ctx.author, sorted(voitures_a_afficher, key=lambda x: (x.get('marque',''), x.get('nom',''))), profil, titre="🗑️ Retrait de la Wishlist")
    await ctx.send(embed=view.get_embed(), view=view)

@bot.hybrid_command(name="wishlist", description="Affiche ta liste de souhaits en cours.", aliases=["wl", "wishlists"])
async def wishlist(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    profil = await collection_inventaires.find_one({"_id": str(cible.id)})
    wishlist_ids = profil.get("wishlist", []) if profil else []
    if not wishlist_ids: return await ctx.send(f"📭 Wishlist de {cible.display_name} vide.")
        
    description = ""
    for i, vid in enumerate(wishlist_ids, 1):
        v = VOITURES_BY_ID.get(vid)
        if v: description += f"**{i}.** {LOGOS.get(v.get('marque', ''), '')} {get_nom_complet(v)} - *{v.get('rareté', '')}*\n"
        else: description += f"**{i}.** Voiture ID {vid} introuvable\n"
            
    embed = discord.Embed(title=f"🌟 Wishlist de {cible.display_name} ({len(wishlist_ids)}/10)", description=description, color=discord.Color.gold())
    await ctx.send(embed=embed)
#endregion

#region ranks
@bot.hybrid_command(name="ranks", description="Affiche la liste des rangs compétitifs.", aliases=["elos"])
async def ranks(ctx):
    description = (
        f"{LOGOS.get('Ruby', '🔴')} **Ruby** : 1900 Elo et +\n\n"
        f"{LOGOS.get('Diamant', '💎')} **Diamant** : 1700 - 1899 Elo\n\n"
        f"{LOGOS.get('Platine', '🟦')} **Platine** : 1500 - 1699 Elo\n\n"
        f"{LOGOS.get('Or', '🟨')} **Or** : 1300 - 1499 Elo\n\n"
        f"{LOGOS.get('Argent', '⬜')} **Argent** : 1100 - 1299 Elo\n\n"
        f"{LOGOS.get('Bronze', '🟫')} **Bronze** : 0 - 1099 Elo"
    )
    embed = discord.Embed(title="🏁 Rangs Compétitifs", description=description, color=discord.Color.red())
    await ctx.send(embed=embed)
#endregion

#region race
def obtenir_ratio(vid):
    voiture = VOITURES_BY_ID.get(vid)
    if not voiture: return 10.0 
    puissance_str = voiture.get('puissance', '')
    masse_str = str(voiture.get('masse_kg', ''))
    puissance = None
    if puissance_str and puissance_str.lower() not in ["inconnu", "inconnue"]:
        nombres_p = re.findall(r'\d+', puissance_str.replace(' ', ''))
        if nombres_p: puissance = int(nombres_p[0])
    masse = None
    if masse_str and masse_str.lower() not in ["inconnu", "inconnue"]:
        nombres_m = re.findall(r'\d+', masse_str.replace(' ', ''))
        if nombres_m: masse = int(nombres_m[0])
    if not puissance or not masse or puissance == 0: return 10.0 
    return masse / puissance

class RaceSelectionView(discord.ui.View):
    def __init__(self, ctx, user, eligible_cars_ids, titre):
        super().__init__(timeout=60)
        self.ctx, self.user, self.eligible_cars_ids, self.titre = ctx, user, eligible_cars_ids, titre
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, math.ceil(len(eligible_cars_ids) / self.items_per_page))
        self.number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        self.selected_car_id = None
        self.update_buttons()

    def update_buttons(self):
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page >= self.total_pages - 1)
        for i, btn in enumerate([self.btn_1, self.btn_2, self.btn_3, self.btn_4, self.btn_5]):
            if (self.current_page * self.items_per_page + i) >= len(self.eligible_cars_ids): btn.disabled, btn.style = True, discord.ButtonStyle.secondary
            else: btn.disabled, btn.style = False, discord.ButtonStyle.primary

    def get_embed(self):
        start = self.current_page * self.items_per_page
        page_items = self.eligible_cars_ids[start:start + self.items_per_page]
        lignes = []
        for i, vid in enumerate(page_items):
            voiture_info = VOITURES_BY_ID.get(vid)
            nom = get_nom_complet(voiture_info)
            if voiture_info:
                lignes.append(f"{self.number_emojis[i]} **{nom}**\n> ⚙️ *{voiture_info.get('puissance', '?')} | {voiture_info.get('masse_kg', '?')} kg (Ratio: {round(obtenir_ratio(vid), 2)})*")
            else: lignes.append(f"{self.number_emojis[i]} **{nom}**")
            
        embed = discord.Embed(title=self.titre, description="Clique sur le numéro :\n\n" + "\n".join(lignes), color=discord.Color.orange())
        return embed

    async def select_item(self, interaction: discord.Interaction, idx_offset: int):
        if interaction.user != self.user: return await interaction.response.send_message("Pas à toi de jouer !", ephemeral=True)
        idx = self.current_page * self.items_per_page + idx_offset
        if idx < len(self.eligible_cars_ids):
            self.selected_car_id = self.eligible_cars_ids[idx]
            for child in self.children: child.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()

    @discord.ui.button(label="1️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_1(self, interaction, button): await self.select_item(interaction, 0)
    @discord.ui.button(label="2️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_2(self, interaction, button): await self.select_item(interaction, 1)
    @discord.ui.button(label="3️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_3(self, interaction, button): await self.select_item(interaction, 2)
    @discord.ui.button(label="4️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_4(self, interaction, button): await self.select_item(interaction, 3)
    @discord.ui.button(label="5️⃣", style=discord.ButtonStyle.primary, row=0)
    async def btn_5(self, interaction, button): await self.select_item(interaction, 4)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page -= 1; self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page += 1; self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.hybrid_command(name="race", description="Provoque un joueur en duel.")
async def race(ctx, membre: discord.Member, montant: int, classe_voulue: str):
    classe_voulue = classe_voulue.upper().strip()
    valid_classes = ["D", "C", "B", "A", "S1", "S2", "X"]
    if classe_voulue not in valid_classes: return await ctx.send(f"❌ Classe invalide !")
    if ctx.author == membre: return await ctx.send("❌ Pas contre toi-même !")
    if montant <= 0: return await ctx.send("❌ Mise > 0 🪙.")

    user_id, target_id = str(ctx.author.id), str(membre.id)
    profil_user = await collection_inventaires.find_one({"_id": user_id}) or {}
    profil_target = await collection_inventaires.find_one({"_id": target_id}) or {}

    solde_user, solde_target = profil_user.get("coins", 0), profil_target.get("coins", 0)
    if solde_user < montant: return await ctx.send(f"❌ Il te manque **{montant - solde_user} 🪙**.")
    if solde_target < montant: return await ctx.send(f"❌ {membre.display_name} n'a pas assez (Solde: {solde_target} 🪙).")
    
    def filter_cars_by_class(garage_ids, cls):
        result = []
        for vid in set(garage_ids):
            v_info = VOITURES_BY_ID.get(vid)
            if v_info and obtenir_nom_classe_simple(v_info) == cls: result.append(vid)
        result.sort(key=lambda vid: obtenir_ratio(vid))
        return result

    voitures_a = filter_cars_by_class(profil_user.get("garage", []), classe_voulue)
    voitures_b = filter_cars_by_class(profil_target.get("garage", []), classe_voulue)

    if not voitures_a: return await ctx.send(f"❌ Aucune voiture Classe {classe_voulue} dans ton garage !")
    if not voitures_b: return await ctx.send(f"❌ {membre.display_name} n'a aucune voiture Classe {classe_voulue}.")

    view_a = RaceSelectionView(ctx, ctx.author, voitures_a, f"🏁 Choix de {ctx.author.display_name}")
    msg_select_a = await ctx.send(f"{ctx.author.mention}, choisis ta monture :", embed=view_a.get_embed(), view=view_a)
    await view_a.wait()
    if not view_a.selected_car_id: return await ctx.send("⏳ Temps écoulé, course annulée.")
    
    ma_voiture_id = view_a.selected_car_id
    nom_ma_voiture = get_nom_complet(VOITURES_BY_ID.get(ma_voiture_id))
    try: await msg_select_a.delete()
    except: pass

    msg_invite = await ctx.send(f"🏁 **DÉFI RACING !** 🏁\n{membre.mention}, {ctx.author.mention} te provoque en Classe **{classe_voulue}** pour **{montant} 🪙** !\nIl pilote sa **{nom_ma_voiture}**.\n✅ Accepter | ❌ Refuser")
    await msg_invite.add_reaction("✅"); await msg_invite.add_reaction("❌")
    def check_reaction(reaction, user): return user == membre and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg_invite.id
    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=45.0, check=check_reaction)
        if str(reaction.emoji) == "❌": return await ctx.send(f"💨 {membre.display_name} a refusé.")
        try: await msg_invite.delete()
        except: pass
    except asyncio.TimeoutError: return await ctx.send("⏳ Défi expiré.")

    view_b = RaceSelectionView(ctx, membre, voitures_b, f"🔥 Choix de {membre.display_name}")
    msg_select_b = await ctx.send(f"{membre.mention}, choisis ta voiture :", embed=view_b.get_embed(), view=view_b)
    await view_b.wait()
    if not view_b.selected_car_id: return await ctx.send("⏳ Trop lent ! Course annulée.")
    
    sa_voiture_id = view_b.selected_car_id
    nom_sa_voiture = get_nom_complet(VOITURES_BY_ID.get(sa_voiture_id))
    try: await msg_select_b.delete()
    except: pass

    vitesse_base_a = max(1.0, min(12.0, 15.0 - obtenir_ratio(ma_voiture_id)))
    vitesse_base_b = max(1.0, min(12.0, 15.0 - obtenir_ratio(sa_voiture_id)))

    pos_a, pos_b, tour = 0.0, 0.0, 0
    phrase_intro = random.choice(PHRASES_INTRO)
    dernier_commentaire = phrase_intro

    def generer_piste(pos, pseudo, voiture, emoji_voiture):
        pos_int = min(int(pos), 20)
        return f"**{pseudo}** ({voiture})\n🏁{'➖' * (20 - pos_int)}{emoji_voiture}{'➖' * pos_int}🟩"

    course_msg = await ctx.send(phrase_intro)
    await asyncio.sleep(2)
    
    while pos_a < 20 and pos_b < 20 and tour < 30:
        pos_a += (vitesse_base_a / 4.0) + random.uniform(0.1, 0.8)
        pos_b += (vitesse_base_b / 4.0) + random.uniform(0.1, 0.8)

        if tour > 0 and tour % 3 == 0:
            dernier_commentaire = f"🎙️ *{random.choice(PHRASES_RACE).format(pseudo=random.choice([ctx.author.display_name, membre.display_name]))}*"

        embed = discord.Embed(title=f"🚨 COURSE EN COURS (Classe {classe_voulue}) 🚨", description=f"{generer_piste(pos_a, ctx.author.display_name, nom_ma_voiture, '🏎️')}\n\n{generer_piste(pos_b, membre.display_name, nom_sa_voiture, '🚙')}\n\n{dernier_commentaire}", color=discord.Color.orange())
        await course_msg.edit(content=None, embed=embed)
        tour += 1
        await asyncio.sleep(1.2)

    vainqueur_id, perdant_id = (user_id, target_id) if pos_a >= pos_b else (target_id, user_id)
    gagnant, perdant = (ctx.author, membre) if pos_a >= pos_b else (membre, ctx.author)

    elo_user, elo_target = profil_user.get("elo", 1000), profil_target.get("elo", 1000)
    esp_user = 1 / (1 + 10 ** ((elo_target - elo_user) / 400))
    esp_target = 1 / (1 + 10 ** ((elo_user - elo_target) / 400))

    if vainqueur_id == user_id:
        nouveau_elo_user, nouveau_elo_target = max(0, int(elo_user + 45 * (1 - esp_user))), max(0, int(elo_target + 15 * (0 - esp_target)))
    else:
        nouveau_elo_user, nouveau_elo_target = max(0, int(elo_user + 15 * (0 - esp_user))), max(0, int(elo_target + 45 * (1 - esp_target)))

    await collection_inventaires.update_one({"_id": user_id}, {"$inc": {"coins": montant if vainqueur_id == user_id else -montant}, "$set": {"elo": nouveau_elo_user}})
    await collection_inventaires.update_one({"_id": target_id}, {"$inc": {"coins": montant if vainqueur_id == target_id else -montant}, "$set": {"elo": nouveau_elo_target}})

    embed_fin = discord.Embed(
        title="🏆 ARRIVÉE ! 🏆", 
        description=(
            f"{generer_piste(pos_a, ctx.author.display_name, nom_ma_voiture, '🏎️')}\n"
            f"📈 {get_elo_rank(nouveau_elo_user)} : **{nouveau_elo_user}** Elo ({'+' if nouveau_elo_user >= elo_user else ''}{nouveau_elo_user - elo_user})\n\n"
            f"{generer_piste(pos_b, membre.display_name, nom_sa_voiture, '🚙')}\n"
            f"📉 {get_elo_rank(nouveau_elo_target)} : **{nouveau_elo_target}** Elo ({'+' if nouveau_elo_target >= elo_target else ''}{nouveau_elo_target - elo_target})\n\n"
            f"{random.choice(PHRASES_VICTOIRE).format(gagnant=gagnant.display_name)}\n"
            f"💰 **{gagnant.mention} rafle {montant * 2} 🪙 !**"
        ), color=discord.Color.green())
    embed_fin.set_footer(text=f"{perdant.display_name} rentre avec -{montant} 🪙...")
    await course_msg.edit(embed=embed_fin)

@race.error
async def race_error(ctx, error):
    if isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send(f"❌ **Syntaxe:** `/race @pseudo <montant> <Classe>`")
#endregion

#region suggestions_voitures
ADMIN_ID = "320606002837979157"
@bot.hybrid_command(name="form", description="Laisse une suggestion de voiture à ajouter au bot.")
async def form(ctx, marque: str, modele: Optional[str] = None, annee: Optional[str] = None):
    suggestion = {
        "user_id": str(ctx.author.id), "auteur": str(ctx.author),
        "marque": marque.strip(), "modele": modele.strip() if modele else "", "annee": annee.strip() if annee else "",
        "date": datetime.utcnow()
    }
    await collection_suggestions.insert_one(suggestion)
    
    affichage_voiture = f"**{marque.strip()}**" + (f" {modele.strip()}" if modele else "") + (f" ({annee.strip()})" if annee else "")
    embed = discord.Embed(title="📝 Suggestion enregistrée !", description=f"Merci {ctx.author.mention} ! La suggestion pour {affichage_voiture} a bien été ajoutée.", color=discord.Color.brand_green())
    await ctx.send(embed=embed)

@bot.hybrid_command(name="forms", description="Affiche la liste des voitures suggérées.")
async def forms(ctx):
    suggestions = await collection_suggestions.find().sort("date", -1).limit(20).to_list(length=20)
    if not suggestions: return await ctx.send("📭 Aucune suggestion de voiture.")

    lignes = [f"**{i}.** **{s['marque']}**{f' {s['modele']}' if s.get('modele') else ''}{f' ({s['annee']})' if s.get('annee') else ''} — *suggéré par <@{s['user_id']}>*" for i, s in enumerate(suggestions, 1)]
    embed = discord.Embed(title="📋 Suggestions de voitures", description="\n".join(lignes), color=discord.Color.blue())
    embed.set_footer(text="Utilise /clearforms pour vider.")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="clearforms", description="Efface toutes les suggestions (Admin).")
async def clearforms(ctx):
    if str(ctx.author.id) != ADMIN_ID: return await ctx.send("❌ Interdit !")
    await collection_suggestions.delete_many({})
    await ctx.send("🗑️ Toutes les suggestions effacées.")
#endregion

# 4. Lancement
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
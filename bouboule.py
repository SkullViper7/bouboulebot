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

with open('cars.json', 'r', encoding='utf-8') as f:
    VOITURES = json.load(f)

# --- Faux Serveur Web pour Render ---
app = Flask('')
@app.route('/')
def home():
    return "Bot en ligne !"

def run_web():
    # Render utilise la variable d'environnement PORT, sinon 8080 par défaut
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# 3. Configuration du Bot Discord
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
#endregion

bot = commands.Bot(command_prefix="!", intents=intents)

# --- NOUVEAU : Événement de démarrage ---
@bot.event
async def on_ready():
    print("="*30)
    print(f"✅ CONNECTÉ AVEC SUCCÈS !")
    print(f"🤖 Nom du bot : {bot.user.name}")
    print(f"🆔 ID du bot  : {bot.user.id}")
    print("="*30)

# --- ÉCONOMIE ---
PRIX_REVENTE = {
    "Commun ⚪": 100,
    "Rare 🔵": 500,
    "Mythique 🟣": 2500,
    "Légendaire 🟡": 5000,
    "GOAT 🔴": 20000
}
# --- COULEURS DES RARETÉS ---
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
    
    heure_dernier_reset = (now.hour // 4) * 4
    heure_prochain_reset = heure_dernier_reset + 4
    
    last_reset = now.replace(hour=heure_dernier_reset, minute=0, second=0, microsecond=0)
    
    if heure_prochain_reset == 24:
        next_reset = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        next_reset = now.replace(hour=heure_prochain_reset, minute=0, second=0, microsecond=0)
        
    return last_reset.timestamp(), next_reset.timestamp(), next_reset
#endregion

#region succes
async def verifier_succes_marque(ctx, user_id, marque):
    voitures_de_la_marque = [
        f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() 
        for v in VOITURES if v['marque'] == marque
    ]
    
    if len(voitures_de_la_marque) < 2:
        return
    
    profil = await collection_inventaires.find_one({"_id": str(user_id)})
    if not profil:
        return
        
    succes_debloques = profil.get("succes_marques", [])
    if marque in succes_debloques:
        return 
        
    garage = profil.get("garage", [])
    
    possede_toutes = all(voiture in garage for voiture in voitures_de_la_marque)
    
    if possede_toutes:
        recompense = len(voitures_de_la_marque) * 1000 
        
        await collection_inventaires.update_one(
            {"_id": str(user_id)},
            {
                "$push": {"succes_marques": marque},
                "$inc": {"coins": recompense}
            }
        )
        
        embed = discord.Embed(
            title="🏆 NOUVEAU SUCCÈS DÉBLOQUÉ !",
            description=f"Incroyable ! <@{user_id}> vient de collectionner **absolument tous** les modèles de la marque **{marque}** !\n\n🎁 **Bonus de collectionnneur : +{recompense} 🪙**",
            color=discord.Color.brand_green()
        )
        await ctx.send(embed=embed)
#endregion

#region sort
def appliquer_tri_garage(garage, preference):
    if not preference:
        return garage
        
    voiture_map = {f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip(): v for v in VOITURES}
    
    if preference == "rarity":
        ordre_rarete = {"GOAT 🔴": 1, "Légendaire 🟡": 2, "Mythique 🟣": 3, "Rare 🔵": 4, "Commun ⚪": 5}
        garage.sort(key=lambda x: (
            ordre_rarete.get(voiture_map.get(x, {}).get("rareté", "Commun ⚪"), 99),
            voiture_map.get(x, {}).get("marque", ""),
            voiture_map.get(x, {}).get("nom", "")
        ))
    elif preference == "brand":
        garage.sort(key=lambda x: (
            voiture_map.get(x, {}).get("marque", ""),
            voiture_map.get(x, {}).get("nom", "")
        ))
    elif preference == "year":
        def get_year(nom_voiture):
            try: return int(voiture_map.get(nom_voiture, {}).get("annee", ""))
            except ValueError: return 9999
        garage.sort(key=lambda x: (
            get_year(x),
            voiture_map.get(x, {}).get("marque", ""),
            voiture_map.get(x, {}).get("nom", "")
        ))
    elif preference == "power":
        def get_power(nom_voiture):
            puissance_str = voiture_map.get(nom_voiture, {}).get("puissance", "")
            if not puissance_str or puissance_str.lower() in ["inconnu", "inconnue"]:
                return -1 
            nombres = re.findall(r'\d+', puissance_str.replace(' ', ''))
            if not nombres:
                return -1
            return int(nombres[0])
            
        garage.sort(key=lambda x: (
            -get_power(x),
            voiture_map.get(x, {}).get("marque", ""),
            voiture_map.get(x, {}).get("nom", "")
        ))
    elif preference == "class":
        def get_ratio(nom_voiture):
            voiture = voiture_map.get(nom_voiture, {})
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
                    
            if not puissance or not masse or puissance == 0:
                return 999.0 # On met un ratio énorme pour que les "Inconnus" finissent tout en bas
                
            return masse / puissance

        # Tri croissant (du plus petit ratio kg/ch au plus grand)
        garage.sort(key=lambda x: (
            get_ratio(x),
            voiture_map.get(x, {}).get("marque", ""),
            voiture_map.get(x, {}).get("nom", "")
        ))
        
    return garage

@bot.command(aliases=["sortr", "trierrarte", "trier_rarete"])
async def sortrarity(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
        return
        
    garage = appliquer_tri_garage(profil["garage"], "rarity")
    
    await collection_inventaires.update_one(
        {"_id": user_id}, 
        {"$set": {"garage": garage, "sort_preference": "rarity"}}
    )
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par rareté** (du plus rare au plus commun). Fais `!garage` pour admirer.")

@bot.command(aliases=["sortb", "triermarque", "trier_marque"])
async def sortbrand(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
        return
        
    garage = appliquer_tri_garage(profil["garage"], "brand")
    
    await collection_inventaires.update_one(
        {"_id": user_id}, 
        {"$set": {"garage": garage, "sort_preference": "brand"}}
    )
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par ordre alphabétique des marques**. Fais `!garage` pour admirer.")

@bot.command(aliases=["sorty", "trierannee", "trier_annee"])
async def sortyear(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
        return
        
    garage = appliquer_tri_garage(profil["garage"], "year")
    
    await collection_inventaires.update_one(
        {"_id": user_id}, 
        {"$set": {"garage": garage, "sort_preference": "year"}}
    )
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par ordre chronologique**. Fais `!garage` pour admirer l'évolution automobile !")

@bot.command(aliases=["sortp", "trierpuissance", "trier_puissance"])
async def sortpower(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
        return
        
    garage = appliquer_tri_garage(profil["garage"], "power")
    
    await collection_inventaires.update_one(
        {"_id": user_id}, 
        {"$set": {"garage": garage, "sort_preference": "power"}}
    )
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par ordre de puissance (du plus au moins puissant)**. Fais `!garage` pour admirer tes monstres !")

@bot.command(aliases=["sortc", "trierclasse", "trier_classe", "sortratio"])
async def sortclass(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est vide, {ctx.author.mention} ! Rien à trier.")
        return
        
    garage = appliquer_tri_garage(profil["garage"], "class")
    
    await collection_inventaires.update_one(
        {"_id": user_id}, 
        {"$set": {"garage": garage, "sort_preference": "class"}}
    )
    await ctx.send(f"✨ Garage trié avec succès {ctx.author.mention} ! Tes véhicules sont classés **par classe de performance (du meilleur ratio Poids/Puissance au pire)**. Fais `!garage` pour admirer l'élite de ta collection !")
#endregion

#region grade
def obtenir_nom_classe_simple(voiture):
    """Retourne juste 'D', 'C', 'B', 'A', 'S1', 'S2' ou 'X'"""
    # On réutilise la logique de calcul de ratio
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
            
    if not puissance or not masse or puissance == 0:
        return None
        
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
    
    # 1. Extraction de la puissance (en ch)
    puissance = None
    if puissance_str and puissance_str.lower() not in ["inconnu", "inconnue"]:
        nombres_p = re.findall(r'\d+', puissance_str.replace(' ', ''))
        if nombres_p:
            puissance = int(nombres_p[0])
            
    # 2. Extraction de la masse (en kg)
    masse = None
    if masse_str and masse_str.lower() not in ["inconnu", "inconnue"]:
        nombres_m = re.findall(r'\d+', masse_str.replace(' ', ''))
        if nombres_m:
            masse = int(nombres_m[0])
            
    # Si l'une des deux données manque, on ne peut pas calculer le ratio
    if not puissance or not masse or puissance == 0:
        return LOGOS.get("Classe Inconnue", "❓ Non classé")
        
    # 3. Calcul du Rapport Poids/Puissance (kg/ch)
    # Plus le ratio est bas, meilleure est l'accélération
    ratio = masse / puissance
    
    # 4. Barème inversé (basé sur le kg/ch)
    if ratio >= 10.0: 
        return LOGOS.get("Classe D", "🟩 **Classe D**")
    elif ratio >= 7.0: 
        return LOGOS.get("Classe C", "🟦 **Classe C**")
    elif ratio >= 4.5: 
        return LOGOS.get("Classe B", "🟪 **Classe B**")
    elif ratio >= 3.0: 
        return LOGOS.get("Classe A", "🟧 **Classe A**")
    elif ratio >= 2.0: 
        return LOGOS.get("Classe S1", "🟥 **Classe S1**")
    elif ratio >= 1.2: 
        return LOGOS.get("Classe S2", "💎 **Classe S2**")
    else: 
        return LOGOS.get("Classe X", "👑 **Classe X**")
#endregion

#region roll
@bot.command()
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

    voitures_possedees = profil.get("garage", []) if profil else []
    wishlist_joueur = profil.get("wishlist", []) if profil else []
    voitures_disponibles = []
    poids_disponibles = []

    for voiture in VOITURES:
        nom_complet = f"{voiture['marque']} {voiture['nom']} {voiture.get('annee', '')}".strip()
        if nom_complet not in voitures_possedees:
            voitures_disponibles.append(voiture)
            poids_base = voiture.get("poids", 10)
            
            if nom_complet in wishlist_joueur:
                poids_disponibles.append(poids_base * 2)
            else:
                poids_disponibles.append(poids_base)

    if not voitures_disponibles:
        await ctx.send(f"🏆 Incroyable {ctx.author.mention}, tu possèdes déjà **TOUTES** les voitures du jeu ! Attends une mise à jour.")
        return

    voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
    nom_complet_gagnee = f"{voiture_gagnee['marque']} {voiture_gagnee['nom']} {voiture_gagnee.get('annee', '')}".strip()
    print(f"[LOG 🎰] {ctx.author.name} a obtenu : {nom_complet_gagnee}")

    rarete = voiture_gagnee['rareté']
    prix_base = PRIX_REVENTE.get(rarete, 50)
    bonus_coins = int(prix_base * 0.20) 

    maintenant = time.time()
    
    # NOUVEAU : Application du tri automatique sur le nouveau garage
    sort_preference = profil.get("sort_preference") if profil else None
    voitures_possedees.append(nom_complet_gagnee)
    
    if sort_preference:
        voitures_possedees = appliquer_tri_garage(voitures_possedees, sort_preference)
    
    update_query = {
        "$set": {
            "garage": voitures_possedees,
            "last_roll": maintenant
        },
        "$inc": {"coins": bonus_coins}
    }
    
    if nom_complet_gagnee in wishlist_joueur:
        update_query["$pull"] = {"wishlist": nom_complet_gagnee}

    await collection_inventaires.update_one(
        {"_id": user_id},
        update_query,
        upsert=True
    )

    curseur = collection_inventaires.find({"garage": nom_complet_gagnee})
    docs = await curseur.to_list(length=100)
    proprietaires_mentions = [f"<@{doc['_id']}>" for doc in docs]
    texte_proprietaires = ", ".join(proprietaires_mentions) if proprietaires_mentions else f"<@{user_id}>"

    classe_forza = calculer_classe_forza(voiture_gagnee)
    masse = voiture_gagnee.get('masse_kg', 'Inconnu')
    logo = LOGOS.get(voiture_gagnee['marque'], "")
    lignes = [
        voiture_gagnee['nom'],
        f"{logo} **{voiture_gagnee['marque']}**"
    ]
    if voiture_gagnee.get('annee'):
        lignes.append(str(voiture_gagnee['annee']))
    lignes.append(voiture_gagnee.get('pays', '🏁'))
    lignes.append("")
    lignes.append("**Rareté**")
    lignes.append(rarete)
    lignes.append("")
    lignes.append("**⚙️ Spécifications**")
    lignes.append(f"Moteur : {voiture_gagnee.get('moteur', 'Inconnu')}")
    lignes.append(f"Puissance : {voiture_gagnee.get('puissance', 'Inconnue')}")
    lignes.append(f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu")
    lignes.append(classe_forza)
    lignes.append("")
    lignes.append("**Propriétaires :**")
    lignes.append(texte_proprietaires)
    lignes.append("")
    lignes.append(f"🎁 *Bonus de drop : +{bonus_coins} 🪙*")

    couleur_dynamique = COULEURS_RARETE.get(rarete, discord.Color.gold())
    
    embed = discord.Embed(
        title=f"🎰 Vous avez eu : {nom_complet_gagnee}", 
        description="\n".join(lignes),
        color=couleur_dynamique
    )

    img_url = voiture_gagnee.get('image', '')
    if img_url and img_url.startswith(('http://', 'https://')):
        embed.set_image(url=img_url)
    else:
        embed.add_field(name="⚠️ Image indisponible", value="Le lien de cette image doit être corrigé dans le catalogue.", inline=False)

    messages_rarete = {
        "Commun ⚪": "Ouais basique",
        "Rare 🔵": "Eh pas mal",
        "Mythique 🟣": "Eh beh mon salaud",
        "Légendaire 🟡": "Oh pétard",
        "GOAT 🔴": "WAAAAAAAA"
    }
    phrase = messages_rarete.get(rarete, "Bien joué")
    
    voeu_exauce = ""
    if nom_complet_gagnee in wishlist_joueur:
        voeu_exauce = "\n\n🌟 **VŒU EXAUCÉ !** Cette voiture était dans ta wishlist, elle a été retirée de la liste."

    await verifier_succes_marque(ctx, user_id, voiture_gagnee['marque'])
    await ctx.send(content=f"{ctx.author.mention} **{phrase} !**{voeu_exauce}", embed=embed)

@roll.error
async def roll_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        minutes_restantes = int(error.retry_after // 60)
        await ctx.send(f"⏳ Doucement {ctx.author.mention} ! Trop de commandes en même temps.")
#endregion

#region garage
from typing import Union
import collections

class GaragePagination(discord.ui.View):
    # NOUVEAU : On ajoute l'argument `start_page`
    def __init__(self, ctx, pages, total_voitures, target_member, solde, start_page=0):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.total_voitures = total_voitures
        self.target_member = target_member
        self.solde = solde 
        
        # Sécurité : on s'assure que la page demandée n'est pas hors limites (négative ou trop grande)
        self.current_page = max(0, min(start_page, len(self.pages) - 1)) if self.pages else 0
        
        self.update_buttons()

    def update_buttons(self):
        self.bouton_prec.disabled = len(self.pages) <= 1
        self.bouton_suiv.disabled = len(self.pages) <= 1

    def get_embed(self):
        voiture = self.pages[self.current_page]
        rarete = voiture['rareté']
        couleur_dynamique = COULEURS_RARETE.get(rarete, discord.Color.blue())
        
        classe_forza = calculer_classe_forza(voiture)
        masse = voiture.get('masse_kg', 'Inconnu')
        logo = LOGOS.get(voiture['marque'], "")
        lignes = [
            voiture['nom'],
            f"{logo} **{voiture['marque']}**"
        ]
        if voiture.get('annee'):
            lignes.append(str(voiture['annee']))
        lignes.append(voiture.get('pays', '🏁'))
        lignes.append("")
        lignes.append("**Rareté**")
        lignes.append(rarete)
        lignes.append("")
        lignes.append("**⚙️ Spécifications**")
        lignes.append(f"Moteur : {voiture.get('moteur', 'Inconnu')}")
        lignes.append(f"Puissance : {voiture.get('puissance', 'Inconnue')}")
        lignes.append(f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu")
        lignes.append(classe_forza)
        lignes.append("")
        lignes.append(f"💳 *Solde : {self.solde} 🪙*")
        
        embed = discord.Embed(
            title=f"🚗 Le Garage de {self.target_member.display_name}", 
            description="\n".join(lignes), 
            color=couleur_dynamique
        )
        
        img_url = voiture.get('image', '')
        if img_url and img_url.startswith(('http://', 'https://')):
            embed.set_image(url=img_url)
        else:
            embed.add_field(name="⚠️ Image indisponible", value="Le lien de l'image est invalide ou cassé.", inline=False)
            
        embed.set_footer(text=f"Modèle {self.current_page + 1}/{len(self.pages)} | Total : {self.total_voitures} voitures")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, custom_id="prec")
    async def bouton_prec(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("Ce n'est pas toi qui as demandé à voir ce garage !", ephemeral=True)
            return
            
        self.current_page = (self.current_page - 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, custom_id="suiv")
    async def bouton_suiv(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("Ce n'est pas toi qui as demandé à voir ce garage !", ephemeral=True)
            return
            
        self.current_page = (self.current_page + 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

# NOUVEAU : La commande détecte automatiquement un Membre ET/OU un Nombre
@bot.command()
async def garage(ctx, cible_ou_page: Union[discord.Member, int] = None, page_demandee: int = None):
    # Variables par défaut
    cible = ctx.author
    page_cible = 1
    
    # Analyse de ce qu'a tapé l'utilisateur
    if isinstance(cible_ou_page, discord.Member):
        cible = cible_ou_page
        if page_demandee is not None:
            page_cible = page_demandee
    elif isinstance(cible_ou_page, int):
        page_cible = cible_ou_page
    
    user_id = str(cible.id)
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    solde = profil.get("coins", 0) if profil else 0
    
    if not profil or not profil.get("garage"):
        embed_vide = discord.Embed(
            title=f"🚗 Le Garage de {cible.display_name}", 
            description=f"💳 *Solde : {solde} 🪙*\n\nCe garage est complètement vide pour le moment ! Fais un `!roll`.", 
            color=discord.Color.light_grey()
        )
        await ctx.send(embed=embed_vide)
        return
    
    mes_voitures = profil["garage"]
    inventaire_compte = collections.Counter(mes_voitures)
    
    pages_voitures = []
    
    vus = set()
    for nom_complet in mes_voitures:
        if nom_complet in vus:
            continue
        vus.add(nom_complet)
        
        quantite = inventaire_compte[nom_complet]
        voiture_info = next((v for v in VOITURES if f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() == nom_complet), None)
        
        if voiture_info:
            pages_voitures.append({
                "nom": voiture_info["nom"],
                "marque": voiture_info["marque"],
                "annee": voiture_info.get("annee", ""),
                "pays": voiture_info.get("pays", "🏁"),
                "quantite": quantite, 
                "image": voiture_info["image"],
                "rareté": voiture_info["rareté"],
                # --- LA CORRECTION EST ICI ---
                "moteur": voiture_info.get("moteur", "Inconnu"),
                "puissance": voiture_info.get("puissance", "Inconnue"),
                "masse_kg": voiture_info.get("masse_kg", "Inconnu")
            })
        else:
            pages_voitures.append({
                "nom": nom_complet,
                "marque": "Inconnue",
                "annee": "",
                "pays": "🏴‍☠️",
                "quantite": quantite,
                "image": None,
                "rareté": "Inconnue",
                # --- ET ICI ---
                "moteur": "Inconnu",
                "puissance": "Inconnue",
                "masse_kg": "Inconnu"
            })
            
    # L'index Python commence à 0 (Page 1 = Index 0)
    index_depart = page_cible - 1
            
    view = GaragePagination(ctx, pages_voitures, len(mes_voitures), cible, solde, start_page=index_depart)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region trade
@bot.command()
async def trade(ctx, membre: discord.Member, ma_voiture: str, sa_voiture: str):
    if ctx.author == membre:
        await ctx.send("Tu ne peux pas faire un échange avec toi-même !")
        return

    user_id = str(ctx.author.id)
    target_id = str(membre.id)

    profil_user = await collection_inventaires.find_one({"_id": user_id})
    profil_target = await collection_inventaires.find_one({"_id": target_id})

    if not profil_user or ma_voiture not in profil_user.get("garage", []):
        await ctx.send(f"❌ Tu ne possèdes pas la voiture **{ma_voiture}** !")
        return
    if not profil_target or sa_voiture not in profil_target.get("garage", []):
        await ctx.send(f"❌ {membre.display_name} ne possède pas la voiture **{sa_voiture}** !")
        return

    def trouver_info(nom_complet_recherche):
        return next((v for v in VOITURES if f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() == nom_complet_recherche), None)

    info_ma = trouver_info(ma_voiture)
    info_sa = trouver_info(sa_voiture)

    if not info_ma or not info_sa:
        await ctx.send("❌ Erreur : Impossible de retrouver les informations de ces voitures dans le catalogue.")
        return

    prix_ma = PRIX_REVENTE.get(info_ma["rareté"], 50)
    prix_sa = PRIX_REVENTE.get(info_sa["rareté"], 50)

    diff = abs(prix_ma - prix_sa)
    solde_user = profil_user.get("coins", 0)
    solde_target = profil_target.get("coins", 0)
    
    payeur_id = None
    msg_compensation = "\n⚖️ **Échange équitable** (Même rareté) : Aucun argent ne sera échangé."

    if prix_ma > prix_sa:
        if solde_target < diff:
            await ctx.send(f"❌ **Échange annulé** : {membre.mention} n'a pas assez d'argent pour compenser la différence de valeur. Il lui manque **{diff - solde_target} 🪙** !")
            return
        payeur_id = target_id
        msg_compensation = f"\n⚠️ **Compensation financière :** {membre.display_name} devra payer la différence de **{diff} 🪙** à {ctx.author.display_name}."

    elif prix_sa > prix_ma:
        if solde_user < diff:
            await ctx.send(f"❌ **Échange annulé** : {ctx.author.mention} n'a pas assez d'argent pour compenser la différence de valeur. Il te manque **{diff - solde_user} 🪙** !")
            return
        payeur_id = user_id
        msg_compensation = f"\n⚠️ **Compensation financière :** {ctx.author.display_name} devra payer la différence de **{diff} 🪙** à {membre.display_name}."

    msg = await ctx.send(f"Hey {membre.mention} ! {ctx.author.mention} te propose d'échanger sa **{ma_voiture}** contre ta **{sa_voiture}**.{msg_compensation}\n\n*Réagis avec ✅ pour accepter ou ❌ pour refuser.*")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    def check(reaction, user):
        return user == membre and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
        
        if str(reaction.emoji) == "✅":
            garage_user = profil_user["garage"]
            garage_target = profil_target["garage"]

            garage_user.remove(ma_voiture)
            garage_target.remove(sa_voiture)
            garage_user.append(sa_voiture)
            garage_target.append(ma_voiture)

            # NOUVEAU : On re-trie les garages des deux joueurs après l'échange
            pref_user = profil_user.get("sort_preference")
            pref_target = profil_target.get("sort_preference")
            
            if pref_user: garage_user = appliquer_tri_garage(garage_user, pref_user)
            if pref_target: garage_target = appliquer_tri_garage(garage_target, pref_target)

            update_user = {"$set": {"garage": garage_user}}
            update_target = {"$set": {"garage": garage_target}}

            if diff > 0:
                if payeur_id == user_id:
                    update_user["$inc"] = {"coins": -diff}
                    update_target["$inc"] = {"coins": diff}
                else:
                    update_user["$inc"] = {"coins": diff}
                    update_target["$inc"] = {"coins": -diff}

            await collection_inventaires.update_one({"_id": user_id}, update_user)
            await collection_inventaires.update_one({"_id": target_id}, update_target)

            await ctx.send(f"🎉 **Échange réussi** entre {ctx.author.mention} et {membre.mention} ! Les garages (et les portefeuilles) ont été mis à jour.")
            await verifier_succes_marque(ctx, user_id, info_sa['marque'])
            await verifier_succes_marque(ctx, target_id, info_ma['marque'])
        else:
            await ctx.send(f"❌ {membre.display_name} a refusé l'échange.")

    except asyncio.TimeoutError:
        await ctx.send(f"⏳ Temps écoulé, l'échange proposé par {ctx.author.mention} est annulé.")
#endregion

#region sell
@bot.command(aliases=["jeter", "poubelle", "vendre"])
async def sell(ctx, *, recherche: str):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})

    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est complètement vide, {ctx.author.mention} !")
        return

    garage = profil["garage"]
    recherche_lower = recherche.lower().strip()

    voitures_trouvees = [v for v in garage if recherche_lower in v.lower()]

    if not voitures_trouvees:
        await ctx.send(f"❌ Tu ne possèdes aucune voiture correspondant à **{recherche}** !")
        return

    if len(voitures_trouvees) > 1:
        liste_conflits = "\n".join([f"• {v}" for v in voitures_trouvees[:5]]) 
        if len(voitures_trouvees) > 5:
            liste_conflits += "\n..."
        await ctx.send(f"⚠️ {ctx.author.mention}, sois plus précis ! J'ai trouvé plusieurs voitures dans ton garage qui correspondent :\n{liste_conflits}")
        return

    voiture_exacte = voitures_trouvees[0]

    voiture_info = next((v for v in VOITURES if f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() == voiture_exacte), None)
    
    if not voiture_info:
        await ctx.send("❌ Erreur : Cette voiture n'existe plus dans le catalogue.")
        return
        
    rarete = voiture_info["rareté"]
    prix_vente = PRIX_REVENTE.get(rarete, 50)

    msg = await ctx.send(f"⚠️ {ctx.author.mention}, veux-tu vendre ta **{voiture_exacte}** ?\nLe concessionnaire t'en offre **{prix_vente} 🪙**.\n\n*Réagis avec ✅ pour vendre ou ❌ pour annuler.*")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=30.0, check=check)
        
        if str(reaction.emoji) == "✅":
            garage.remove(voiture_exacte) 

            await collection_inventaires.update_one(
                {"_id": user_id},
                {
                    "$set": {"garage": garage},
                    "$inc": {"coins": prix_vente}
                }
            )

            await ctx.send(f"💵 Vente conclue {ctx.author.mention} ! Tu as gagné **{prix_vente} 🪙** en vendant ta {voiture_exacte}.")
        else:
            await ctx.send(f"❌ Vente annulée. Tu gardes ta **{voiture_exacte}**.")

    except asyncio.TimeoutError:
        await ctx.send(f"⏳ Temps écoulé, la vente est annulée.")
#endregion

#region search
class SearchPagination(discord.ui.View):
    def __init__(self, ctx, pages, titre, couleur):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.pages = pages
        self.titre = titre
        self.couleur = couleur
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.bouton_prec.disabled = len(self.pages) <= 1
        self.bouton_suiv.disabled = len(self.pages) <= 1

    def get_embed(self):
        embed = discord.Embed(
            title=self.titre, 
            description=self.pages[self.current_page], 
            color=self.couleur
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)}")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, custom_id="search_prec")
    async def bouton_prec(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Tu n'es pas l'auteur de cette recherche !", ephemeral=True)
            
        self.current_page = (self.current_page - 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, custom_id="search_suiv")
    async def bouton_suiv(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Tu n'es pas l'auteur de cette recherche !", ephemeral=True)
            
        self.current_page = (self.current_page + 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.command()
async def search(ctx, *, recherche: str):
    recherche_lower = recherche.lower().strip()
    
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    mon_garage = profil.get("garage", []) if profil else []

    MOTS_RARETES = {
        "commun": "Commun ⚪", "commune": "Commun ⚪", "blanc": "Commun ⚪",
        "rare": "Rare 🔵", "bleu": "Rare 🔵",
        "mythique": "Mythique 🟣", "violet": "Mythique 🟣",
        "legendaire": "Légendaire 🟡", "légendaire": "Légendaire 🟡", "jaune": "Légendaire 🟡",
        "goat": "GOAT 🔴", "rouge": "GOAT 🔴"
    }
    
    NOMS_PAYS_RECHERCHE = {
        "france": "🇫🇷", "fr": "🇫🇷", "allemagne": "🇩🇪", "de": "🇩🇪", "italie": "🇮🇹", "it": "🇮🇹",
        "royaume-uni": "🇬🇧", "angleterre": "🇬🇧", "uk": "🇬🇧", "gb": "🇬🇧",
        "suede": "🇸🇪", "suède": "🇸🇪", "se": "🇸🇪", "espagne": "🇪🇸", "es": "🇪🇸",
        "tchequie": "🇨🇿", "cz": "🇨🇿", "roumanie": "🇷🇴", "ro": "🇷🇴", "russie": "🇷🇺", "ru": "🇷🇺",
        "japon": "🇯🇵", "jp": "🇯🇵", "coree": "🇰🇷", "kr": "🇰🇷", "chine": "🇨🇳", "cn": "🇨🇳",
        "usa": "🇺🇸", "etats-unis": "🇺🇸", "etats unis": "🇺🇸", "amerique": "🇺🇸", "us": "🇺🇸",
        "autriche": "🇦🇹", "at": "🇦🇹", "croatie": "🇭🇷", "hr": "🇭🇷", "danemark": "🇩🇰", "dk": "🇩🇰",
        "ile de man": "🇮🇲", "im": "🇮🇲", "serbie": "🇷🇸", "rs": "🇷🇸", "australie": "🇦🇺", "au": "🇦🇺",
        "pays-bas": "🇳🇱", "pays bas": "🇳🇱", "hollande": "🇳🇱", "nl": "🇳🇱",
        "emirats": "🇦🇪", "ae": "🇦🇪",
        "belgique": "🇧🇪", "be": "🇧🇪",
        "irlande": "🇮🇪", "ie": "🇮🇪",
        "maroc": "🇲🇦", "ma": "🇲🇦",
        "canada": "🇨🇦", "ca": "🇨🇦",
        "argentine": "🇦🇷", "ar": "🇦🇷",
        "chili": "🇨🇱", "cl": "🇨🇱",
        "turquie": "🇹🇷", "tr": "🇹🇷",
        "pologne": "🇵🇱", "pl": "🇵🇱",
        "israel": "🇮🇱", "israël": "🇮🇱", "il": "🇮🇱",
        "mexique": "🇲🇽", "mx": "🇲🇽",
        "bresil": "🇧🇷", "brésil": "🇧🇷", "br": "🇧🇷",
        "lituanie": "🇱🇹", "lt": "🇱🇹",
        "slovenie": "🇸🇮", "slovénie": "🇸🇮", "si": "🇸🇮",
        "portugal": "🇵🇹", "pt": "🇵🇹",
        "finlande": "🇫🇮", "fi": "🇫🇮",
        "norvege": "🇳🇴", "norvège": "🇳🇴", "no": "🇳🇴",
        
        # Spécial
        "cinema": "🎬", "film": "🎬", "serie": "🎬",
        "jeu": "🎮", "jeux": "🎮", "jeux video": "🎮", "jeu video": "🎮",
        "pirate": "🏴‍☠️", "inconnu": "🏴‍☠️"
    }

    resultats = []
    titre_recherche = ""
    couleur_embed = discord.Color.blue()

    if recherche_lower in MOTS_RARETES:
        rarete_cible = MOTS_RARETES[recherche_lower]
        resultats = [v for v in VOITURES if v["rareté"] == rarete_cible]
        titre_recherche = f"🔮 Modèles de rareté : {rarete_cible}"
        couleur_embed = COULEURS_RARETE.get(rarete_cible, discord.Color.blue())

    elif recherche_lower in NOMS_PAYS_RECHERCHE or any(recherche_lower == p for p in NOMS_PAYS_RECHERCHE.values()):
        drapeau_cible = NOMS_PAYS_RECHERCHE.get(recherche_lower, recherche_lower)
        resultats = [v for v in VOITURES if drapeau_cible in v.get("pays", "🏁")]
        titre_recherche = f"🌍 Modèles du pays : {drapeau_cible}"
        couleur_embed = discord.Color.green()

    elif any(v["marque"].lower() == recherche_lower for v in VOITURES):
        resultats = [v for v in VOITURES if v["marque"].lower() == recherche_lower]
        titre_recherche = f"Modèles de la marque : {resultats[0]['marque']}"
        couleur_embed = discord.Color.orange()

    if resultats:
        resultats_tries = sorted(resultats, key=lambda x: (x.get('marque',''), x.get('nom','')))
        
        lignes = []
        for v in resultats_tries:
            nom_complet = f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip()
            possede = " ✅" if nom_complet in mon_garage else ""
            
            logo = LOGOS.get(v['marque'], "")
            
            lignes.append(f"• {logo} **{v['marque']}** {v['nom']} {v.get('annee', '')} ({v['rareté']}) {v.get('pays', '🏁')}{possede}")

        lignes_par_page = 15
        pages = []
        for i in range(0, len(lignes), lignes_par_page):
            pages.append("\n".join(lignes[i:i + lignes_par_page]))
        
        if len(pages) == 1:
            embed = discord.Embed(title=titre_recherche, description=pages[0], color=couleur_embed)
            embed.set_footer(text=f"Total : {len(resultats)} modèles")
            await ctx.send(embed=embed)
        else:
            view = SearchPagination(ctx, pages, titre_recherche, couleur_embed)
            await ctx.send(embed=view.get_embed(), view=view)
        return

    modele_trouve = next((v for v in VOITURES if recherche_lower in f"{v['marque']} {v['nom']} {v.get('annee', '')}".lower()), None)

    if modele_trouve:
        nom_complet = f"{modele_trouve['marque']} {modele_trouve['nom']} {modele_trouve.get('annee', '')}".strip()
        
        curseur = collection_inventaires.find({"garage": nom_complet})
        docs = await curseur.to_list(length=100)
        
        proprietaires_mentions = [f"<@{doc['_id']}>" for doc in docs]
        texte_proprietaires = ", ".join(proprietaires_mentions) if proprietaires_mentions else "Personne ne possède ce bijou... 😢"

        rarete = modele_trouve['rareté']
        couleur_dynamique = COULEURS_RARETE.get(rarete, discord.Color.green())
        
        titre_possede = " ✅" if nom_complet in mon_garage else ""

        classe_forza = calculer_classe_forza(modele_trouve)
        masse = modele_trouve.get('masse_kg', 'Inconnu')
        logo = LOGOS.get(modele_trouve['marque'], "")
        
        lignes = [
            modele_trouve['nom'],
            f"{logo}**{modele_trouve['marque']}**"
        ]
        if modele_trouve.get('annee'):
            lignes.append(str(modele_trouve['annee']))
        lignes.append(modele_trouve.get('pays', '🏁'))
        lignes.append("")
        lignes.append("**Rareté**")
        lignes.append(rarete)
        lignes.append("")
        lignes.append("**⚙️ Spécifications**")
        lignes.append(f"Moteur : {modele_trouve.get('moteur', 'Inconnu')}")
        lignes.append(f"Puissance : {modele_trouve.get('puissance', 'Inconnue')}")
        lignes.append(f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu")
        lignes.append(classe_forza)
        lignes.append("")
        lignes.append("**Propriétaires :**")
        lignes.append(texte_proprietaires)

        embed = discord.Embed(
            title=f"🔍 {nom_complet}{titre_possede}", 
            description="\n".join(lignes),
            color=couleur_dynamique
        )
    
        img_url = modele_trouve.get('image', '')
        if img_url and img_url.startswith(('http://', 'https://')):
            embed.set_image(url=img_url)
        else:
            embed.add_field(name="⚠️ Image indisponible", value="Le lien de cette image doit être corrigé dans le catalogue.", inline=False)

        await ctx.send(embed=embed)
        return

    await ctx.send(f"❌ Je n'ai trouvé aucun pays, rareté, marque ni modèle correspondant à **{recherche}**.")
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
        embed = discord.Embed(
            title="📖 Catalogue officiel du Garage", 
            description=self.pages[self.current_page], 
            color=discord.Color.dark_theme()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} | Total : {len(VOITURES)} modèles disponibles")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, custom_id="cat_prec")
    async def bouton_prec(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Tu n'es pas l'auteur de cette commande !", ephemeral=True)
            
        self.current_page = (self.current_page - 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, custom_id="cat_suiv")
    async def bouton_suiv(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Tu n'es pas l'auteur de cette commande !", ephemeral=True)
            
        self.current_page = (self.current_page + 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.command(aliases=["catalog", "liste", "voitures"])
async def catalogue(ctx):
    if not VOITURES:
        await ctx.send("Le catalogue est vide pour le moment !")
        return

    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    mon_garage = profil.get("garage", []) if profil else []

    voitures_triees = sorted(VOITURES, key=lambda x: (x['marque'], x['nom']))
    
    lignes_catalogue = []
    for v in voitures_triees:
        nom_complet = f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip()
        possede = " ✅" if nom_complet in mon_garage else ""
        
        logo = LOGOS.get(v['marque'], "")
        lignes_catalogue.append(f"{logo} **{v['marque']}** {v['nom']} {v.get('annee', '')} - *{v['rareté']}*{possede}")

    lignes_par_page = 15
    pages = []
    for i in range(0, len(lignes_catalogue), lignes_par_page):
        morceau = "\n".join(lignes_catalogue[i:i + lignes_par_page])
        pages.append(morceau)
        
    view = CataloguePagination(ctx, pages)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region favori
@bot.command(aliases=["favori", "favorite", "marque"])
async def fav(ctx, *, marque: str):
    user_id = str(ctx.author.id)
    marque_lower = marque.lower().strip()

    # On vérifie si la marque existe bien dans notre catalogue
    marque_trouvee = None
    for v in VOITURES:
        if v["marque"].lower() == marque_lower:
            marque_trouvee = v["marque"] # On récupère le nom avec la bonne majuscule
            break

    if not marque_trouvee:
        await ctx.send(f"❌ Je ne connais aucune marque nommée **{marque}** dans le catalogue.")
        return

    # On enregistre la marque dans le profil du joueur
    await collection_inventaires.update_one(
        {"_id": user_id},
        {"$set": {"favorite_brand": marque_trouvee}},
        upsert=True
    )

    logo = LOGOS.get(marque_trouvee, "")
    affichage_logo = f"{logo}" if logo else ""
    
    await ctx.send(f"⭐ C'est noté ! Ta marque favorite est maintenant {affichage_logo} **{marque_trouvee}**.")
#endregion

#region profil
@bot.command(aliases=["profile", "stats", "statistiques", "me"])
async def profil(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    user_id = str(cible.id)
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil:
        await ctx.send(f"❌ **{cible.display_name}** n'a pas encore de profil. Fais un `!roll` pour commencer l'aventure !")
        return
        
    # 1. Récupération de l'argent et de la marque favorite
    solde = profil.get("coins", 0)
    elo = profil.get("elo", 1000)
    rank_full_display = get_elo_rank(elo)
    favorite_brand = profil.get("favorite_brand")
    
    # 2. Préparation du dictionnaire pour calculer la valeur, les raretés et les marques
    infos_voitures = {}
    for v in VOITURES:
        nom_complet = f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip()
        infos_voitures[nom_complet] = {
            "prix": PRIX_REVENTE.get(v['rareté'], 50),
            "emoji": v['rareté'][-1],
            "marque": v['marque'] # On stocke la marque pour le calcul du favori
        }
        
    # 3. Analyse du garage
    garage = profil.get("garage", [])
    taille_garage = len(garage)
    valeur_totale = 0
    comptes = {"🔴": 0, "🟡": 0, "🟣": 0, "🔵": 0, "⚪": 0}
    compte_marque_fav = 0
    
    for nom in garage:
        info = infos_voitures.get(nom, {})
        valeur_totale += info.get("prix", 50)
        
        # On compte les raretés
        emoji = info.get("emoji", "⚪")
        if emoji in comptes:
            comptes[emoji] += 1
            
        # NOUVEAU : On compte si c'est la marque favorite
        if favorite_brand and info.get("marque") == favorite_brand:
            compte_marque_fav += 1
            
    # Formatage de la ligne des raretés
    details = []
    for emj in ["🔴", "🟡", "🟣", "🔵", "⚪"]:
        if comptes[emj] > 0:
            details.append(f"**{comptes[emj]}** {emj}")
            
    details_str = " ".join(details) if details else "Aucune voiture"
    
    # 4. Analyse des succès
    succes = profil.get("succes_marques", [])
    
    # On calcule le nombre total de marques uniques existantes dans le jeu
    marques_totales = len(set(v["marque"] for v in VOITURES))
    
    if succes:
        texte_succes = f"**{len(succes)}/{marques_totales}** marques"
    else:
        texte_succes = f"0/{marques_totales} marque"

    # 5. Formatage de la Marque Favorite avec le COMPTEUR
    if favorite_brand:
        logo_fav = LOGOS.get(favorite_brand, "")
        affichage_logo_fav = f"{logo_fav}" if logo_fav else ""
        # On affiche le nombre de modèles possédés à côté
        texte_favori = f"{affichage_logo_fav} **{favorite_brand}** ({compte_marque_fav} possédés)"
    else:
        texte_favori = "*Aucune marque définie (`!fav`)*"
        
    # 6. Création de la carte de profil
    embed = discord.Embed(
        title=f"👤 Profil de {cible.display_name}",
        color=cible.color if cible.color != discord.Color.default() else discord.Color.blue()
    )
    
    if cible.avatar:
        embed.set_thumbnail(url=cible.avatar.url)
        
    # Ajout des champs
    embed.add_field(name="💰 Portefeuille", value=f"**{solde}** 🪙", inline=True)
    embed.add_field(name="💎 Valeur du Garage", value=f"**{valeur_totale}** 🪙", inline=True)
    embed.add_field(name="🏎️ Rang Compétitif", value=rank_full_display, inline=False)
    embed.add_field(name="📊 Score ELO", value=f"**{elo}** points", inline=True)
    
    embed.add_field(name="⭐ Marque Favorite", value=texte_favori, inline=False)
    embed.add_field(name="🚗 Collection", value=f"**{taille_garage}** véhicules\n*{details_str}*", inline=False)
    embed.add_field(name="🎖️ Succès Débloqués", value=texte_succes, inline=False)
    
    await ctx.send(embed=embed)
#endregion

#region commandes
@bot.command(aliases=["commandes", "menu", "aide"])
async def cmd(ctx):
    embed = discord.Embed(
        title="🛠️ Liste des commandes de Bouboule",
        description="Voici tout ce que je peux faire pour l'instant :",
        color=discord.Color.blurple()
    )
    
    embed.add_field(
        name="🎰 `!roll`", 
        value="Tire une voiture au hasard toutes les 12h.", 
        inline=False
    )
    embed.add_field(
        name="🚗 `!garage [@pseudo]`", 
        value="Affiche ton garage et ton solde. Tu peux mentionner quelqu'un !", 
        inline=False
    )
    embed.add_field(
        name="🗂️ `!sortrarity` / `!sortbrand` / `!sortyear` /`!sortpower` /`!sortclass`", 
        value="Trie ton garage par ordre de rareté, par marque, par puissance, par rapport poids/puissance ou chronologiquement par année de sortie.", 
        inline=False
    )
    embed.add_field(
        name="⏳ `!timer`", 
        value="Affiche le temps restant avant ton prochain `!roll` gratuit.", 
        inline=False
    )
    embed.add_field(
        name="🛒 `!sell [Ma voiture]`", 
        value="Vends ta voiture au concessionnaire contre des 🪙. *(Alias: !vendre)*", 
        inline=False
    )
    embed.add_field(
        name="🤝 `!trade @pseudo \"Ma Voiture\" \"Sa Voiture\"`", 
        value="Propose un échange. *N'oublie pas les guillemets !*", 
        inline=False
    )
    embed.add_field(
        name="🔍 `!voiture [modèle ou marque]`", 
        value="Cherche une voiture pour voir à quoi elle ressemble. *(Alias: !search)*", 
        inline=False
    )
    embed.add_field(
        name="📖 `!catalogue`", 
        value="Affiche la liste complète des voitures disponibles. *(Alias: !liste)*", 
        inline=False
    )

    embed.add_field(
        name="💸 `!daily`", 
        value="Récupère ton salaire de 500 🪙 toutes les 24h.", 
        inline=False
    )
    embed.add_field(
        name="⏱️ `!dailytimer`", 
        value="Affiche le temps restant avant ton prochain salaire. *(Alias: !dtimer)*", 
        inline=False
    )
    embed.add_field(
        name="💳 `!solde [@pseudo]`", 
        value="Regarde combien d'argent tu as en banque. *(Alias: !argent)*", 
        inline=False
    )
    embed.add_field(
        name="🎟️ `!buyroll`", 
        value="Achète un tirage supplémentaire immédiat pour 5000 🪙.", 
        inline=False
    )
    embed.add_field(
        name="🏆 `!top`", 
        value="Affiche le classement des joueurs les plus riches et des plus gros garages.", 
        inline=False
    )
    embed.add_field(
        name="🌟 `!wish [voiture]` / `!wishlist`", 
        value="Ajoute des voitures à ta liste de souhaits pour doubler tes chances de les obtenir !", 
        inline=False
    )
    embed.add_field(
        name="👤 `!profil [@pseudo]`", 
        value="Affiche la carte de joueur (Stats, richesse et succès débloqués).", 
        inline=False
    )
    embed.add_field(
        name="⭐ `!fav [marque]`", 
        value="Affiche la marque de tes rêves sur ta carte de profil.", 
        inline=False
    )
    embed.add_field(
        name="🏁 `!race @pseudo [montant] [Classe]`", 
        value="Provoque un joueur en duel sur une classe précise (D, C, B, A, S1, S2, X) ! *(Alias: !course, !duel)*", 
        inline=False
    )
    embed.add_field(
        name="📊 `!ranks`", 
        value="Affiche la liste des rangs compétitifs et les points Elo requis pour les atteindre.", 
        inline=False
    )
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)

    await ctx.send(embed=embed)
#endregion

#region timer
@bot.command(aliases=["cd", "cooldown", "temps"])
async def timer(ctx):
    user_id = str(ctx.author.id)
    
    last_reset_ts, next_reset_ts, next_reset_dt = get_reset_timestamps()
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil or "last_roll" not in profil or profil["last_roll"] < last_reset_ts:
        await ctx.send(f"✅ C'est bon {ctx.author.mention}, ton tirage est prêt ! Fais `!roll` pour tenter ta chance.")
        return

    temps_restant = int(next_reset_ts - time.time())
    heures = temps_restant // 3600
    minutes = (temps_restant % 3600) // 60
    
    heure_cible = next_reset_dt.strftime("%Hh00")
    
    await ctx.send(f"⏳ Patience {ctx.author.mention} ! Ton prochain tirage sera disponible à **{heure_cible}** (dans {heures}h et {minutes}m).")
#endregion

#region dailytimer
@bot.command(aliases=["dtimer", "dailycd", "tempsdaily"])
async def dailytimer(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if not profil or "last_daily" not in profil:
        await ctx.send(f"✅ C'est bon {ctx.author.mention}, ton salaire est prêt ! Fais `!daily` pour le récupérer.")
        return

    maintenant = time.time()
    cooldown_daily = 72000 
    temps_ecoule = maintenant - profil["last_daily"]
    
    if temps_ecoule < cooldown_daily:
        temps_restant = int(cooldown_daily - temps_ecoule)
        heures = temps_restant // 3600
        minutes = (temps_restant % 3600) // 60
        
        await ctx.send(f"⏳ Patience {ctx.author.mention} ! Ton prochain salaire sera disponible dans **{heures}h et {minutes}m**.")
    else:
        await ctx.send(f"✅ C'est bon {ctx.author.mention}, ton salaire est prêt ! Fais `!daily` pour le récupérer.")
#endregion

#region argent
@bot.command(aliases=["bal", "balance", "argent", "money"])
async def solde(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    profil = await collection_inventaires.find_one({"_id": str(cible.id)})
    
    coins = profil.get("coins", 0) if profil else 0
    await ctx.send(f"💳 Le solde de **{cible.display_name}** est de **{coins} 🪙**.")

@bot.command()
async def daily(ctx):
    user_id = str(ctx.author.id)
    maintenant = time.time()
    cooldown_daily = 72000 
    salaire = 500 

    profil = await collection_inventaires.find_one({"_id": user_id})
    
    if profil and "last_daily" in profil:
        temps_ecoule = maintenant - profil["last_daily"]
        if temps_ecoule < cooldown_daily:
            temps_restant = int(cooldown_daily - temps_ecoule)
            heures = temps_restant // 3600
            minutes = (temps_restant % 3600) // 60
            await ctx.send(f"⏳ Reviens demain {ctx.author.mention} ! Ton prochain salaire sera disponible dans **{heures}h et {minutes}m**.")
            return

    await collection_inventaires.update_one(
        {"_id": user_id},
        {
            "$inc": {"coins": salaire},
            "$set": {"last_daily": maintenant}
        },
        upsert=True
    )

    nouveau_profil = await collection_inventaires.find_one({"_id": user_id})
    solde_actuel = nouveau_profil.get("coins", salaire)

    await ctx.send(f"💸 Bien joué {ctx.author.mention} ! Tu as récupéré ton salaire de **{salaire} 🪙**.\nTon nouveau solde est de **{solde_actuel} 🪙**.")
#endregion

#region buyroll
@bot.command()
async def buyroll(ctx):
    user_id = str(ctx.author.id)
    prix_roll = 5000 
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    solde = profil.get("coins", 0) if profil else 0
    
    if solde < prix_roll:
        await ctx.send(f"❌ Désolé {ctx.author.mention}, il te faut **{prix_roll} 🪙**. Il te manque **{prix_roll - solde} 🪙** !")
        return

    voitures_possedees = profil.get("garage", []) if profil else []
    wishlist_joueur = profil.get("wishlist", []) if profil else []
    voitures_disponibles = []
    poids_disponibles = []

    for voiture in VOITURES:
        nom_complet = f"{voiture['marque']} {voiture['nom']} {voiture.get('annee', '')}".strip()
        if nom_complet not in voitures_possedees:
            voitures_disponibles.append(voiture)
            poids_base = voiture.get("poids", 10)
            
            if nom_complet in wishlist_joueur:
                poids_disponibles.append(poids_base * 2) 
            else:
                poids_disponibles.append(poids_base)

    if not voitures_disponibles:
        await ctx.send(f"🏆 Tu possèdes déjà **TOUTES** les voitures du jeu !")
        return

    voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
    nom_complet_gagnee = f"{voiture_gagnee['marque']} {voiture_gagnee['nom']} {voiture_gagnee.get('annee', '')}".strip()
    print(f"[LOG 🎰] {ctx.author.name} a obtenu : {nom_complet_gagnee}")
    rarete = voiture_gagnee['rareté']

    # NOUVEAU : Application du tri automatique sur le nouveau garage
    sort_preference = profil.get("sort_preference") if profil else None
    voitures_possedees.append(nom_complet_gagnee)
    
    if sort_preference:
        voitures_possedees = appliquer_tri_garage(voitures_possedees, sort_preference)

    update_query = {
        "$set": {"garage": voitures_possedees},
        "$inc": {"coins": -prix_roll}
    }
    
    if nom_complet_gagnee in wishlist_joueur:
        update_query["$pull"] = {"wishlist": nom_complet_gagnee}

    await collection_inventaires.update_one(
        {"_id": user_id},
        update_query
    )

    curseur = collection_inventaires.find({"garage": nom_complet_gagnee})
    docs = await curseur.to_list(length=100)
    proprietaires_mentions = [f"<@{doc['_id']}>" for doc in docs]
    texte_proprietaires = ", ".join(proprietaires_mentions) if proprietaires_mentions else f"<@{user_id}>"

    classe_forza = calculer_classe_forza(voiture_gagnee)
    masse = voiture_gagnee.get('masse_kg', 'Inconnu')
    logo = LOGOS.get(voiture_gagnee['marque'], "")
    lignes = [
        voiture_gagnee['nom'],
        f"{logo} **{voiture_gagnee['marque']}**"
    ]
    if voiture_gagnee.get('annee'):
        lignes.append(str(voiture_gagnee['annee']))
    lignes.append(voiture_gagnee.get('pays', '🏁'))
    lignes.append("")
    lignes.append("**Rareté**")
    lignes.append(rarete)
    lignes.append("")
    lignes.append("**⚙️ Spécifications**")
    lignes.append(f"Moteur : {voiture_gagnee.get('moteur', 'Inconnu')}")
    lignes.append(f"Puissance : {voiture_gagnee.get('puissance', 'Inconnue')}")
    lignes.append(f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu")
    lignes.append(classe_forza)
    lignes.append("")
    lignes.append("**Propriétaires :**")
    lignes.append(texte_proprietaires)
    lignes.append("")
    lignes.append(f"💸 *Nouveau solde : {solde - prix_roll} 🪙*")

    couleur_dynamique = COULEURS_RARETE.get(rarete, discord.Color.purple())
    
    embed = discord.Embed(
        title=f"🎰 Vous avez eu : {nom_complet_gagnee}", 
        description="\n".join(lignes),
        color=couleur_dynamique
    )
    
    img_url = voiture_gagnee.get('image', '')
    if img_url and img_url.startswith(('http://', 'https://')):
        embed.set_image(url=img_url)
    else:
        embed.add_field(name="⚠️ Image indisponible", value="Le lien de cette image doit être corrigé dans le catalogue.", inline=False)

    messages_rarete = {
        "Commun ⚪": "Ouais basique",
        "Rare 🔵": "Eh pas mal",
        "Mythique 🟣": "Eh beh mon salaud",
        "Légendaire 🟡": "Oh pétard",
        "GOAT 🔴": "WAAAAAAAA"
    }
    phrase = messages_rarete.get(rarete, "Bien joué")

    voeu_exauce = ""
    if nom_complet_gagnee in wishlist_joueur:
        voeu_exauce = "\n\n🌟 **VŒU EXAUCÉ !** Cette voiture était dans ta wishlist, elle a été retirée de la liste."

    await verifier_succes_marque(ctx, user_id, voiture_gagnee['marque'])
    await ctx.send(content=f"{ctx.author.mention} **{phrase} !**{voeu_exauce}", embed=embed)
#endregion

#region leaderboard
@bot.command(aliases=["top", "lb", "classement", "leaderboard"])
async def toplist(ctx):
    # On récupère tous les profils
    profils = await collection_inventaires.find({}).to_list(length=1000)

    if not profils:
        await ctx.send("❌ Aucun joueur n'est enregistré dans la base de données pour le moment !")
        return

    # Dictionnaire pour la valeur ET la rareté (l'émoji) de chaque voiture
    infos_voitures = {}
    for v in VOITURES:
        nom_complet = f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip()
        infos_voitures[nom_complet] = {
            "prix": PRIX_REVENTE.get(v['rareté'], 50),
            "emoji": v['rareté'][-1] 
        }

    # On calcule la valeur totale du garage pour chaque joueur
    for profil in profils:
        valeur_totale = sum(infos_voitures.get(nom, {}).get("prix", 50) for nom in profil.get("garage", []))
        profil["valeur_garage"] = valeur_totale

    # --- Tris des 3 catégories ---
    top_coins = sorted(profils, key=lambda x: x.get("coins", 0), reverse=True)[:10]
    top_garage = sorted(profils, key=lambda x: len(x.get("garage", [])), reverse=True)[:10]
    top_valeur = sorted(profils, key=lambda x: x.get("valeur_garage", 0), reverse=True)[:10]
    top_elo = sorted(profils, key=lambda x: x.get("elo", 1000), reverse=True)[:10]

    # --- Colonne 1 : Argent ---
    texte_coins = ""
    for i, profil in enumerate(top_coins, 1):
        solde = profil.get('coins', 0)
        if solde > 0: 
            texte_coins += f"**{i}.** <@{profil['_id']}> : **{solde}** 🪙\n"
            
    if not texte_coins:
        texte_coins = "Tout le monde est fauché ! 💸\n"

    # --- Colonne 2 : Nombre de Voitures + Détail des raretés ---
    texte_garage = ""
    for i, profil in enumerate(top_garage, 1):
        garage = profil.get("garage", [])
        taille = len(garage)
        if taille > 0: 
            # On compte les raretés
            comptes = {"🔴": 0, "🟡": 0, "🟣": 0, "🔵": 0, "⚪": 0}
            for nom in garage:
                emoji = infos_voitures.get(nom, {}).get("emoji", "⚪")
                if emoji in comptes:
                    comptes[emoji] += 1
            
            # On crée le petit texte de détail (du plus rare au plus commun)
            details = []
            for emj in ["🔴", "🟡", "🟣", "🔵", "⚪"]:
                if comptes[emj] > 0:
                    details.append(f"**{comptes[emj]}** {emj}")
            
            details_str = " ".join(details)
            
            texte_garage += f"**{i}.** <@{profil['_id']}> : **{taille}** 🚗 *({details_str})*\n"
            
    if not texte_garage:
        texte_garage = "Tous les garages sont vides ! 🚶‍♂️\n"

    # --- Colonne 3 : Valeur Garage ---
    texte_valeur = ""
    for i, profil in enumerate(top_valeur, 1):
        valeur = profil.get('valeur_garage', 0)
        if valeur > 0: 
            texte_valeur += f"**{i}.** <@{profil['_id']}> : **{valeur}** 💎\n"
            
    if not texte_valeur:
        texte_valeur = "Aucun patrimoine ! 📉\n"

    texte_elo = ""
    for i, profil in enumerate(top_elo, 1):
        elo = profil.get('elo', 1000)
        # On extrait juste le logo pour le top (en appelant get_elo_rank et en prenant le début)
        logo_rank = get_elo_rank(elo).split("**")[0].strip()
        
        if elo > 1000:
            texte_elo += f"**{i}.** {logo_rank} <@{profil['_id']}> : **{elo}**\n"
            
    if not texte_elo:
        texte_elo = "Personne n'a encore fait ses preuves sur l'asphalte ! 🛣️\n"

    # --- Création de l'affichage ---
    embed = discord.Embed(
        title="🏆 Classement Officiel du Serveur",
        description="Qui dominera le marché automobile ?\n\u200b", # \u200b ajoute un espace vide pour aérer un peu
        color=discord.Color.gold()
    )
    
    # NOUVEAU : inline=False permet à chaque catégorie de prendre toute la largeur !
    embed.add_field(name="💰 Top Richesse", value=texte_coins, inline=False)
    embed.add_field(name="🏁 Top Pilotes (Elo)", value=texte_elo, inline=False)
    embed.add_field(name="🚗 Top Collection", value=texte_garage, inline=False)
    embed.add_field(name="💎 Valeur Garage", value=texte_valeur, inline=False)
    
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None) 
    
    await ctx.send(embed=embed)
#endregion

#region wishlist
@bot.command()
async def wish(ctx, *, recherche: str):
    user_id = str(ctx.author.id)
    recherche_lower = recherche.lower().strip()
    
    modele_trouve = next((v for v in VOITURES if recherche_lower in f"{v['marque']} {v['nom']} {v.get('annee', '')}".lower()), None)
    
    if not modele_trouve:
        await ctx.send(f"❌ Je n'ai trouvé aucune voiture correspondant à **{recherche}**.")
        return
        
    nom_complet = f"{modele_trouve['marque']} {modele_trouve['nom']} {modele_trouve.get('annee', '')}".strip()
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    garage = profil.get("garage", []) if profil else []
    wishlist = profil.get("wishlist", []) if profil else []
    
    if nom_complet in garage:
        await ctx.send(f"❌ Tu possèdes déjà la **{nom_complet}** dans ton garage !")
        return
        
    if nom_complet in wishlist:
        await ctx.send(f"⚠️ La **{nom_complet}** est déjà dans ta wishlist !")
        return
        
    if len(wishlist) >= 10:
        await ctx.send(f"❌ Ta wishlist est pleine (10/10) ! Utilise `!unwish` pour faire de la place.")
        return
        
    await collection_inventaires.update_one(
        {"_id": user_id},
        {"$push": {"wishlist": nom_complet}},
        upsert=True
    )
    
    await ctx.send(f"🌟 **{nom_complet}** a été ajoutée à ta wishlist ! (Ses chances d'apparition sont multipliées par 2).")

@bot.command()
async def unwish(ctx, *, recherche: str):
    user_id = str(ctx.author.id)
    recherche_lower = recherche.lower().strip()
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    wishlist = profil.get("wishlist", []) if profil else []
    
    if not wishlist:
        await ctx.send("❌ Ta wishlist est déjà vide !")
        return
        
    voiture_a_retirer = next((v for v in wishlist if recherche_lower in v.lower()), None)
    
    if not voiture_a_retirer:
        await ctx.send(f"❌ Aucune voiture correspondant à **{recherche}** n'a été trouvée dans ta wishlist.")
        return
        
    await collection_inventaires.update_one(
        {"_id": user_id},
        {"$pull": {"wishlist": voiture_a_retirer}}
    )
    
    await ctx.send(f"🗑️ **{voiture_a_retirer}** a été retirée de ta wishlist.")

@bot.command(aliases=["wl", "wishlists"])
async def wishlist(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    user_id = str(cible.id)
    
    profil = await collection_inventaires.find_one({"_id": user_id})
    wishlist_cars = profil.get("wishlist", []) if profil else []
    
    if not wishlist_cars:
        await ctx.send(f"📭 La wishlist de {cible.display_name} est vide.")
        return
        
    description = ""
    for i, nom_complet in enumerate(wishlist_cars, 1):
        voiture_info = next((v for v in VOITURES if f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() == nom_complet), None)
        if voiture_info:
            description += f"**{i}.** {nom_complet} - *{voiture_info['rareté']}*\n"
        else:
            description += f"**{i}.** {nom_complet}\n"
            
    embed = discord.Embed(
        title=f"🌟 Wishlist de {cible.display_name} ({len(wishlist_cars)}/10)",
        description=description,
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)
#endregion

#region ranks
@bot.command(aliases=["ranklist", "elos", "grades"])
async def ranks(ctx):
    # Récupération des logos depuis ton fichier custom (ou emojis de secours)
    logo_bronze = LOGOS.get("Bronze", "🟫")
    logo_argent = LOGOS.get("Argent", "⬜")
    logo_or = LOGOS.get("Or", "🟨")
    logo_platine = LOGOS.get("Platine", "🟦")
    logo_diamant = LOGOS.get("Diamant", "💎")
    logo_ruby = LOGOS.get("Ruby", "🔴")

    # Formatage de la liste (du plus haut au plus bas)
    description = (
        f"{logo_ruby} **Ruby** : 1900 Elo et +\n\n"
        f"{logo_diamant} **Diamant** : 1700 - 1899 Elo\n\n"
        f"{logo_platine} **Platine** : 1500 - 1699 Elo\n\n"
        f"{logo_or} **Or** : 1300 - 1499 Elo\n\n"
        f"{logo_argent} **Argent** : 1100 - 1299 Elo\n\n"
        f"{logo_bronze} **Bronze** : 0 - 1099 Elo *(Score de départ : 1000)*"
    )

    embed = discord.Embed(
        title="🏁 Rangs Compétitifs (Street Racing)",
        description="Voici les différents paliers d'Elo à franchir pour dominer le serveur :\n\n" + description,
        color=discord.Color.red()
    )
    
    embed.set_footer(text="Gagne des courses en duel (!race) pour monter en grade !")
    
    await ctx.send(embed=embed)
#endregion

#region race
def obtenir_ratio(nom_complet):
    voiture = next((v for v in VOITURES if f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() == nom_complet), None)
    if not voiture:
        return 10.0 
        
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
            
    if not puissance or not masse or puissance == 0:
        return 10.0 
        
    return masse / puissance

def get_elo_rank(elo):
    if elo < 1100:
        rank_name = "Bronze"
        emoji_alt = "🟫"
    elif elo < 1300:
        rank_name = "Argent"
        emoji_alt = "⬜"
    elif elo < 1500:
        rank_name = "Or"
        emoji_alt = "🟨"
    elif elo < 1700:
        rank_name = "Platine"
        emoji_alt = "🟦"
    elif elo < 1900:
        rank_name = "Diamant"
        emoji_alt = "💎"
    else:
        rank_name = "Ruby"
        emoji_alt = "🔴"

    logo = LOGOS.get(rank_name, emoji_alt)
    return f"{logo} **{rank_name}**"

# NOUVEAU : Système de pagination pour la sélection de voitures
class RaceSelectionPagination(discord.ui.View):
    def __init__(self, ctx, user, pages, titre):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.user = user # L'utilisateur autorisé à cliquer (attaquant ou défenseur)
        self.pages = pages
        self.titre = titre
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.bouton_prec.disabled = len(self.pages) <= 1
        self.bouton_suiv.disabled = len(self.pages) <= 1

    def get_embed(self):
        embed = discord.Embed(
            title=self.titre,
            description=self.pages[self.current_page],
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} | Tape le numéro de ton choix dans le chat !")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, custom_id="race_prec")
    async def bouton_prec(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("Ce n'est pas à ton tour de choisir !", ephemeral=True)
        self.current_page = (self.current_page - 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, custom_id="race_suiv")
    async def bouton_suiv(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("Ce n'est pas à ton tour de choisir !", ephemeral=True)
        self.current_page = (self.current_page + 1) % len(self.pages)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.command(aliases=["course", "duel"])
async def race(ctx, membre: discord.Member, montant: int, classe_voulue: str):
    classe_voulue = classe_voulue.upper().strip()
    valid_classes = ["D", "C", "B", "A", "S1", "S2", "X"]
    
    if classe_voulue not in valid_classes:
        return await ctx.send(f"❌ Classe invalide ! Choisis parmi : `{', '.join(valid_classes)}`")
    if ctx.author == membre:
        return await ctx.send("❌ Tu ne peux pas faire la course contre toi-même !")
    if montant <= 0:
        return await ctx.send("❌ La mise doit être supérieure à 0 🪙.")

    user_id = str(ctx.author.id)
    target_id = str(membre.id)

    profil_user = await collection_inventaires.find_one({"_id": user_id})
    profil_target = await collection_inventaires.find_one({"_id": target_id})

    # 1. Vérification de l'argent
    solde_user = profil_user.get("coins", 0) if profil_user else 0
    solde_target = profil_target.get("coins", 0) if profil_target else 0

    if solde_user < montant:
        return await ctx.send(f"❌ Tu n'as pas assez d'argent ! Il te manque **{montant - solde_user} 🪙**.")
    if solde_target < montant:
        return await ctx.send(f"❌ {membre.display_name} n'a pas assez d'argent pour couvrir cette mise (Solde: {solde_target} 🪙).")
    
    # 2. Filtrage des garages selon la Classe
    def filter_cars_by_class(garage, cls):
        result = []
        for nom in garage:
            v_info = next((v for v in VOITURES if f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() == nom), None)
            if v_info and obtenir_nom_classe_simple(v_info) == cls:
                if nom not in result: result.append(nom)
        return result

    voitures_a = filter_cars_by_class(profil_user.get("garage", []), classe_voulue)
    voitures_b = filter_cars_by_class(profil_target.get("garage", []), classe_voulue)

    if not voitures_a:
        return await ctx.send(f"❌ Tu ne possèdes aucune voiture de **Classe {classe_voulue}** dans ton garage !")
    if not voitures_b:
        return await ctx.send(f"❌ Duel impossible : {membre.display_name} ne possède aucune voiture de **Classe {classe_voulue}**.")

    # 3. Choix de l'Attaquant (Avec Pagination)
    lignes_a = [f"**{i+1}.** {v}" for i, v in enumerate(voitures_a)]
    pages_a = ["\n".join(lignes_a[i:i + 15]) for i in range(0, len(lignes_a), 15)]
    titre_a = f"🏁 Duel en Classe {classe_voulue} - Choix de {ctx.author.display_name}"
    
    view_a = RaceSelectionPagination(ctx, ctx.author, pages_a, titre_a)
    msg_select_a = await ctx.send(
        content=f"{ctx.author.mention}, choisis ta voiture en tapant son numéro dans le chat :",
        embed=view_a.get_embed(), 
        view=view_a
    )

    def check_msg_a(m): return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

    try:
        # Temps augmenté à 60s
        msg_resp_a = await bot.wait_for('message', timeout=60.0, check=check_msg_a)
        choix_idx_a = int(msg_resp_a.content) - 1
        if not (0 <= choix_idx_a < len(voitures_a)): 
            return await ctx.send("❌ Numéro invalide. Course annulée.")
        ma_voiture_exacte = voitures_a[choix_idx_a]
        
        # Nettoyage
        try:
            await msg_select_a.delete()
            await msg_resp_a.delete()
        except: pass
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Temps écoulé pour choisir. Course annulée.")

    # 4. Invitation au Défenseur
    msg_invite = await ctx.send(
        f"🏁 **DÉFI STREET RACING !** 🏁\n"
        f"{membre.mention}, {ctx.author.mention} te provoque en duel de **Classe {classe_voulue}** pour **{montant} 🪙** !\n"
        f"Il a choisi de piloter sa **{ma_voiture_exacte}**.\n\n"
        f"*Accepte avec ✅ ou fuis lâchement avec ❌.*"
    )
    await msg_invite.add_reaction("✅")
    await msg_invite.add_reaction("❌")

    def check_reaction(reaction, user):
        return user == membre and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg_invite.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=45.0, check=check_reaction)
        if str(reaction.emoji) == "❌":
            return await ctx.send(f"💨 {membre.display_name} a refusé la course.")
        
        try: await msg_invite.delete()
        except: pass
    except asyncio.TimeoutError:
        return await ctx.send(f"⏳ Le temps est écoulé, {membre.display_name} n'a pas répondu à l'invitation.")

    # 5. Choix du Défenseur (Avec Pagination)
    lignes_b = [f"**{i+1}.** {v}" for i, v in enumerate(voitures_b)]
    pages_b = ["\n".join(lignes_b[i:i + 15]) for i in range(0, len(lignes_b), 15)]
    titre_b = f"🔥 Défi accepté ! Choix de {membre.display_name}"
    
    view_b = RaceSelectionPagination(ctx, membre, pages_b, titre_b)
    msg_select_b = await ctx.send(
        content=f"{membre.mention}, choisis ta voiture de **Classe {classe_voulue}** en tapant son numéro :",
        embed=view_b.get_embed(), 
        view=view_b
    )

    def check_msg_b(m): return m.author == membre and m.channel == ctx.channel and m.content.isdigit()

    try:
        # Temps augmenté à 60s
        msg_resp_b = await bot.wait_for('message', timeout=60.0, check=check_msg_b)
        choix_idx_b = int(msg_resp_b.content) - 1
        if not (0 <= choix_idx_b < len(voitures_b)): 
            return await ctx.send("❌ Numéro invalide. Duel annulé.")
        sa_voiture_exacte = voitures_b[choix_idx_b]
        
        try:
            await msg_select_b.delete()
            await msg_resp_b.delete()
        except: pass
    except asyncio.TimeoutError:
        return await ctx.send("⏳ Trop lent pour choisir la voiture... La course est annulée !")

    # 6. Lancement de la Course
    ratio_a = obtenir_ratio(ma_voiture_exacte)
    ratio_b = obtenir_ratio(sa_voiture_exacte)

    vitesse_base_a = max(1.0, min(12.0, 15.0 - ratio_a))
    vitesse_base_b = max(1.0, min(12.0, 15.0 - ratio_b))

    LONGUEUR_PISTE = 20
    pos_a = 0.0
    pos_b = 0.0
    
    # NOUVEAU : On pioche l'intro au hasard
    phrase_intro = random.choice(PHRASES_INTRO)
    dernier_commentaire = phrase_intro

    def generer_piste(pos, pseudo, voiture, emoji_voiture):
        pos_int = int(pos)
        if pos_int > LONGUEUR_PISTE: pos_int = LONGUEUR_PISTE
        route_restante = "➖" * (LONGUEUR_PISTE - pos_int)
        route_parcourue = "➖" * pos_int
        return f"**{pseudo}** ({voiture})\n🏁{route_restante}{emoji_voiture}{route_parcourue}🟩"

    course_msg = await ctx.send(phrase_intro)
    await asyncio.sleep(2)
    
    tour = 0
    while pos_a < LONGUEUR_PISTE and pos_b < LONGUEUR_PISTE and tour < 30:
        pos_a += (vitesse_base_a / 4.0) + random.uniform(0.1, 0.8)
        pos_b += (vitesse_base_b / 4.0) + random.uniform(0.1, 0.8)

        # Générer un nouveau commentaire tous les 3 tours
        if tour > 0 and tour % 3 == 0:
            commentateur = random.choice([ctx.author.display_name, membre.display_name])
            dernier_commentaire = f"🎙️ *{random.choice(PHRASES_RACE).format(pseudo=commentateur)}*"

        piste_a = generer_piste(pos_a, ctx.author.display_name, ma_voiture_exacte, "🏎️")
        piste_b = generer_piste(pos_b, membre.display_name, sa_voiture_exacte, "🚙")
        
        embed = discord.Embed(
            title=f"🚨 COURSE EN COURS (Classe {classe_voulue}) 🚨", 
            description=f"{piste_a}\n\n{piste_b}\n\n{dernier_commentaire}", 
            color=discord.Color.orange()
        )
        await course_msg.edit(content=None, embed=embed)
        
        tour += 1
        await asyncio.sleep(1.2)

    # 7. Détermination du vainqueur et Elo
    if pos_a >= LONGUEUR_PISTE and pos_b >= LONGUEUR_PISTE:
        if pos_a >= pos_b:
            gagnant, perdant = ctx.author, membre
            vainqueur_id, perdant_id = user_id, target_id
        else:
            gagnant, perdant = membre, ctx.author
            vainqueur_id, perdant_id = target_id, user_id
    elif pos_a >= LONGUEUR_PISTE:
        gagnant, perdant = ctx.author, membre
        vainqueur_id, perdant_id = user_id, target_id
    else:
        gagnant, perdant = membre, ctx.author
        vainqueur_id, perdant_id = target_id, user_id

    cagnotte_totale = montant * 2

    elo_user = profil_user.get("elo", 1000) if profil_user else 1000
    elo_target = profil_target.get("elo", 1000) if profil_target else 1000

    K_WIN = 45   
    K_LOSS = 15  

    esp_user = 1 / (1 + 10 ** ((elo_target - elo_user) / 400))
    esp_target = 1 / (1 + 10 ** ((elo_user - elo_target) / 400))

    if vainqueur_id == user_id:
        nouveau_elo_user = int(elo_user + K_WIN * (1 - esp_user))
        nouveau_elo_target = int(elo_target + K_LOSS * (0 - esp_target))
    else:
        nouveau_elo_user = int(elo_user + K_LOSS * (0 - esp_user))
        nouveau_elo_target = int(elo_target + K_WIN * (1 - esp_target))

    nouveau_elo_user = max(0, nouveau_elo_user)
    nouveau_elo_target = max(0, nouveau_elo_target)

    diff_user = nouveau_elo_user - elo_user
    diff_target = nouveau_elo_target - elo_target

    signe_user = "+" if diff_user >= 0 else ""
    signe_target = "+" if diff_target >= 0 else ""

    await collection_inventaires.update_one(
        {"_id": user_id}, 
        {"$inc": {"coins": montant if vainqueur_id == user_id else -montant}, "$set": {"elo": nouveau_elo_user}}
    )
    await collection_inventaires.update_one(
        {"_id": target_id}, 
        {"$inc": {"coins": montant if vainqueur_id == target_id else -montant}, "$set": {"elo": nouveau_elo_target}}
    )

    rank_display_user = get_elo_rank(nouveau_elo_user)
    rank_display_target = get_elo_rank(nouveau_elo_target)

    piste_a = generer_piste(pos_a, ctx.author.display_name, ma_voiture_exacte, "🏎️")
    piste_b = generer_piste(pos_b, membre.display_name, sa_voiture_exacte, "🚙")
    
    phrase_finale = random.choice(PHRASES_VICTOIRE).format(gagnant=gagnant.display_name)

    embed_fin = discord.Embed(
        title="🏆 ARRIVÉE ! 🏆", 
        description=(
            f"{piste_a}\n"
            f"📈 {rank_display_user} : **{nouveau_elo_user}** Elo ({signe_user}{diff_user})\n\n"
            f"{piste_b}\n"
            f"📉 {rank_display_target} : **{nouveau_elo_target}** Elo ({signe_target}{diff_target})\n\n"
            f"{phrase_finale}\n"
            f"💰 **{gagnant.mention} rafle la cagnotte de {cagnotte_totale} 🪙 !**"
        ), 
        color=discord.Color.green()
    )
    embed_fin.set_footer(text=f"Le pauvre {perdant.display_name} rentre chez lui avec -{montant} 🪙...")
    
    await course_msg.edit(embed=embed_fin)

@race.error
async def race_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument) or isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ **Erreur de syntaxe.**\nUtilise la commande dans cet ordre :\n`!race @pseudo <montant> <Classe>`\n\n*Exemple :* `!race @Bouboule 500 S1`")
#endregion

# 4. Lancement
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
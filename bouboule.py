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

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
#endregion

# --- NOUVEAU : Événement de démarrage ---
@bot.event
async def on_ready():
    print("="*30)
    print(f"✅ CONNECTÉ AVEC SUCCÈS !")
    print(f"🤖 Nom du bot : {bot.user.name}")
    print(f"🆔 ID du bot  : {bot.user.id}")
    
    # Synchronisation des commandes slash
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Commandes Slash synchronisées : {len(synced)}")
    except Exception as e:
        print(f"❌ Erreur de synchro slash : {e}")
        
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
    
    # Remplacement des 4 par des 2
    heure_dernier_reset = (now.hour // 2) * 2
    heure_prochain_reset = heure_dernier_reset + 2
    
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
        
        # NOUVEAU : Récupération et affichage du nouveau solde
        ancien_solde = profil.get("coins", 0)
        nouveau_solde = ancien_solde + recompense
        
        embed = discord.Embed(
            title="🏆 NOUVEAU SUCCÈS DÉBLOQUÉ !",
            description=f"Incroyable ! <@{user_id}> vient de collectionner **absolument tous** les modèles de la marque **{marque}** !\n\n🎁 **Bonus de collectionnneur : +{recompense} 🪙**",
            color=discord.Color.brand_green()
        )
        embed.set_footer(text=f"Nouveau solde : {nouveau_solde} 🪙")
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

@bot.hybrid_command(name="sortrarity", description="Trie ton garage par ordre de rareté.", aliases=["sortr", "trierrarte", "trier_rarete"])
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

@bot.hybrid_command(name="sortbrand", description="Trie ton garage par ordre alphabétique des marques.", aliases=["sortb", "triermarque", "trier_marque"])
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

@bot.hybrid_command(name="sortyear", description="Trie ton garage par ordre chronologique.", aliases=["sorty", "trierannee", "trier_annee"])
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

@bot.hybrid_command(name="sortpower", description="Trie ton garage par ordre de puissance.", aliases=["sortp", "trierpuissance", "trier_puissance"])
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

@bot.hybrid_command(name="sortclass", description="Trie ton garage par classe de performance (ratio Poids/Puissance).", aliases=["sortc", "trierclasse", "trier_classe", "sortratio"])
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
@bot.hybrid_command(name="roll", description="Tire une voiture au hasard toutes les 2h.")
async def roll(ctx):
    user_id = str(ctx.author.id)
    
    last_reset_ts, next_reset_ts, next_reset_dt = get_reset_timestamps()
    profil = await collection_inventaires.find_one({"_id": user_id})

    tolerance = 60
    
    if profil and "last_roll" in profil:
        # On vérifie si le dernier roll a été fait dans le créneau actuel, moins la tolérance
        if profil["last_roll"] >= (last_reset_ts - tolerance):
            temps_restant = int(next_reset_ts - time.time())
            
            # Si le temps restant est inférieur à la tolérance, on laisse passer
            if temps_restant > tolerance:
                heures = temps_restant // 3600
                minutes = (temps_restant % 3600) // 60
                
                heure_cible = next_reset_dt.strftime("%Hh00")
                await ctx.send(f"⏳ Doucement {ctx.author.mention} ! Tu as déjà fait ton tirage pour ce créneau.\nLe prochain sera dispo à **{heure_cible}** (dans {heures}h et {minutes}m).")
                return

    voitures_possedees = profil.get("garage", []) if profil else []
    wishlist_joueur = profil.get("wishlist", []) if profil else []
    marque_favorite = profil.get("favorite_brand") if profil else None
    
    voitures_disponibles = []
    poids_disponibles = []

    for voiture in VOITURES:
        nom_complet = f"{voiture['marque']} {voiture['nom']} {voiture.get('annee', '')}".strip()
        if nom_complet not in voitures_possedees:
            voitures_disponibles.append(voiture)
            poids_calc = voiture.get("poids", 10)
            
            # NOUVEAU : Bonus x1.5 pour la marque favorite
            if marque_favorite and voiture['marque'] == marque_favorite:
                poids_calc *= 1.5
            
            if nom_complet in wishlist_joueur:
                poids_calc *= 2
                
            poids_disponibles.append(poids_calc)

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
    
    # Application du tri automatique sur le nouveau garage
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

    membres_serveur_ids = [str(m.id) for m in ctx.guild.members]
    curseur = collection_inventaires.find({
        "garage": nom_complet_gagnee,
        "_id": {"$in": membres_serveur_ids}
    })
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
    elif marque_favorite and voiture_gagnee['marque'] == marque_favorite:
        voeu_exauce = "\n\n⭐ **BINGO !** Ta fidélité a payé, tu viens d'obtenir un modèle de ta marque favorite !"

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
@bot.hybrid_command(name="garage", description="Affiche ton garage ou celui d'un autre joueur.")
async def garage(ctx, membre: discord.Member = None, page: int = 1):
    cible = membre or ctx.author
    page_cible = max(1, page) # Sécurité pour éviter les pages 0 ou négatives
    
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
@bot.hybrid_command(name="trade", description="Propose un échange de voiture à un autre joueur.")
async def trade(ctx, membre: discord.Member, ma_voiture: str, sa_voiture: str):
    if ctx.author == membre:
        await ctx.send("Tu ne peux pas faire un échange avec toi-même !")
        return

    user_id = str(ctx.author.id)
    target_id = str(membre.id)

    profil_user = await collection_inventaires.find_one({"_id": user_id})
    profil_target = await collection_inventaires.find_one({"_id": target_id})

    garage_user = profil_user.get("garage", []) if profil_user else []
    garage_target = profil_target.get("garage", []) if profil_target else []

    # --- NOUVEAU : Recherche souple ---
    ma_voiture_exacte = next((v for v in garage_user if ma_voiture.lower() in v.lower()), None)
    sa_voiture_exacte = next((v for v in garage_target if sa_voiture.lower() in v.lower()), None)

    if not ma_voiture_exacte:
        await ctx.send(f"❌ Tu ne possèdes pas la voiture **{ma_voiture}** !")
        return
    if not sa_voiture_exacte:
        await ctx.send(f"❌ {membre.display_name} ne possède pas la voiture **{sa_voiture}** !")
        return

    def trouver_info(nom_complet_recherche):
        return next((v for v in VOITURES if f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() == nom_complet_recherche), None)

    info_ma = trouver_info(ma_voiture_exacte)
    info_sa = trouver_info(sa_voiture_exacte)

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

    msg = await ctx.send(f"Hey {membre.mention} ! {ctx.author.mention} te propose d'échanger sa **{ma_voiture_exacte}** contre ta **{sa_voiture_exacte}**.{msg_compensation}\n\n*Réagis avec ✅ pour accepter ou ❌ pour refuser.*")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    def check(reaction, user):
        return user == membre and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
        
        if str(reaction.emoji) == "✅":
            garage_user.remove(ma_voiture_exacte)
            garage_target.remove(sa_voiture_exacte)
            garage_user.append(sa_voiture_exacte)
            garage_target.append(ma_voiture_exacte)

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

#region tradeup
class TradeUpSelectionView(discord.ui.View):
    def __init__(self, ctx, eligible_cars, rarete_base, rarete_gagne, profil, garage):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.user = ctx.author
        self.eligible_cars = eligible_cars
        self.rarete_base = rarete_base
        self.rarete_gagne = rarete_gagne
        self.profil = profil
        self.garage = garage
        
        self.selected_indices = set()
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, math.ceil(len(eligible_cars) / self.items_per_page))
        self.number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        
        self.update_view_state()

    def update_view_state(self):
        # Navigation
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page >= self.total_pages - 1)
        
        # Validation
        self.btn_confirm.disabled = (len(self.selected_indices) != 5)
        
        # Mise à jour des boutons 1 à 5
        boutons_nombres = [self.btn_1, self.btn_2, self.btn_3, self.btn_4, self.btn_5]
        for i, btn in enumerate(boutons_nombres):
            abs_index = self.current_page * self.items_per_page + i
            if abs_index >= len(self.eligible_cars):
                btn.disabled = True
                btn.style = discord.ButtonStyle.secondary
            else:
                btn.disabled = False
                if abs_index in self.selected_indices:
                    btn.style = discord.ButtonStyle.success # Devient vert si sélectionné
                else:
                    btn.style = discord.ButtonStyle.secondary # Reste gris sinon

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.eligible_cars[start:end]
        
        lignes = []
        for i, voiture in enumerate(page_items):
            abs_index = start + i
            check = " ✅" if abs_index in self.selected_indices else ""
            lignes.append(f"{self.number_emojis[i]} **{voiture}**{check}")
            
        embed = discord.Embed(
            title=f"⚠️ TRADE-UP {self.rarete_base} ➔ {self.rarete_gagne}",
            description=f"Sélectionne **5 voitures** à sacrifier.\n\n" + "\n".join(lignes),
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} | Sélectionnées : {len(self.selected_indices)}/5")
        return embed

    async def toggle_item(self, interaction: discord.Interaction, idx_offset: int):
        if interaction.user != self.user:
            return await interaction.response.send_message("Ce n'est pas ton menu !", ephemeral=True)
            
        abs_index = self.current_page * self.items_per_page + idx_offset
        if abs_index >= len(self.eligible_cars):
            return await interaction.response.defer()
            
        if abs_index in self.selected_indices:
            self.selected_indices.remove(abs_index)
        else:
            if len(self.selected_indices) >= 5:
                return await interaction.response.send_message("❌ Tu as déjà sélectionné tes 5 voitures ! Désélectionnes-en une pour changer.", ephemeral=True)
            self.selected_indices.add(abs_index)
            
        self.update_view_state()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # --- BOUTONS NUMÉROS ---
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

    # --- BOUTONS DE NAVIGATION ET VALIDATION ---
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, row=1)
    async def btn_prev(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page -= 1
        self.update_view_state()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, row=1)
    async def btn_next(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page += 1
        self.update_view_state()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="✅ CONFIRMER", style=discord.ButtonStyle.success, row=1, disabled=True)
    async def btn_confirm(self, interaction, button):
        if interaction.user != self.user: return
        await self.execute_tradeup(interaction)

    async def execute_tradeup(self, interaction: discord.Interaction):
        # Désactiver l'interface pendant le chargement
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(view=self)

        noms_exacts = [self.eligible_cars[i] for i in self.selected_indices]
        nouveau_garage = list(self.garage)
        
        # Retrait des voitures
        for v in noms_exacts:
            if v in nouveau_garage:
                nouveau_garage.remove(v)

        wishlist_joueur = self.profil.get("wishlist", [])
        voitures_possibles = [v for v in VOITURES if v['rareté'] == self.rarete_gagne]
        
        voitures_disponibles = []
        poids_disponibles = []

        for v in voitures_possibles:
            nom_c = f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip()
            if nom_c not in nouveau_garage:
                voitures_disponibles.append(v)
                if nom_c in wishlist_joueur: poids_disponibles.append(v.get("poids", 10) * 2)
                else: poids_disponibles.append(v.get("poids", 10))

        if not voitures_disponibles:
            voitures_disponibles = voitures_possibles
            poids_disponibles = [v.get("poids", 10) for v in voitures_possibles]

        voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
        nom_complet_gagnee = f"{voiture_gagnee['marque']} {voiture_gagnee['nom']} {voiture_gagnee.get('annee', '')}".strip()
        
        nouveau_garage.append(nom_complet_gagnee)
        pref = self.profil.get("sort_preference")
        if pref: nouveau_garage = appliquer_tri_garage(nouveau_garage, pref)

        update_query = {"$set": {"garage": nouveau_garage}}
        if nom_complet_gagnee in wishlist_joueur: update_query["$pull"] = {"wishlist": nom_complet_gagnee}

        user_id = str(self.user.id)
        await collection_inventaires.update_one({"_id": user_id}, update_query)

        # Affichage du résultat
        membres_serveur_ids = [str(m.id) for m in self.ctx.guild.members]
        curseur = collection_inventaires.find({
            "garage": nom_complet_gagnee,
            "_id": {"$in": membres_serveur_ids}
        })
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
        if voiture_gagnee.get('annee'): lignes.append(str(voiture_gagnee['annee']))
        lignes.append(voiture_gagnee.get('pays', '🏁'))
        lignes.append("")
        lignes.append("**Nouvelle Rareté**")
        lignes.append(self.rarete_gagne)
        lignes.append("")
        lignes.append("**⚙️ Spécifications**")
        lignes.append(f"Moteur : {voiture_gagnee.get('moteur', 'Inconnu')}")
        lignes.append(f"Puissance : {voiture_gagnee.get('puissance', 'Inconnue')}")
        lignes.append(f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu")
        lignes.append(classe_forza)
        lignes.append("")
        lignes.append("**Propriétaires :**")
        lignes.append(texte_proprietaires)

        couleur_dynamique = COULEURS_RARETE.get(self.rarete_gagne, discord.Color.purple())
        
        embed = discord.Embed(
            title=f"✨ FUSION RÉUSSIE : {nom_complet_gagnee}", 
            description="\n".join(lignes),
            color=couleur_dynamique
        )
        img_url = voiture_gagnee.get('image', '')
        if img_url and img_url.startswith(('http://', 'https://')): embed.set_image(url=img_url)

        voeu_exauce = "\n🌟 **VŒU EXAUCÉ !** Cette voiture a été retirée de ta wishlist." if nom_complet_gagnee in wishlist_joueur else ""

        await interaction.followup.send(content=f"🎉 {self.user.mention} **L'amélioration a fonctionné !**{voeu_exauce}", embed=embed)
        await verifier_succes_marque(self.ctx, user_id, voiture_gagnee['marque'])


@bot.hybrid_command(name="tradeup", description="Sacrifie 5 voitures de même rareté (Commun ou Rare) contre une de rang supérieur.")
async def tradeup(ctx, rarete: str):
    rarete_lower = rarete.lower().strip()
    map_rarete = {
        "commun": ("Commun ⚪", "Rare 🔵"),
        "commune": ("Commun ⚪", "Rare 🔵"),
        "blanc": ("Commun ⚪", "Rare 🔵"),
        "rare": ("Rare 🔵", "Mythique 🟣"),
        "bleu": ("Rare 🔵", "Mythique 🟣")
    }

    if rarete_lower not in map_rarete:
        await ctx.send(f"❌ {ctx.author.mention}, tu ne peux utiliser le trade-up que pour les raretés **Communes** ou **Rares**.\nExemple : `/tradeup commun`")
        return

    rarete_base, rarete_gagne = map_rarete[rarete_lower]

    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})
    garage = profil.get("garage", []) if profil else []

    voiture_map = {f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip(): v['rareté'] for v in VOITURES}
    
    # On filtre les voitures de la bonne rareté et on les trie par ordre alphabétique pour s'y retrouver
    voitures_eligibles = sorted([v for v in garage if voiture_map.get(v) == rarete_base])

    if len(voitures_eligibles) < 5:
        await ctx.send(f"❌ {ctx.author.mention}, il te faut au moins **5 voitures {rarete_base}** pour faire ce trade-up. Tu n'en as que {len(voitures_eligibles)}.")
        return

    view = TradeUpSelectionView(ctx, voitures_eligibles, rarete_base, rarete_gagne, profil, garage)
    await ctx.send(embed=view.get_embed(), view=view)
#endregion

#region sell
@bot.hybrid_command(name="sell", description="Vends une de tes voitures au concessionnaire.", aliases=["jeter", "poubelle", "vendre"])
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

@bot.hybrid_command(name="sellall", description="Vend absolument TOUTES tes voitures (action irréversible).", aliases=["liquider", "pieton"])
async def sellall(ctx):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})

    if not profil or not profil.get("garage"):
        await ctx.send(f"❌ Ton garage est déjà vide, {ctx.author.mention} ! Tu es déjà un piéton.")
        return

    garage = profil["garage"]
    nb_voitures = len(garage)
    
    # Calcul de la valeur totale du garage
    infos_voitures = {f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip(): PRIX_REVENTE.get(v['rareté'], 50) for v in VOITURES}
    valeur_totale = sum(infos_voitures.get(nom, 50) for nom in garage)

    # --- CONFIRMATION 1 ---
    msg1 = await ctx.send(f"⚠️ **ATTENTION {ctx.author.mention} !**\nTu es sur le point de vendre tes **{nb_voitures} voitures** pour un total de **{valeur_totale} 🪙**.\nEs-tu vraiment sûr de vouloir faire ça ?\n*Réagis avec ✅ pour continuer ou ❌ pour annuler.*")
    await msg1.add_reaction("✅")
    await msg1.add_reaction("❌")

    def check1(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg1.id

    try:
        reaction1, user1 = await bot.wait_for('reaction_add', timeout=30.0, check=check1)
        if str(reaction1.emoji) == "❌":
            return await ctx.send("Ouf... Vente annulée. Tes voitures ont eu la peur de leur vie.")
    except asyncio.TimeoutError:
        return await ctx.send(f"⏳ Temps écoulé, la vente massive est annulée.")

    # --- CONFIRMATION 2 ---
    msg2 = await ctx.send(f"🤨 **Hé, attends une seconde {ctx.author.mention}...**\nT'es vraiment sérieux ? Tu vas te retrouver sans rien. Tu comptes aller travailler en trottinette ou prendre le bus ?\n*Réagis avec ✅ si t'aimes les transports en commun, ou ❌ pour tout annuler.*")
    await msg2.add_reaction("✅")
    await msg2.add_reaction("❌")

    def check2(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg2.id

    try:
        reaction2, user2 = await bot.wait_for('reaction_add', timeout=30.0, check=check2)
        if str(reaction2.emoji) == "❌":
            return await ctx.send("Excellente décision. Le bus, c'est chiant. Vente annulée.")
    except asyncio.TimeoutError:
        return await ctx.send(f"⏳ Tu as trop hésité. Vente annulée.")

    # --- CONFIRMATION 3 ---
    msg3 = await ctx.send(f"🚨 **DERNIÈRE CHANCE {ctx.author.mention}** 🚨\nC'est le point de non-retour. L'action est **IRRÉVERSIBLE**. Si tu cliques sur ✅, le concessionnaire emporte tout et on ne pourra plus rien faire pour toi.\n*Tu valides ton pass Navigo ?*")
    await msg3.add_reaction("✅")
    await msg3.add_reaction("❌")

    def check3(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg3.id

    try:
        reaction3, user3 = await bot.wait_for('reaction_add', timeout=30.0, check=check3)
        if str(reaction3.emoji) == "❌":
            return await ctx.send("Mdr, je savais que t'aurais pas le courage. Vente annulée, ton garage est sauf.")
            
        # Si on arrive ici, les 3 confirmations ont été validées
        await collection_inventaires.update_one(
            {"_id": user_id},
            {
                "$set": {"garage": []},
                "$inc": {"coins": valeur_totale}
            }
        )
        
        await ctx.send(f"💥 **VENDU !** {ctx.author.mention} a complètement craqué et liquidé ses **{nb_voitures} voitures** pour **{valeur_totale} 🪙** !\nIl est maintenant officiellement piéton. Félicitations pour cette décision très discutable. 🚶‍♂️")

    except asyncio.TimeoutError:
        await ctx.send(f"⏳ Le temps a expiré, tes voitures sont sauvées de justesse.")
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
            if abs_index >= len(self.eligible_cars):
                btn.disabled = True
                btn.style = discord.ButtonStyle.secondary
            else:
                btn.disabled = False
                btn.style = discord.ButtonStyle.primary

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.eligible_cars[start:end]
        
        mon_garage = self.profil.get("garage", []) if self.profil else []
        
        lignes = []
        for i, voiture in enumerate(page_items):
            nom_complet = f"{voiture['marque']} {voiture['nom']} {voiture.get('annee', '')}".strip()
            possede = " ✅" if nom_complet in mon_garage else ""
            logo = LOGOS.get(voiture['marque'], "")
            
            lignes.append(f"{self.number_emojis[i]} {logo} **{voiture['marque']}** {voiture['nom']} {voiture.get('annee', '')} ({voiture['rareté']}){possede}")
            
        embed = discord.Embed(
            title=self.titre,
            description="Clique sur le numéro pour afficher les détails du modèle :\n\n" + "\n".join(lignes),
            color=self.couleur
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} | Total : {len(self.eligible_cars)} modèles")
        return embed

    async def display_car(self, interaction: discord.Interaction, idx_offset: int):
        if interaction.user != self.user:
            return await interaction.response.send_message("Ce n'est pas ta recherche !", ephemeral=True)
            
        abs_index = self.current_page * self.items_per_page + idx_offset
        if abs_index >= len(self.eligible_cars):
            return await interaction.response.defer()
            
        voiture_choisie = self.eligible_cars[abs_index]
        nom_complet = f"{voiture_choisie['marque']} {voiture_choisie['nom']} {voiture_choisie.get('annee', '')}".strip()
        
        # --- Construction de la carte de la voiture ---
        membres_serveur_ids = [str(m.id) for m in self.ctx.guild.members]
        curseur = collection_inventaires.find({
            "garage": nom_complet,
            "_id": {"$in": membres_serveur_ids}
        })
        docs = await curseur.to_list(length=100)
        
        proprietaires_mentions = [f"<@{doc['_id']}>" for doc in docs]
        texte_proprietaires = ", ".join(proprietaires_mentions) if proprietaires_mentions else "Personne ne possède ce bijou... 😢"

        rarete = voiture_choisie['rareté']
        couleur_dynamique = COULEURS_RARETE.get(rarete, discord.Color.green())
        
        mon_garage = self.profil.get("garage", []) if self.profil else []
        titre_possede = " ✅" if nom_complet in mon_garage else ""

        classe_forza = calculer_classe_forza(voiture_choisie)
        masse = voiture_choisie.get('masse_kg', 'Inconnu')
        logo = LOGOS.get(voiture_choisie['marque'], "")
        
        lignes = [
            voiture_choisie['nom'],
            f"{logo}**{voiture_choisie['marque']}**"
        ]
        if voiture_choisie.get('annee'):
            lignes.append(str(voiture_choisie['annee']))
        lignes.append(voiture_choisie.get('pays', '🏁'))
        lignes.append("")
        lignes.append("**Rareté**")
        lignes.append(rarete)
        lignes.append("")
        lignes.append("**⚙️ Spécifications**")
        lignes.append(f"Moteur : {voiture_choisie.get('moteur', 'Inconnu')}")
        lignes.append(f"Puissance : {voiture_choisie.get('puissance', 'Inconnue')}")
        lignes.append(f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu")
        lignes.append(classe_forza)
        lignes.append("")
        lignes.append("**Propriétaires :**")
        lignes.append(texte_proprietaires)

        embed_voiture = discord.Embed(
            title=f"🔍 {nom_complet}{titre_possede}", 
            description="\n".join(lignes),
            color=couleur_dynamique
        )
    
        img_url = voiture_choisie.get('image', '')
        if img_url and img_url.startswith(('http://', 'https://')):
            embed_voiture.set_image(url=img_url)
        else:
            embed_voiture.add_field(name="⚠️ Image indisponible", value="Le lien de cette image doit être corrigé dans le catalogue.", inline=False)

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
        if interaction.user != self.user: return await interaction.response.send_message("Tu n'as pas l'autorisation.", ephemeral=True)
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction, button):
        if interaction.user != self.user: return await interaction.response.send_message("Tu n'as pas l'autorisation.", ephemeral=True)
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.hybrid_command(name="search", description="Cherche un modèle précis, une marque, un pays ou une rareté.")
async def search(ctx, *, recherche: str):
    recherche_lower = recherche.lower().strip()
    
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id})

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
        
        "cinema": "🎬", "film": "🎬", "serie": "🎬",
        "jeu": "🎮", "jeux": "🎮", "jeux video": "🎮", "jeu video": "🎮",
        "pirate": "🏴‍‍☠️", "inconnu": "🏴‍☠️"
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

    else:
        # Recherche ultra-souple : on ignore les espaces, tirets et autres caractères spéciaux
        recherche_nettoyee = re.sub(r'[^a-z0-9]', '', recherche_lower)
        
        resultats = []
        for v in VOITURES:
            nom_complet = f"{v['marque']} {v['nom']} {v.get('annee', '')}".lower()
            nom_nettoye = re.sub(r'[^a-z0-9]', '', nom_complet)
            
            if recherche_nettoyee in nom_nettoye:
                resultats.append(v)
                
        titre_recherche = f"🔍 Résultats pour : {recherche}"
        couleur_embed = discord.Color.teal()

    if not resultats:
        await ctx.send(f"❌ Je n'ai trouvé aucun pays, rareté, marque ni modèle correspondant à **{recherche}**.")
        return
        
    resultats_tries = sorted(resultats, key=lambda x: (x.get('marque',''), x.get('nom','')))

    # Si la recherche ne retourne qu'un seul véhicule, on l'affiche directement (pas besoin de liste)
    if len(resultats_tries) == 1:
        voiture_choisie = resultats_tries[0]
        nom_complet = f"{voiture_choisie['marque']} {voiture_choisie['nom']} {voiture_choisie.get('annee', '')}".strip()
        
        membres_serveur_ids = [str(m.id) for m in ctx.guild.members]
        curseur = collection_inventaires.find({
            "garage": nom_complet,
            "_id": {"$in": membres_serveur_ids}
        })
        docs = await curseur.to_list(length=100)
        
        proprietaires_mentions = [f"<@{doc['_id']}>" for doc in docs]
        texte_proprietaires = ", ".join(proprietaires_mentions) if proprietaires_mentions else "Personne ne possède ce bijou... 😢"

        rarete = voiture_choisie['rareté']
        couleur_dynamique = COULEURS_RARETE.get(rarete, discord.Color.green())
        
        mon_garage = profil.get("garage", []) if profil else []
        titre_possede = " ✅" if nom_complet in mon_garage else ""

        classe_forza = calculer_classe_forza(voiture_choisie)
        masse = voiture_choisie.get('masse_kg', 'Inconnu')
        logo = LOGOS.get(voiture_choisie['marque'], "")
        
        lignes = [
            voiture_choisie['nom'],
            f"{logo}**{voiture_choisie['marque']}**"
        ]
        if voiture_choisie.get('annee'):
            lignes.append(str(voiture_choisie['annee']))
        lignes.append(voiture_choisie.get('pays', '🏁'))
        lignes.append("")
        lignes.append("**Rareté**")
        lignes.append(rarete)
        lignes.append("")
        lignes.append("**⚙️ Spécifications**")
        lignes.append(f"Moteur : {voiture_choisie.get('moteur', 'Inconnu')}")
        lignes.append(f"Puissance : {voiture_choisie.get('puissance', 'Inconnue')}")
        lignes.append(f"Poids : {masse} kg" if masse != "Inconnu" else "Poids : Inconnu")
        lignes.append(classe_forza)
        lignes.append("")
        lignes.append("**Propriétaires :**")
        lignes.append(texte_proprietaires)

        embed_voiture = discord.Embed(
            title=f"🔍 {nom_complet}{titre_possede}", 
            description="\n".join(lignes),
            color=couleur_dynamique
        )
    
        img_url = voiture_choisie.get('image', '')
        if img_url and img_url.startswith(('http://', 'https://')):
            embed_voiture.set_image(url=img_url)
        else:
            embed_voiture.add_field(name="⚠️ Image indisponible", value="Le lien de cette image doit être corrigé dans le catalogue.", inline=False)

        await ctx.send(embed=embed_voiture)
        return

    # S'il y a plusieurs résultats, on affiche l'interface interactive
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

@bot.hybrid_command(name="catalogue", description="Affiche la liste complète des voitures disponibles.", aliases=["catalog", "liste", "voitures"])
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
@bot.hybrid_command(name="fav", description="Définit ta marque favorite pour ton profil.", aliases=["favori", "favorite", "marque"])
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
@bot.hybrid_command(name="profil", description="Affiche la carte de joueur et les statistiques.", aliases=["profile", "stats", "statistiques", "me"])
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
@bot.hybrid_command(name="cmd", description="Affiche la liste de toutes les commandes du bot.", aliases=["commandes", "menu", "aide", "help"])
async def cmd(ctx):
    embed = discord.Embed(
        title="🛠️ Liste des commandes de Bouboule",
        description="Voici tout ce que je peux faire pour t'aider à bâtir le garage ultime :",
        color=discord.Color.blurple()
    )
    
    embed.add_field(
        name="🎰 Tirages & Souhaits", 
        value=(
            "**`/roll`** : Tire une voiture au hasard toutes les 2h (*`/timer` pour voir le délai*).\n"
            "**`/buyroll`** : Achète un tirage supplémentaire immédiat pour 5000 🪙.\n"
            "**`/wish [recherche]`** : Cherche un modèle ou une marque pour l'ajouter à ta wishlist.\n"
            "**`/unwish (modèle)`** : Affiche ta wishlist pour la gérer, ou retire un modèle précis.\n"
            "**`/wishlist`** : Affiche tes souhaits en cours."
        ),
        inline=False
    )
    
    embed.add_field(
        name="💰 Économie & Échanges", 
        value=(
            "**`/daily`** : Récupère ton salaire de 500 🪙 toutes les 24h (*`/dtimer` pour le délai*).\n"
            "**`/solde [@pseudo]`** : Affiche l'argent en banque.\n"
            "**`/sell [voiture]`** : Vends un de tes modèles au concessionnaire.\n"
            "**`/sellall`** : Vend absolument TOUTES tes voitures (action irréversible ⚠️).\n"
            "**`/trade @pseudo \"Ta Voiture\" \"Sa Voiture\"`** : Propose un échange équitable ou avec compensation.\n"
            "**`/tradeup [rareté]`** : Sacrifie 5 voitures de cette rareté pour en obtenir une de rang supérieur."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🚗 Gestion du Garage", 
        value=(
            "**`/garage [@pseudo] [page]`** : Affiche ta collection ou celle d'un ami.\n"
            "**`/sortrarity` / `/sortbrand` / `/sortyear` / `/sortpower` / `/sortclass`** : Trie ton garage.\n"
            "**`/search [mot-clé]`** : Cherche un modèle précis, une marque, un pays ou une rareté.\n"
            "**`/catalogue`** : Affiche le catalogue officiel de toutes les voitures disponibles.\n"
            "**`/fav [marque]`** : Mets en avant ta marque de cœur sur ton profil."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🏁 Compétition & Profil", 
        value=(
            "**`/profil [@pseudo]`** : Affiche la carte de joueur (Stats, Richesse, Score Elo, Succès).\n"
            "**`/toplist`** : Affiche les classements du serveur (Richesse, Pilotes, Collection, Valeur).\n"
            "**`/race @pseudo [mise] [Classe]`** : Provoque un joueur en duel sur une classe (D, C, B, A, S1, S2, X).\n"
            "**`/ranks`** : Liste les grades compétitifs et les points Elo requis pour monter en ligue."
        ),
        inline=False
    )

    if bot.user.avatar:
        embed.set_thumbnail(url=bot.user.avatar.url)
        
    embed.set_footer(text="Astuce : Utilise les commandes Slash (/) ! C'est plus pratique pour remplir les arguments (comme pour /trade ou /race).")

    await ctx.send(embed=embed)
#endregion

#region timer
@bot.hybrid_command(name="timer", description="Affiche le temps restant avant ton prochain !roll gratuit.", aliases=["cd", "cooldown", "temps"])
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
@bot.hybrid_command(name="dailytimer", description="Affiche le temps restant avant ton prochain salaire.", aliases=["dtimer", "dailycd", "tempsdaily"])
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
@bot.hybrid_command(name="solde", description="Affiche l'argent en banque d'un joueur.", aliases=["bal", "balance", "argent", "money"])
async def solde(ctx, membre: discord.Member = None):
    cible = membre or ctx.author
    profil = await collection_inventaires.find_one({"_id": str(cible.id)})
    
    coins = profil.get("coins", 0) if profil else 0
    await ctx.send(f"💳 Le solde de **{cible.display_name}** est de **{coins} 🪙**.")

@bot.hybrid_command(name="daily", description="Récupère ton salaire de 500 pièces toutes les 24h.")
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
            await ctx.send(f"⏳ Reviens plus tard {ctx.author.mention} ! Ton prochain salaire sera disponible dans **{heures}h et {minutes}m**.")
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
@bot.hybrid_command(name="buyroll", description="Achète un tirage supplémentaire immédiat pour 5000 pièces.")
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
    marque_favorite = profil.get("favorite_brand") if profil else None
    
    voitures_disponibles = []
    poids_disponibles = []

    for voiture in VOITURES:
        nom_complet = f"{voiture['marque']} {voiture['nom']} {voiture.get('annee', '')}".strip()
        if nom_complet not in voitures_possedees:
            voitures_disponibles.append(voiture)
            poids_calc = voiture.get("poids", 10)
            
            # NOUVEAU : Bonus x1.5 pour la marque favorite
            if marque_favorite and voiture['marque'] == marque_favorite:
                poids_calc *= 1.5
                
            if nom_complet in wishlist_joueur:
                poids_calc *= 2 
            
            poids_disponibles.append(poids_calc)

    if not voitures_disponibles:
        await ctx.send(f"🏆 Tu possèdes déjà **TOUTES** les voitures du jeu !")
        return

    voiture_gagnee = random.choices(voitures_disponibles, weights=poids_disponibles, k=1)[0]
    nom_complet_gagnee = f"{voiture_gagnee['marque']} {voiture_gagnee['nom']} {voiture_gagnee.get('annee', '')}".strip()
    print(f"[LOG 🎰] {ctx.author.name} a obtenu : {nom_complet_gagnee}")
    rarete = voiture_gagnee['rareté']

    # Application du tri automatique sur le nouveau garage
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

    membres_serveur_ids = [str(m.id) for m in ctx.guild.members]
    curseur = collection_inventaires.find({
        "garage": nom_complet_gagnee,
        "_id": {"$in": membres_serveur_ids}
    })
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
    elif marque_favorite and voiture_gagnee['marque'] == marque_favorite:
        voeu_exauce = "\n\n⭐ **BINGO !** Ta fidélité a payé, tu viens d'obtenir un modèle de ta marque favorite !"

    await verifier_succes_marque(ctx, user_id, voiture_gagnee['marque'])
    await ctx.send(content=f"{ctx.author.mention} **{phrase} !**{voeu_exauce}", embed=embed)
#endregion

#region leaderboard
@bot.hybrid_command(name="toplist", description="Affiche le classement officiel du serveur.", aliases=["top", "lb", "classement", "leaderboard"])
async def toplist(ctx):
    # 1. On récupère la liste des IDs (en texte) de tous les membres actuels du serveur
    membres_serveur_ids = [str(membre.id) for membre in ctx.guild.members]

    # 2. On demande à MongoDB de ne chercher QUE les profils dont l'_id est dans cette liste
    profils = await collection_inventaires.find({"_id": {"$in": membres_serveur_ids}}).to_list(length=1000)

    if not profils:
        await ctx.send("❌ Aucun joueur de ce serveur n'est enregistré dans la base de données pour le moment !")
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
        title=f"🏆 Classement Officiel - {ctx.guild.name}", # NOUVEAU : Affiche le nom du serveur
        description="Qui dominera le marché automobile ici ?\n\u200b", 
        color=discord.Color.gold()
    )
    
    embed.add_field(name="💰 Top Richesse", value=texte_coins, inline=False)
    embed.add_field(name="🏁 Top Pilotes (Elo)", value=texte_elo, inline=False)
    embed.add_field(name="🚗 Top Collection", value=texte_garage, inline=False)
    embed.add_field(name="💎 Valeur Garage", value=texte_valeur, inline=False)
    
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None) 
    
    await ctx.send(embed=embed)
#endregion

#region wishlist
class WishSelectionView(discord.ui.View):
    def __init__(self, ctx, user, eligible_cars, profil, titre="🌟 Gestion de la Wishlist"):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.user = user
        self.eligible_cars = eligible_cars
        self.profil = profil
        self.titre = titre
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, math.ceil(len(eligible_cars) / self.items_per_page))
        self.number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        self.update_buttons()

    def update_buttons(self):
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page >= self.total_pages - 1)
        
        boutons_nombres = [self.btn_1, self.btn_2, self.btn_3, self.btn_4, self.btn_5]
        wishlist = self.profil.get("wishlist", [])
        
        for i, btn in enumerate(boutons_nombres):
            abs_index = self.current_page * self.items_per_page + i
            if abs_index >= len(self.eligible_cars):
                btn.disabled = True
                btn.style = discord.ButtonStyle.secondary
            else:
                btn.disabled = False
                voiture = self.eligible_cars[abs_index]
                nom_complet = f"{voiture['marque']} {voiture['nom']} {voiture.get('annee', '')}".strip()
                # Si la voiture est déjà dans la wishlist, le bouton devient vert
                if nom_complet in wishlist:
                    btn.style = discord.ButtonStyle.success
                else:
                    btn.style = discord.ButtonStyle.primary

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.eligible_cars[start:end]
        
        lignes = []
        wishlist = self.profil.get("wishlist", [])
        garage = self.profil.get("garage", [])
        
        for i, voiture in enumerate(page_items):
            nom_complet = f"{voiture['marque']} {voiture['nom']} {voiture.get('annee', '')}".strip()
            
            etat = ""
            if nom_complet in wishlist:
                etat = " 🌟 *(Dans la wishlist)*"
            elif nom_complet in garage:
                etat = " ✅ *(Déjà possédé)*"
                
            logo = LOGOS.get(voiture['marque'], "")
            lignes.append(f"{self.number_emojis[i]} {logo} **{voiture['marque']}** {voiture['nom']} {voiture.get('annee', '')} ({voiture['rareté']}){etat}")
            
        embed = discord.Embed(
            title=self.titre,
            description="Clique sur un numéro pour l'ajouter ou le retirer de ta wishlist :\n\n" + "\n".join(lignes),
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} | Ta wishlist contient {len(wishlist)}/10 modèles")
        return embed

    async def toggle_wishlist(self, interaction: discord.Interaction, idx_offset: int):
        if interaction.user != self.user:
            return await interaction.response.send_message("Ce n'est pas ta recherche !", ephemeral=True)
            
        abs_index = self.current_page * self.items_per_page + idx_offset
        if abs_index >= len(self.eligible_cars):
            return await interaction.response.defer()
            
        voiture_choisie = self.eligible_cars[abs_index]
        nom_complet = f"{voiture_choisie['marque']} {voiture_choisie['nom']} {voiture_choisie.get('annee', '')}".strip()
        
        # On met à jour le profil pour avoir les données fraîches
        self.profil = await collection_inventaires.find_one({"_id": str(self.user.id)}) or {}
        wishlist = self.profil.get("wishlist", [])
        garage = self.profil.get("garage", [])
        
        if nom_complet in garage:
            return await interaction.response.send_message(f"❌ Tu possèdes déjà la **{nom_complet}** dans ton garage !", ephemeral=True)
            
        if nom_complet in wishlist:
            # S'il y est déjà, on le retire (Toggle)
            await collection_inventaires.update_one(
                {"_id": str(self.user.id)},
                {"$pull": {"wishlist": nom_complet}}
            )
            self.profil["wishlist"].remove(nom_complet)
            await interaction.response.send_message(f"🗑️ **{nom_complet}** a été retirée de ta wishlist.", ephemeral=True)
        else:
            # S'il n'y est pas, on l'ajoute
            if len(wishlist) >= 10:
                return await interaction.response.send_message(f"❌ Ta wishlist est pleine (10/10) ! Retire des modèles d'abord.", ephemeral=True)
                
            await collection_inventaires.update_one(
                {"_id": str(self.user.id)},
                {"$push": {"wishlist": nom_complet}},
                upsert=True
            )
            if "wishlist" not in self.profil:
                self.profil["wishlist"] = []
            self.profil["wishlist"].append(nom_complet)
            await interaction.response.send_message(f"🌟 **{nom_complet}** a été ajoutée à ta wishlist !", ephemeral=True)

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
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction, button):
        if interaction.user != self.user: return
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.hybrid_command(name="wish", description="Ajoute une voiture à ta liste de souhaits.")
async def wish(ctx, *, recherche: str):
    user_id = str(ctx.author.id)
    recherche_lower = recherche.lower().strip()
    recherche_nettoyee = re.sub(r'[^a-z0-9]', '', recherche_lower)
    
    # Recherche souple
    resultats = []
    for v in VOITURES:
        nom_complet = f"{v['marque']} {v['nom']} {v.get('annee', '')}".lower()
        nom_nettoye = re.sub(r'[^a-z0-9]', '', nom_complet)
        
        if recherche_nettoyee in nom_nettoye:
            resultats.append(v)
            
    if not resultats:
        await ctx.send(f"❌ Je n'ai trouvé aucune voiture correspondant à **{recherche}**.")
        return
        
    profil = await collection_inventaires.find_one({"_id": user_id}) or {}
    
    # S'il n'y a qu'un seul résultat, on l'ajoute directement pour gagner du temps
    if len(resultats) == 1:
        voiture_choisie = resultats[0]
        nom_complet = f"{voiture_choisie['marque']} {voiture_choisie['nom']} {voiture_choisie.get('annee', '')}".strip()
        
        garage = profil.get("garage", [])
        wishlist = profil.get("wishlist", [])
        
        if nom_complet in garage:
            await ctx.send(f"❌ Tu possèdes déjà la **{nom_complet}** dans ton garage !")
            return
            
        if nom_complet in wishlist:
            await ctx.send(f"⚠️ La **{nom_complet}** est déjà dans ta wishlist !")
            return
            
        if len(wishlist) >= 10:
            await ctx.send(f"❌ Ta wishlist est pleine (10/10) ! Utilise `/unwish` pour faire de la place.")
            return
            
        await collection_inventaires.update_one(
            {"_id": user_id},
            {"$push": {"wishlist": nom_complet}},
            upsert=True
        )
        await ctx.send(f"🌟 **{nom_complet}** a été ajoutée à ta wishlist ! (Ses chances d'apparition sont multipliées par 2).")
        return

    # S'il y a plusieurs résultats, on affiche l'interface interactive avec les boutons
    resultats_tries = sorted(resultats, key=lambda x: (x.get('marque',''), x.get('nom','')))
    view = WishSelectionView(ctx, ctx.author, resultats_tries, profil, titre="🌟 Ajout à la Wishlist")
    await ctx.send(embed=view.get_embed(), view=view)

@bot.hybrid_command(name="unwish", description="Retire une voiture de ta liste de souhaits.")
async def unwish(ctx, *, recherche: Optional[str] = None):
    user_id = str(ctx.author.id)
    profil = await collection_inventaires.find_one({"_id": user_id}) or {}
    wishlist_noms = profil.get("wishlist", [])
    
    if not wishlist_noms:
        await ctx.send("❌ Ta wishlist est déjà vide !")
        return
        
    # Reconvertir les noms de la wishlist en objets 'voiture' pour la View
    voitures_wishlist = []
    for nom in wishlist_noms:
        voiture_trouvee = next((v for v in VOITURES if f"{v['marque']} {v['nom']} {v.get('annee', '')}".strip() == nom), None)
        if voiture_trouvee:
            voitures_wishlist.append(voiture_trouvee)
            
    if recherche:
        recherche_lower = recherche.lower().strip()
        recherche_nettoyee = re.sub(r'[^a-z0-9]', '', recherche_lower)
        
        resultats = []
        for v in voitures_wishlist:
            nom_complet = f"{v['marque']} {v['nom']} {v.get('annee', '')}".lower()
            nom_nettoye = re.sub(r'[^a-z0-9]', '', nom_complet)
            if recherche_nettoyee in nom_nettoye:
                resultats.append(v)
                
        if not resultats:
            await ctx.send(f"❌ Aucune voiture correspondant à **{recherche}** n'a été trouvée dans ta wishlist.")
            return
            
        if len(resultats) == 1:
            voiture_a_retirer = f"{resultats[0]['marque']} {resultats[0]['nom']} {resultats[0].get('annee', '')}".strip()
            await collection_inventaires.update_one(
                {"_id": user_id},
                {"$pull": {"wishlist": voiture_a_retirer}}
            )
            await ctx.send(f"🗑️ **{voiture_a_retirer}** a été retirée de ta wishlist.")
            return
            
        voitures_a_afficher = resultats
    else:
        # Si on n'a rien tapé, on affiche toute la wishlist
        voitures_a_afficher = voitures_wishlist
        
    # S'il y a plusieurs résultats (ou qu'on veut voir toute la liste), on affiche l'interface
    voitures_triees = sorted(voitures_a_afficher, key=lambda x: (x.get('marque',''), x.get('nom','')))
    
    # On réutilise la même vue qui gère déjà très bien l'ajout et le retrait !
    view = WishSelectionView(ctx, ctx.author, voitures_triees, profil, titre="🗑️ Retrait de la Wishlist")
    await ctx.send(content="Voici les modèles correspondants. Clique sur un numéro pour le désélectionner :", embed=view.get_embed(), view=view)

@bot.hybrid_command(name="wishlist", description="Affiche ta liste de souhaits en cours.", aliases=["wl", "wishlists"])
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
            logo = LOGOS.get(voiture_info['marque'], "")
            description += f"**{i}.** {logo} {nom_complet} - *{voiture_info['rareté']}*\n"
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
@bot.hybrid_command(name="ranks", description="Affiche la liste des rangs compétitifs et les points Elo requis.", aliases=["ranklist", "elos", "grades"])
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

# NOUVEAU : Système de sélection avec boutons interactifs (1 à 5)
class RaceSelectionView(discord.ui.View):
    def __init__(self, ctx, user, eligible_cars, titre):
        super().__init__(timeout=60) # 60 secondes pour choisir
        self.ctx = ctx
        self.user = user 
        self.eligible_cars = eligible_cars
        self.titre = titre
        self.current_page = 0
        self.items_per_page = 5
        self.total_pages = max(1, math.ceil(len(eligible_cars) / self.items_per_page))
        self.number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        self.selected_car = None
        self.update_buttons()

    def update_buttons(self):
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_next.disabled = (self.current_page >= self.total_pages - 1)
        
        boutons_nombres = [self.btn_1, self.btn_2, self.btn_3, self.btn_4, self.btn_5]
        for i, btn in enumerate(boutons_nombres):
            abs_index = self.current_page * self.items_per_page + i
            if abs_index >= len(self.eligible_cars):
                btn.disabled = True
                btn.style = discord.ButtonStyle.secondary
            else:
                btn.disabled = False
                btn.style = discord.ButtonStyle.primary

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.eligible_cars[start:end]
        
        lignes = []
        for i, voiture in enumerate(page_items):
            lignes.append(f"{self.number_emojis[i]} **{voiture}**")
            
        embed = discord.Embed(
            title=self.titre,
            description="Clique sur le numéro de la voiture que tu souhaites piloter :\n\n" + "\n".join(lignes),
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages}")
        return embed

    async def select_item(self, interaction: discord.Interaction, idx_offset: int):
        if interaction.user != self.user:
            return await interaction.response.send_message("Ce n'est pas à ton tour de choisir !", ephemeral=True)
            
        abs_index = self.current_page * self.items_per_page + idx_offset
        if abs_index < len(self.eligible_cars):
            self.selected_car = self.eligible_cars[abs_index]
            # On désactive tout une fois le choix fait
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop() # Arrête l'attente de la vue

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
        if interaction.user != self.user: return await interaction.response.send_message("Tu n'as pas l'autorisation.", ephemeral=True)
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction, button):
        if interaction.user != self.user: return await interaction.response.send_message("Tu n'as pas l'autorisation.", ephemeral=True)
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

@bot.hybrid_command(name="race", description="Provoque un joueur en duel sur une classe précise.", aliases=["course", "duel"])
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

    # 3. Choix de l'Attaquant
    titre_a = f"🏁 Duel en Classe {classe_voulue} - Choix de {ctx.author.display_name}"
    view_a = RaceSelectionView(ctx, ctx.author, voitures_a, titre_a)
    msg_select_a = await ctx.send(
        content=f"{ctx.author.mention}, choisis ta monture pour ce duel :",
        embed=view_a.get_embed(), 
        view=view_a
    )

    await view_a.wait() # Attend que l'utilisateur clique sur un numéro ou que les 60s s'écoulent
    
    if not view_a.selected_car:
        return await ctx.send(f"⏳ Temps écoulé, {ctx.author.display_name}. La course est annulée.")
        
    ma_voiture_exacte = view_a.selected_car
    try: await msg_select_a.delete()
    except: pass

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

    # 5. Choix du Défenseur
    titre_b = f"🔥 Défi accepté ! Choix de {membre.display_name}"
    view_b = RaceSelectionView(ctx, membre, voitures_b, titre_b)
    msg_select_b = await ctx.send(
        content=f"{membre.mention}, choisis avec quoi tu vas l'affronter :",
        embed=view_b.get_embed(), 
        view=view_b
    )

    await view_b.wait()
    
    if not view_b.selected_car:
        return await ctx.send(f"⏳ Trop lent pour choisir la voiture... La course est annulée !")
        
    sa_voiture_exacte = view_b.selected_car
    try: await msg_select_b.delete()
    except: pass

    # 6. Lancement de la Course
    ratio_a = obtenir_ratio(ma_voiture_exacte)
    ratio_b = obtenir_ratio(sa_voiture_exacte)

    vitesse_base_a = max(1.0, min(12.0, 15.0 - ratio_a))
    vitesse_base_b = max(1.0, min(12.0, 15.0 - ratio_b))

    LONGUEUR_PISTE = 20
    pos_a = 0.0
    pos_b = 0.0
    
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
        await ctx.send(f"❌ **Erreur de syntaxe.**\nUtilise la commande dans cet ordre :\n`/race @pseudo <montant> <Classe>`")
#endregion

# 4. Lancement
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
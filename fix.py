import json
import os

FICHIER_JSON = "cars.json"
DOSSIER_IMAGES = "images_webp"
NOUVELLE_BASE_URL = "https://cdn.jsdelivr.net/gh/SkullViper7/bouboulebot@main/images_webp"

with open(FICHIER_JSON, "r", encoding="utf-8") as f:
    cars = json.load(f)

modifies = 0
for car in cars:
    car_id = car["id"]
    ancienne_url = car.get("image", "")
    fichier_local = os.path.join(DOSSIER_IMAGES, f"{car_id}.webp")

    # Remplace le lien s'il pointait déjà vers ton dépôt ou si l'image .webp existe en local
    if "SkullViper7/bouboulebot" in ancienne_url or os.path.exists(fichier_local):
        car["image"] = f"{NOUVELLE_BASE_URL}/{car_id}.webp"
        modifies += 1

with open(FICHIER_JSON, "w", encoding="utf-8") as f:
    json.dump(cars, f, ensure_ascii=False, indent=4)

print(f"✅ Terminé ! {modifies}/{len(cars)} liens mis à jour.")
print(f"Exemple : {cars[0]['image']}")
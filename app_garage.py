import json
import os
import math
import customtkinter as ctk
from tkinter import messagebox, filedialog
from PIL import Image

# Configuration de base du design
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

FICHIER_JSON = 'cars.json'
DOSSIER_IMAGES = 'images_webp'
BASE_URL = "https://raw.githubusercontent.com/SkullViper7/bouboulebot/main/images_webp"

# Paramètres d'optimisation WebP
WEBP_QUALITY = 82
MAX_WIDTH = 1280

# Dictionnaire des raretés
RARETES = {
    "Commun ⚪": {"couleur": "#D3D3D3", "poids": 100},
    "Rare 🔵": {"couleur": "#1E90FF", "poids": 30},
    "Mythique 🟣": {"couleur": "#8A2BE2", "poids": 8},
    "Légendaire 🟡": {"couleur": "#FFD700", "poids": 2},
    "GOAT 🔴": {"couleur": "#FF0000", "poids": 1}
}


class FormulaireVoiture(ctk.CTkToplevel):
    def __init__(self, parent, voiture_data=None, index=None, callback=None):
        super().__init__(parent)
        self.parent = parent
        self.title("Nouvel Élément - Gestionnaire de Voitures" if not voiture_data else "Modifier l'Élément")
        self.geometry("680x680")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.voiture_data = voiture_data
        self.index = index
        self.callback = callback
        self.rarete_selectionnee = ctk.StringVar(value="Commun ⚪")
        self.chemin_image_locale = None
        self.apercu_ctk = None

        # Récupération dynamique directement depuis la base de données propre
        self.marques_existantes = sorted(list(set(v.get("marque", "").strip() for v in parent.voitures if v.get("marque", "").strip())))
        self.pays_existants = sorted(list(set(v.get("pays", "🏁 Par défaut").strip() for v in parent.voitures if v.get("pays", "").strip())))

        # Mémoire des marques pour deviner le pays
        self.marque_to_pays = {}
        for v in parent.voitures:
            m = v.get("marque", "").strip()
            p = v.get("pays", "🏁 Par défaut").strip()
            if m and p and p != "🏁 Par défaut" and m not in self.marque_to_pays:
                self.marque_to_pays[m] = p

        if not self.marques_existantes:
            self.marques_existantes = ["Bugatti"]
        if not self.pays_existants:
            self.pays_existants = ["🏁 Par défaut"]

        self.after_id_marque = None
        self.after_id_pays = None

        self.setup_ui()

        if self.voiture_data:
            self.charger_donnees()
        else:
            self.combo_marque.set("")
            self.combo_pays.set("")

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        frame_gauche = ctk.CTkFrame(self, fg_color="transparent")
        frame_gauche.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        # Modèle
        ctk.CTkLabel(frame_gauche, text="Modèle", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.entry_modele = ctk.CTkEntry(frame_gauche, placeholder_text="Ex: Veyron 16.4", width=350)
        self.entry_modele.pack(pady=(0, 10), anchor="w")

        # Marque
        ctk.CTkLabel(frame_gauche, text="Marque", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        frame_marque = ctk.CTkFrame(frame_gauche, fg_color="transparent")
        frame_marque.pack(pady=(0, 10), anchor="w")

        self.combo_marque = ctk.CTkComboBox(frame_marque, values=self.marques_existantes, width=300, command=self.auto_fill_pays)
        self.combo_marque.pack(side="left")
        self.combo_marque._entry.bind('<KeyRelease>', self.autocomplete_marque)
        self.combo_marque._entry.bind('<FocusOut>', lambda e: self.auto_fill_pays(self.combo_marque.get()))

        btn_add_marque = ctk.CTkButton(frame_marque, text="+", width=40, command=self.ajouter_nouvelle_marque)
        btn_add_marque.pack(side="left", padx=(10, 0))

        # Année
        ctk.CTkLabel(frame_gauche, text="Année", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.entry_annee = ctk.CTkEntry(frame_gauche, placeholder_text="Ex: 2013", width=350)
        self.entry_annee.pack(pady=(0, 10), anchor="w")

        # Pays
        ctk.CTkLabel(frame_gauche, text="Pays (Drapeau)", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        frame_pays = ctk.CTkFrame(frame_gauche, fg_color="transparent")
        frame_pays.pack(pady=(0, 10), anchor="w")

        self.combo_pays = ctk.CTkComboBox(frame_pays, values=self.pays_existants, width=300)
        self.combo_pays.pack(side="left")
        self.combo_pays._entry.bind('<KeyRelease>', self.autocomplete_pays)

        btn_add_pays = ctk.CTkButton(frame_pays, text="+", width=40, command=self.ajouter_nouveau_pays)
        btn_add_pays.pack(side="left", padx=(10, 0))

        # Moteur
        ctk.CTkLabel(frame_gauche, text="Moteur", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.entry_moteur = ctk.CTkEntry(frame_gauche, placeholder_text="Ex: V8 4.0L Bi-Turbo", width=350)
        self.entry_moteur.pack(pady=(0, 10), anchor="w")

        # Puissance
        ctk.CTkLabel(frame_gauche, text="Puissance", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.entry_puissance = ctk.CTkEntry(frame_gauche, placeholder_text="Ex: 600 ch", width=350)
        self.entry_puissance.pack(pady=(0, 10), anchor="w")

        # Masse
        ctk.CTkLabel(frame_gauche, text="Masse (kg)", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.entry_masse = ctk.CTkEntry(frame_gauche, placeholder_text="Ex: 1500", width=350)
        self.entry_masse.pack(pady=(0, 10), anchor="w")

        # Rareté
        ctk.CTkLabel(frame_gauche, text="Rareté", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        frame_rarete = ctk.CTkFrame(frame_gauche, fg_color="transparent")
        frame_rarete.pack(pady=(0, 10), anchor="w")

        self.boutons_rarete = {}
        for nom_rarete, info in RARETES.items():
            btn = ctk.CTkButton(
                frame_rarete, text="", width=40, height=25, corner_radius=15,
                fg_color=info["couleur"], hover_color=info["couleur"],
                command=lambda r=nom_rarete: self.selectionner_rarete(r)
            )
            btn.pack(side="left", padx=(0, 10))
            self.boutons_rarete[nom_rarete] = btn

        # Importation d'image locale
        ctk.CTkLabel(frame_gauche, text="Image du véhicule", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        frame_image = ctk.CTkFrame(frame_gauche, fg_color="transparent")
        frame_image.pack(pady=(0, 15), anchor="w")

        self.btn_importer_image = ctk.CTkButton(
            frame_image,
            text="📁 Importer une image",
            width=180,
            fg_color="#3B3B3B",
            hover_color="#4D4D4D",
            command=self.importer_image
        )
        self.btn_importer_image.pack(side="left")

        self.lbl_fichier_image = ctk.CTkLabel(
            frame_image,
            text="Aucune image sélectionnée",
            font=("Segoe UI", 11),
            text_color="gray"
        )
        self.lbl_fichier_image.pack(side="left", padx=(10, 0))

        # Panneau droit (Validation + Aperçu)
        frame_droit = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=10)
        frame_droit.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        btn_valider = ctk.CTkButton(
            frame_droit, text="Valider", font=("Segoe UI", 16, "bold"),
            height=45, command=self.sauvegarder
        )
        btn_valider.pack(padx=20, pady=(30, 20), fill="x")

        ctk.CTkLabel(frame_droit, text="Aperçu", font=("Segoe UI", 12, "bold"), text_color="gray").pack(pady=(10, 5))
        self.lbl_apercu = ctk.CTkLabel(
            frame_droit,
            text="Aucune image",
            width=180,
            height=120,
            fg_color="#1E1E1E",
            corner_radius=8,
            text_color="gray"
        )
        self.lbl_apercu.pack(padx=15, pady=5)

        self.selectionner_rarete("Commun ⚪")

    def afficher_apercu(self, chemin_image):
        try:
            img = Image.open(chemin_image)
            img.thumbnail((180, 120), Image.Resampling.LANCZOS)
            self.apercu_ctk = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self.lbl_apercu.configure(image=self.apercu_ctk, text="")
        except Exception:
            self.lbl_apercu.configure(image=None, text="Aperçu indisponible")

    def importer_image(self):
        fichier = filedialog.askopenfilename(
            parent=self,
            title="Choisir l'image de la voiture",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                ("Tous les fichiers", "*.*")
            ]
        )
        if fichier:
            self.chemin_image_locale = fichier
            nom_fichier = os.path.basename(fichier)
            if len(nom_fichier) > 22:
                nom_fichier = nom_fichier[:19] + "..."
            self.lbl_fichier_image.configure(text=f"✅ {nom_fichier}", text_color="#4CAF50")
            self.afficher_apercu(fichier)

    def convertir_et_enregistrer_webp(self, chemin_source, car_id):
        os.makedirs(DOSSIER_IMAGES, exist_ok=True)
        chemin_destination = os.path.join(DOSSIER_IMAGES, f"{car_id}.webp")

        img = Image.open(chemin_source)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        if img.width > MAX_WIDTH:
            ratio = MAX_WIDTH / img.width
            nouvelle_hauteur = int(img.height * ratio)
            img = img.resize((MAX_WIDTH, nouvelle_hauteur), Image.Resampling.LANCZOS)

        img.save(chemin_destination, "WEBP", quality=WEBP_QUALITY, method=6)
        return f"{BASE_URL}/{car_id}.webp"

    def auto_fill_pays(self, choice=None):
        marque_choisie = choice if choice else self.combo_marque.get().strip()
        if marque_choisie in self.marque_to_pays:
            self.combo_pays.set(self.marque_to_pays[marque_choisie])

    def autocomplete_marque(self, event):
        if event.keysym in ('BackSpace', 'Left', 'Right', 'Up', 'Down', 'Delete', 'Shift_L', 'Shift_R', 'Tab', 'Return'):
            return
        if self.after_id_marque:
            self.after_cancel(self.after_id_marque)
        self.after_id_marque = self.after(150, self.process_autocomplete_marque)

    def process_autocomplete_marque(self):
        texte_actuel = self.combo_marque.get()
        if not texte_actuel:
            return
        for marque in self.marques_existantes:
            if marque.lower().startswith(texte_actuel.lower()):
                self.combo_marque.set(marque)
                self.combo_marque._entry.select_range(len(texte_actuel), 'end')
                self.combo_marque._entry.icursor(len(texte_actuel))
                self.auto_fill_pays(marque)
                break

    def autocomplete_pays(self, event):
        if event.keysym in ('BackSpace', 'Left', 'Right', 'Up', 'Down', 'Delete', 'Shift_L', 'Shift_R', 'Tab', 'Return'):
            return
        if self.after_id_pays:
            self.after_cancel(self.after_id_pays)
        self.after_id_pays = self.after(150, self.process_autocomplete_pays)

    def process_autocomplete_pays(self):
        texte_actuel = self.combo_pays.get()
        if not texte_actuel:
            return
        for pays in self.pays_existants:
            nom_sans_emoji = pays.split(" ", 1)[-1] if " " in pays else pays
            if pays.lower().startswith(texte_actuel.lower()) or nom_sans_emoji.lower().startswith(texte_actuel.lower()):
                self.combo_pays.set(pays)
                self.combo_pays._entry.select_range(len(texte_actuel), 'end')
                self.combo_pays._entry.icursor(len(texte_actuel))
                break

    def selectionner_rarete(self, rarete):
        self.rarete_selectionnee.set(rarete)
        for nom, btn in self.boutons_rarete.items():
            if nom == rarete:
                btn.configure(border_width=3, border_color="white", text="✓")
            else:
                btn.configure(border_width=0, text="")

    def ajouter_nouvelle_marque(self):
        dialog = ctk.CTkInputDialog(text="Entrez la nouvelle marque :", title="Ajouter une marque")
        nouvelle = dialog.get_input()
        if nouvelle and nouvelle.strip():
            nouvelle = nouvelle.strip()
            valeurs_actuelles = self.combo_marque.cget("values")
            if nouvelle not in valeurs_actuelles:
                valeurs_actuelles.append(nouvelle)
                valeurs_actuelles.sort()
                self.combo_marque.configure(values=valeurs_actuelles)
                self.marques_existantes = valeurs_actuelles
            self.combo_marque.set(nouvelle)

    def ajouter_nouveau_pays(self):
        dialog = ctk.CTkInputDialog(text="Entrez le nouveau drapeau + Pays\n(Ex: 🇧🇪 Belgique) :", title="Ajouter un drapeau")
        nouvelle = dialog.get_input()
        if nouvelle and nouvelle.strip():
            nouvelle = nouvelle.strip()
            valeurs_actuelles = self.combo_pays.cget("values")
            if nouvelle not in valeurs_actuelles:
                valeurs_actuelles.append(nouvelle)
                valeurs_actuelles.sort()
                self.combo_pays.configure(values=valeurs_actuelles)
                self.pays_existants = valeurs_actuelles
            self.combo_pays.set(nouvelle)

    def charger_donnees(self):
        self.entry_modele.insert(0, self.voiture_data["nom"])
        self.combo_marque.set(self.voiture_data["marque"])
        self.entry_annee.insert(0, str(self.voiture_data.get("annee", "")))
        self.combo_pays.set(self.voiture_data.get("pays", "🏁 Par défaut"))
        self.entry_moteur.insert(0, self.voiture_data.get("moteur", "Inconnu"))
        self.entry_puissance.insert(0, self.voiture_data.get("puissance", "Inconnue"))
        self.entry_masse.insert(0, str(self.voiture_data.get("masse_kg", "Inconnu")))

        car_id = self.voiture_data.get("id")
        chemin_local_existant = os.path.join(DOSSIER_IMAGES, f"{car_id}.webp") if car_id else ""

        if chemin_local_existant and os.path.exists(chemin_local_existant):
            self.lbl_fichier_image.configure(text=f"📁 {car_id}.webp (actuelle)", text_color="#64B5F6")
            self.afficher_apercu(chemin_local_existant)
        elif self.voiture_data.get("image"):
            self.lbl_fichier_image.configure(text="🌐 Lien existant conservé", text_color="#64B5F6")

        rarete = self.voiture_data.get("rareté", "Commun ⚪")
        if rarete not in RARETES:
            rarete = "Commun ⚪"
        self.selectionner_rarete(rarete)

    def sauvegarder(self):
        modele = self.entry_modele.get().strip()
        marque = self.combo_marque.get().strip()
        annee = self.entry_annee.get().strip()
        pays = self.combo_pays.get().strip()
        moteur = self.entry_moteur.get().strip()
        puissance = self.entry_puissance.get().strip()
        masse = self.entry_masse.get().strip()
        rarete = self.rarete_selectionnee.get()

        if not modele or not marque:
            messagebox.showerror("Erreur", "Le Modèle et la Marque sont obligatoires !", parent=self)
            return

        if not self.chemin_image_locale and not (self.voiture_data and self.voiture_data.get("image")):
            messagebox.showerror("Erreur", "Veuillez importer une image pour ce véhicule !", parent=self)
            return

        # Détermination de l'ID avant de sauvegarder le fichier image
        if self.voiture_data and "id" in self.voiture_data:
            car_id = self.voiture_data["id"]
        else:
            max_id = max([v.get("id", 0) for v in self.parent.voitures], default=0)
            car_id = max_id + 1

        # Traitement de l'image
        if self.chemin_image_locale:
            try:
                url = self.convertir_et_enregistrer_webp(self.chemin_image_locale, car_id)
            except Exception as e:
                messagebox.showerror("Erreur Image", f"Impossible de convertir l'image :\n{e}", parent=self)
                return
        else:
            url = self.voiture_data.get("image", "")

        if not pays:
            pays = "🏁 Par défaut"

        if puissance and puissance.lower() not in ["inconnu", "inconnue"]:
            if not puissance.lower().endswith("ch"):
                puissance = f"{puissance} ch"

        nouvelle_voiture = {
            "id": car_id,
            "nom": modele,
            "marque": marque,
            "annee": annee,
            "pays": pays,
            "rareté": rarete,
            "poids": RARETES[rarete]["poids"],
            "image": url,
            "moteur": moteur if moteur else "Inconnu",
            "puissance": puissance if puissance else "Inconnue",
            "masse_kg": masse if masse else "Inconnu"
        }

        if self.callback:
            self.callback(nouvelle_voiture, self.index)

        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Accueil - Gestionnaire de Voitures")
        self.geometry("900x600")
        self.voitures = []
        self.after_id = None

        self.sort_col = None
        self.sort_order = 0
        self.page_actuelle = 1
        self.elements_par_page = 50

        self.active_sorts = []

        self.charger_json()
        self.setup_ui()
        self.afficher_liste()

    def nettoyer_pays_dynamique(self):
        emoji_to_name = {}
        for v in self.voitures:
            p = v.get("pays", "").strip()
            if not p:
                continue
            emoji = p.split(" ")[0]
            if emoji not in emoji_to_name or len(p) > len(emoji_to_name[emoji]):
                emoji_to_name[emoji] = p

        modifie = False
        for v in self.voitures:
            p = v.get("pays", "").strip()
            if not p:
                v["pays"] = "🏁 Par défaut"
                modifie = True
            else:
                emoji = p.split(" ")[0]
                meilleur_nom = emoji_to_name.get(emoji, p)
                if v["pays"] != meilleur_nom:
                    v["pays"] = meilleur_nom
                    modifie = True

        if modifie:
            self.sauvegarder_json()

    def charger_json(self):
        if os.path.exists(FICHIER_JSON):
            try:
                with open(FICHIER_JSON, 'r', encoding='utf-8') as f:
                    self.voitures = json.load(f)

                max_id = max([v.get("id", 0) for v in self.voitures], default=0)
                besoin_sauvegarde = False
                for v in self.voitures:
                    if "id" not in v:
                        max_id += 1
                        v["id"] = max_id
                        besoin_sauvegarde = True
                if besoin_sauvegarde:
                    self.sauvegarder_json()

                self.nettoyer_pays_dynamique()

            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de lire {FICHIER_JSON} : {e}")
                self.voitures = []
        else:
            self.voitures = []

    def sauvegarder_json(self):
        try:
            with open(FICHIER_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.voitures, f, indent=4, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur de sauvegarde : {e}")

    def setup_ui(self):
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(20, 10))

        lbl_titre = ctk.CTkLabel(header_frame, text="Liste des Voitures", font=("Segoe UI", 20, "bold"))
        lbl_titre.pack(side="left")
        self.lbl_compteur = ctk.CTkLabel(header_frame, text="", font=("Segoe UI", 16), text_color="gray")
        self.lbl_compteur.pack(side="left", padx=10)

        btn_ajouter = ctk.CTkButton(header_frame, text="+ Ajouter", font=("Segoe UI", 14, "bold"), command=self.ouvrir_formulaire)
        btn_ajouter.pack(side="right")

        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(anchor="w", padx=20, pady=(0, 15))

        self.recherche_var = ctk.StringVar()
        self.recherche_var.trace_add("write", self.planifier_recherche)

        search_entry = ctk.CTkEntry(search_frame, placeholder_text="🔍 Rechercher...", textvariable=self.recherche_var, width=300)
        search_entry.pack(side="left")

        btn_clear = ctk.CTkButton(
            search_frame, text="✖", width=30, fg_color="transparent",
            text_color="gray", hover_color="#3B3B3B", command=self.effacer_recherche
        )
        btn_clear.pack(side="left", padx=(5, 0))

        table_header = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        table_header.pack(fill="x", padx=(20, 36), pady=(0, 5))

        table_header.grid_columnconfigure((0, 1), weight=2)
        table_header.grid_columnconfigure((2, 3, 4, 5), weight=1)

        ctk.CTkLabel(table_header, text="Modèle", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")

        self.btn_sort_marque = ctk.CTkButton(table_header, text="Marque", width=50, font=("Segoe UI", 12, "bold"), fg_color="transparent", hover_color="#3B3B3B", anchor="w", command=lambda: self.toggle_sort("marque"))
        self.btn_sort_marque.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        self.btn_sort_annee = ctk.CTkButton(table_header, text="Année", width=50, font=("Segoe UI", 12, "bold"), fg_color="transparent", hover_color="#3B3B3B", anchor="w", command=lambda: self.toggle_sort("annee"))
        self.btn_sort_annee.grid(row=0, column=2, padx=5, pady=5, sticky="w")

        self.btn_sort_pays = ctk.CTkButton(table_header, text="Pays", width=50, font=("Segoe UI", 12, "bold"), fg_color="transparent", hover_color="#3B3B3B", anchor="w", command=lambda: self.toggle_sort("pays"))
        self.btn_sort_pays.grid(row=0, column=3, padx=5, pady=5, sticky="w")

        self.btn_sort_rarete = ctk.CTkButton(table_header, text="Rareté", width=50, font=("Segoe UI", 12, "bold"), fg_color="transparent", hover_color="#3B3B3B", command=lambda: self.toggle_sort("rarete"))
        self.btn_sort_rarete.grid(row=0, column=4, padx=5, pady=5)

        ctk.CTkLabel(table_header, text="Actions", font=("Segoe UI", 12, "bold")).grid(row=0, column=5, padx=10, pady=5)

        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.scroll_frame.grid_columnconfigure((0, 1), weight=2)
        self.scroll_frame.grid_columnconfigure((2, 3, 4, 5), weight=1)

        self.pagination_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.pagination_frame.pack(fill="x", padx=20, pady=(0, 20))

        self.btn_prev = ctk.CTkButton(self.pagination_frame, text="◀ Précédent", width=120, command=self.page_precedente)
        self.btn_prev.pack(side="left")

        self.lbl_page = ctk.CTkLabel(self.pagination_frame, text="Page 1/1", font=("Segoe UI", 14, "bold"))
        self.lbl_page.pack(side="left", expand=True)

        self.btn_next = ctk.CTkButton(self.pagination_frame, text="Suivant ▶", width=120, command=self.page_suivante)
        self.btn_next.pack(side="right")

    def page_precedente(self):
        if self.page_actuelle > 1:
            self.page_actuelle -= 1
            self.afficher_liste()

    def page_suivante(self):
        self.page_actuelle += 1
        self.afficher_liste()

    def toggle_sort(self, col):
        current_order = 0

        for i, (c, o) in enumerate(self.active_sorts):
            if c == col:
                current_order = o
                self.active_sorts.pop(i)
                break

        if current_order == 0:
            next_order = 1
        elif current_order == 1:
            next_order = -1
        else:
            next_order = 0

        if next_order != 0:
            self.active_sorts.insert(0, (col, next_order))

        self.page_actuelle = 1
        self.update_sort_buttons()
        self.afficher_liste()

    def update_sort_buttons(self):
        self.btn_sort_marque.configure(text="Marque")
        self.btn_sort_annee.configure(text="Année")
        self.btn_sort_pays.configure(text="Pays")
        self.btn_sort_rarete.configure(text="Rareté")

        for index, (col, order) in enumerate(self.active_sorts):
            symbol = " ▲" if order == 1 else " ▼"
            priority = f" {index + 1}" if len(self.active_sorts) > 1 else ""
            text_append = priority + symbol

            if col == "marque":
                self.btn_sort_marque.configure(text="Marque" + text_append)
            elif col == "annee":
                self.btn_sort_annee.configure(text="Année" + text_append)
            elif col == "pays":
                self.btn_sort_pays.configure(text="Pays" + text_append)
            elif col == "rarete":
                self.btn_sort_rarete.configure(text="Rareté" + text_append)

    def effacer_recherche(self):
        self.recherche_var.set("")

    def planifier_recherche(self, *args):
        self.page_actuelle = 1
        if self.after_id:
            self.after_cancel(self.after_id)
        self.after_id = self.after(250, self.afficher_liste)

    def afficher_liste(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        self.scroll_frame._parent_canvas.yview_moveto(0)
        terme = self.recherche_var.get().lower()

        donnees_filtrees = []
        for index_original, voiture in enumerate(self.voitures):
            pays_texte = voiture.get("pays", "🏁 Par défaut")
            moteur_texte = voiture.get("moteur", "")
            puissance_texte = voiture.get("puissance", "")
            masse_texte = str(voiture.get("masse_kg", ""))

            if (terme in voiture["nom"].lower() or
                terme in voiture["marque"].lower() or
                terme in str(voiture.get("annee", "")).lower() or
                terme in pays_texte.lower() or
                terme in moteur_texte.lower() or
                terme in puissance_texte.lower() or
                terme in masse_texte.lower()):
                donnees_filtrees.append((index_original, voiture))

        for col, order in reversed(self.active_sorts):
            reverse = (order == -1)
            if col == "marque":
                donnees_filtrees.sort(key=lambda x: x[1].get("marque", "").lower(), reverse=reverse)
            elif col == "annee":
                def get_annee(item):
                    try:
                        return int(item[1].get("annee", 0))
                    except ValueError:
                        return 0
                donnees_filtrees.sort(key=get_annee, reverse=reverse)
            elif col == "pays":
                donnees_filtrees.sort(key=lambda x: x[1].get("pays", "").lower(), reverse=reverse)
            elif col == "rarete":
                donnees_filtrees.sort(key=lambda x: x[1].get("poids", 0), reverse=reverse)

        total_elements = len(donnees_filtrees)
        total_pages = max(1, math.ceil(total_elements / self.elements_par_page))

        if self.page_actuelle > total_pages:
            self.page_actuelle = total_pages

        debut = (self.page_actuelle - 1) * self.elements_par_page
        fin = debut + self.elements_par_page

        compteur = 0
        for index_original, voiture in donnees_filtrees[debut:fin]:
            self.creer_ligne(voiture, index_original, compteur)
            compteur += 1

        self.lbl_compteur.configure(text=f"({total_elements} résultats)")
        self.lbl_page.configure(text=f"Page {self.page_actuelle} / {total_pages}")

        self.btn_prev.configure(state="normal" if self.page_actuelle > 1 else "disabled")
        self.btn_next.configure(state="normal" if self.page_actuelle < total_pages else "disabled")

    def creer_ligne(self, voiture, index_original, index_affichage):
        ctk.CTkLabel(self.scroll_frame, text=voiture["nom"]).grid(row=index_affichage, column=0, padx=10, pady=8, sticky="w")
        ctk.CTkLabel(self.scroll_frame, text=voiture["marque"]).grid(row=index_affichage, column=1, padx=10, pady=8, sticky="w")
        annee = voiture.get("annee", "")
        ctk.CTkLabel(self.scroll_frame, text=str(annee)).grid(row=index_affichage, column=2, padx=10, pady=8, sticky="w")

        pays_affiche = voiture.get("pays", "🏁 Par défaut")
        ctk.CTkLabel(self.scroll_frame, text=pays_affiche).grid(row=index_affichage, column=3, padx=10, pady=8, sticky="w")

        rarete = voiture.get("rareté", "Commun ⚪")
        couleur = RARETES.get(rarete, {}).get("couleur", "gray")

        frame_pastille = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        frame_pastille.grid(row=index_affichage, column=4, pady=8)
        pastille = ctk.CTkFrame(frame_pastille, width=15, height=15, corner_radius=10, fg_color=couleur)
        pastille.pack()

        actions_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        actions_frame.grid(row=index_affichage, column=5, pady=8)

        btn_edit = ctk.CTkButton(actions_frame, text="✏️", width=30, fg_color="transparent", hover_color="#3B3B3B", command=lambda i=index_original: self.ouvrir_formulaire(i))
        btn_edit.pack(side="left", padx=5)

        btn_del = ctk.CTkButton(actions_frame, text="🗑️", width=30, fg_color="transparent", hover_color="#8B0000", command=lambda i=index_original: self.supprimer_voiture(i))
        btn_del.pack(side="left", padx=5)

        separateur = ctk.CTkFrame(self.scroll_frame, height=1, fg_color="#333333")
        separateur.grid(row=index_affichage+1, column=0, columnspan=6, sticky="ew")

    def ouvrir_formulaire(self, index=None):
        voiture_data = self.voitures[index] if index is not None else None
        FormulaireVoiture(self, voiture_data, index, self.sauvegarder_et_rafraichir)

    def sauvegarder_et_rafraichir(self, nouvelle_voiture, index):
        if index is not None:
            self.voitures[index] = nouvelle_voiture
        else:
            if "id" not in nouvelle_voiture:
                max_id = max([v.get("id", 0) for v in self.voitures], default=0)
                nouvelle_voiture["id"] = max_id + 1
            self.voitures.append(nouvelle_voiture)

        self.nettoyer_pays_dynamique()
        self.sauvegarder_json()
        self.afficher_liste()

    def supprimer_voiture(self, index):
        confirmation = messagebox.askyesno("Confirmer", f"Voulez-vous vraiment supprimer la {self.voitures[index]['marque']} {self.voitures[index]['nom']} ?")
        if confirmation:
            del self.voitures[index]
            self.sauvegarder_json()
            self.afficher_liste()


if __name__ == "__main__":
    app = App()
    app.mainloop()
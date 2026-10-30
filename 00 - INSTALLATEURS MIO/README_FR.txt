MIO — INSTALLATEURS WINDOWS FR / EN — 30 OCTOBRE 2026
====================================================

DÉJÀ FAIT
---------
- EXE autonome : cliquer, choisir un dossier vide, installer, puis « Close and start Mio ».
- Image et icône Mio dans l'installateur ; désinstallation graphique avec confirmation.
- Dernière source App clean : chat compact, copier-coller Windows, défilement automatique,
  noms des interlocuteurs et état du fournisseur ; détails d'erreur dans Logs.
- Modules locaux activables individuellement, choix du microphone et test avec vu-mètre.
  MicroBoost est facultatif ; Stop test ferme uniquement l'instance lancée par le test.
- GPT et Gemini : pages dédiées, activation, champ de clé masqué, test de connexion,
  choix du modèle, voix locale ou du fournisseur et recherche web si prise en charge.
- Bascule entre fournisseurs quand Mio est éveillée, Stop commun, Whisper bloqué
  pendant la réponse et après validation d'une première phrase ; commandes Vosk actives.
- Profils User/Child/Adult/Mio génériques, mémoire initiale vierge, aucun échantillon
  vocal ni clé API. Les modes Child/Adult et souvenirs locaux restent locaux.

RESTE À VALIDER
---------------
- Réinstallation réelle et conversation complète après installation : micro, voix,
  arrêt, connexion aux logiciels externes et API. Le contrôle du paquet ne remplace
  pas cet essai sur le PC cible.
- Fonctionnement de toute la chaîne sur un seul GPU et assistant de configuration simplifié.
- Traduction complète de l'interface : FR/EN désigne les commandes vocales Vosk.
  L'interface, les prompts et réponses automatiques génériques sont en anglais.

CE QUI EST INSTALLÉ
------------------
Mio, son interface, son moteur, ses modules internes (Whisper, Vosk, Piper, Melo,
mémoire vectorielle, reconnaissance vocale, VAD, annulation d'écho) et les modèles
internes disponibles dans le paquet. Un environnement Python commun est créé.
Python 3.11 peut être installé pour l'utilisateur s'il manque ; les dépendances
sont téléchargées. Internet et de l'espace libre sont donc nécessaires.

CE QUI N'EST PAS INSTALLÉ
------------------------
LM Studio et ses modèles LLM, Agent DVR, CodeProject.AI, Voice Changer/RVC et ses
modèles, MicroBoost, VB-CABLE, ANIMATE, les avatars, les pilotes et les comptes/API.
Ces programmes et leurs données restent séparés de Mio.

MODE D'EMPLOI
=============

1. PRÉPARER LE PC
Windows 64 bits, GPU NVIDIA et pilote compatible avec les dépendances CUDA.
Pour tout faire en local : un GPU 24 Go recommandé, ou deux GPU de 12 Go chacun.
La taille du LLM et du contexte détermine la mémoire nécessaire ; deux GPU de
12 Go ne forment pas automatiquement un seul espace de 24 Go.
Réglage initial : services sur GPU 0 et LLM sur GPU 1. Avec une seule carte,
dans Language model > Local model loading : mainGpu=0, disabledGpus=[].
Garder services_gpu="0" dans Startup. Cette configuration complète reste à tester.

2. INSTALLER
Choisir Mio Setup FR Test.exe pour les commandes françaises, EN pour l'anglais.
Un seul EXE suffit : aucun dossier payload à fournir à côté.
Choisir un dossier vide dédié ; l'installateur conserve les installations existantes.
Attendre la fin des téléchargements et vérifications. En cas d'erreur, consulter
le journal data\logs\installation.log dans le dossier choisi.

3. CONFIGURER
Ouvrir Mio puis Customize. Les connexions sont génériques, sans les chemins privés
de la machine de développement : adapter les chemins et identifiants avant Start.
Configurer LM Studio et le même identifiant de modèle dans la connexion et le
chargement local. Installer le LLM séparément.
Dans Mio — Modules, choisir les fonctions nécessaires. Par défaut : entrée micro,
voix locale et mémoire activées ; visages, identification vocale et RVC désactivés.
Une caméra n'est donc pas obligatoire dans la configuration initiale.
Dans Microphone, sélectionner l'entrée Windows par défaut ou le périphérique voulu,
cliquer Test, vérifier le niveau et Stop. MicroBoost et VB-CABLE peuvent aider à
augmenter le gain si nécessaire, après installation et configuration séparées.
Activer les visages ou RVC seulement après configuration de leurs logiciels externes.
Save enregistre ; Reload applique. Modifier les modules locaux relance la session.

4. UTILISER
Start démarre la session configurée. Réveiller Mio avec « réveille toi Mio » (FR)
ou « wake up Mio » (EN). Les commandes actives apparaissent dans Controls.
Choisir l'auteur avant Send pour le texte ; Ctrl+Entrée envoie, Entrée ajoute une ligne.
Stop coupe l'échange tout en gardant le fournisseur sélectionné.
Le sommeil exige de réveiller Mio locale avant toute nouvelle bascule.
Ne pas lancer FR et EN simultanément : leurs ports internes sont communs.

5. GPT / GEMINI FACULTATIFS
Dans Online — GPT ou Online — Gemini : choisir un identifiant de modèle réellement
accessible à son compte, enregistrer sa propre clé, puis tester la connexion et activer.
Le bouton vérifie l'accès API ; il ne valide pas une conversation vocale complète.
La voix locale est sélectionnée par défaut. La voix fournisseur demande aussi
son modèle et son nom de voix ; RVC reste applicable s'il est activé et configuré.
En FR, « T'es la GPT », « T'es la Gemini » et « T'es la Mio » changent de modèle
pendant l'éveil. En EN : « Are you there GPT / Gemini / Mio ».
Éditer ces mots dans Online — Commands. La reconnaissance dépend du vocabulaire Vosk.
Les clés ne sont pas incluses dans le paquet ; la clé saisie est stockée dans le
Gestionnaire d'identification Windows pour cette installation. Son champ est masqué.
Les fournisseurs reçoivent le message et leur historique temporaire ; les profils,
prompts familiaux et souvenirs locaux ne sont pas ajoutés automatiquement.
Les tarifs, quotas et modèles disponibles dépendent du compte et du fournisseur.

6. ARRÊTER ET DÉSINSTALLER
Fermer Mio avec la croix. Les services Windows externes peuvent demander une
confirmation administrateur à chaque démarrage/arrêt ; aucun accord permanent ajouté.
Lancer Uninstall Mio depuis le menu Démarrer, vérifier le dossier puis confirmer.
Les fichiers et données de cette installation sont supprimés, les programmes externes
restent en place. Une application encore ouverte doit être fermée avant suppression.
Si une clé API a été enregistrée, la retirer depuis sa page API avant désinstallation.

L'auteur confirme avoir mis les deux derniers EXE sur le dossier Google Drive
lié dans le README GitHub. Comparer les SHA-256 avec SHA256SUMS.txt pour identifier
cette version ; un téléchargement de contrôle complet reste à effectuer.

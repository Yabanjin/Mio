MIO — ÉTAT DU PROJET ET GUIDE D'INSTALLATION
==========================================

DÉJÀ FAIT
---------
- Deux installateurs EXE indépendants : commandes vocales françaises (FR)
  ou anglaises (EN), avec le modèle Vosk correspondant sélectionné.
- Installation graphique dans le dossier choisi, raccourcis et désinstallation
  graphique avec confirmation. L'entrée s'appelle « Uninstall Mio ».
- Interface de chat, saisie de texte, choix de l'auteur, copier-coller,
  défilement et pages de personnalisation par module.
- Modules internes et leurs modèles vocaux/de reconnaissance inclus.
  L'environnement Python et ses dépendances sont installés séparément.
- Paquets anonymisés : mémoire initiale vide, profils génériques User, Child
  et Adult, sans enregistrement vocal ni description personnelle préchargée.
- Prompts génériques modifiables et consigne d'écrire les valeurs en mots.
- Reload Mio relance le moteur et ses auxiliaires nécessaires, sans recharger
  tous les serveurs externes. Les fenêtres techniques sont réduites au démarrage.
- Connexions aux services externes et réglages matériels conservés pour le test.

RESTE À FAIRE / À VALIDER
-----------------------
- Valider ces deux EXE anonymisés après installation sur un autre PC,
  puis vérifier toute la chaîne : microphone, caméra, reconnaissance et réponse.
- Ajouter un choix guidé « un GPU / deux GPU » et valider le fonctionnement
  simultané sur une seule carte. Les réglages actuels ciblent deux GPU.
- Finaliser une traduction française complète : FR désigne les commandes
  vocales ; l'interface et les textes génériques sont actuellement en anglais.
- Ajouter la saisie et la gestion des clés d'API, l'authentification et les
  adaptations nécessaires aux différents fournisseurs d'API hébergées.
- Simplifier l'assistant de première configuration. Les programmes externes,
  les périphériques et l'enregistrement des personnes restent à configurer.


MODE D'EMPLOI SIMPLE
===================

1. PRÉPARER LE PC
----------------
Cette version vise Windows 64 bits avec un GPU NVIDIA et un pilote compatible
avec les bibliothèques CUDA utilisées par Mio. Elle ne propose pas de mode
CPU ou AMD prêt à l'emploi.

Configurations recommandées comme objectifs pour tout faire en local :
- Un GPU avec 24 Go de VRAM : modèle de langage et services sur la même carte.
- Deux GPU avec 12 Go de VRAM chacun : services Mio sur une carte et modèle
  de langage sur l'autre.

Ces indications ne garantissent pas qu'un modèle de langage quelconque tiendra
en mémoire. Sa taille, sa quantification, le contexte et les autres services
comptent aussi. Deux cartes de 12 Go ne deviennent pas automatiquement une
carte de 24 Go. Leur mémoire est distincte dans la configuration actuelle.

Prévoir Internet pour les dépendances Python, un microphone, une sortie audio
et une caméra pour la chaîne actuelle avec autorisation faciale. Garder assez
d'espace disque pour Mio, son environnement et les modèles externes choisis.

2. CHOISIR ET INSTALLER MIO
--------------------------
- Commandes françaises : lancer « Mio Setup FR Test.exe ».
- Commandes anglaises : lancer « Mio Setup EN Test.exe ».

Chaque EXE contient son paquet : aucun dossier payload n'est nécessaire à côté.
Cliquer Browse, choisir un dossier vide, par exemple un nouveau dossier Mio,
puis cliquer Install Mio. Le dossier proposé par défaut est
%LOCALAPPDATA%\Mio. Le raccourci Bureau est facultatif.

Attendre la fin de l'extraction et de l'installation des dépendances. Python
3.11 64 bits avec Tkinter est recherché et son installation est tentée s'il
manque. En cas d'échec, installer Python 3.11 avec Tkinter et relancer.
À la fin, cliquer « Close and start Mio » pour ouvrir le chat.

3. CONNECTER LES PROGRAMMES EXTERNES
-----------------------------------
L'EXE installe Mio et ses composants internes, pas les applications suivantes :
- LM Studio et le modèle de langage choisi ;
- Agent DVR et CodeProject.AI pour la caméra et les visages ;
- VoiceChanger/RVC et son modèle de conversion vocale ;
- MicroBoost, Insta360 Link Controller et les pilotes/périphériques audio.

La chaîne complète actuelle attend les services externes configurés. Les chemins
conservés dans ces versions de test ne sont pas une configuration universelle.

Ouvrir Customize :
- Language model : renseigner les adresses du serveur et le modèle disponible.
  Utiliser le même identifiant dans « Connection and model » et
  « Local model loading » pour le chargement local actuel.
- Agent DVR camera, CodeProject.AI faces et Voice changer : vérifier les URL
  et les paramètres de lancement de chaque programme.
- Startup > Interface runtime : vérifier les exécutables, dossiers de travail
  et ressources. Désactiver les utilitaires de démarrage inutilisés.
- Mio — Main settings : vérifier les entrées/sorties audio. Le routage par
  câble audio virtuel préconfiguré doit correspondre aux périphériques du PC.

Enregistrer chaque page avec Save. Un avatar VRM est facultatif et nécessite
son propre logiciel : aucun avatar ni logiciel d'avatar n'est installé ici.

4. VÉRIFIER L'AFFECTATION DES GPU
-------------------------------
Les valeurs actuelles utilisent GPU 0 pour les services Mio et GPU 1 pour
le modèle de langage. Vérifier que ces indices correspondent aux bonnes cartes.

Pour essayer un seul GPU de 24 Go, dans Language model > Local model loading,
mettre mainGpu à 0 et disabledGpus à [] (liste vide). Garder services_gpu à "0"
dans Startup > Interface runtime. Choisir un modèle qui laisse assez de VRAM
aux services vocaux. Ce montage reste à valider avec tous les services actifs.

5. PERSONNALISER ET DÉMARRER
---------------------------
- Mio — Texts : modifier Prompt / Common, Normal, Adult ou Child, les réponses
  automatiques et les textes de langue. Common s'applique aux trois modes.
- Mio — Timings : régler les délais. Les autres pages regroupent les modules.
- SpeechBrain recognition : les profils n'ont aucun échantillon vocal.
  Pour reconnaître une voix, ajouter ses références et configurer leurs chemins.
  Les visages doivent être enregistrés dans le service externe correspondant.

Cliquer Save, revenir au chat puis Start. Accepter la demande administrateur
Windows pour Agent DVR lorsque son démarrage ou son arrêt est demandé.
Cette autorisation n'est pas enregistrée comme permission permanente.

Commandes de réveil : « réveille-toi Mio » / « yo Mio » en FR ;
« hey Mio » / « wake up Mio » en EN. « stop » interrompt une réponse.
Les commandes configurées sont rappelées dans Controls.

Pour écrire, choisir User, Child ou Adult, saisir le message puis cliquer Send
ou utiliser Ctrl+Entrée. Entrée seule ajoute une ligne. Le choix de l'auteur
ne contourne pas l'autorisation faciale et n'identifie pas une voix.

Après une modification de prompt ou de délai, utiliser Reload Mio dans une
page Mio. Un réglage propre à un serveur externe demande son propre redémarrage.

6. API EXTERNES : CE QUI EST POSSIBLE AUJOURD'HUI
----------------------------------------------
Certaines adresses de service sont modifiables. Un serveur de langage distant
peut être raccordé s'il expose les formats de requête, de réponse en flux et
de contrôle de disponibilité attendus, sans authentification supplémentaire.
Il faut alors désactiver le chargement local automatique du LLM et adapter
les paramètres de connexion et de lancement. Ce n'est pas un branchement
automatique à n'importe quelle API.

La gestion des clés et des fournisseurs hébergés reste à développer. De plus,
ces EXE imposent encore les adresses locales des services Whisper et TTS internes.
Changer une URL ne remplace donc pas tous les modules locaux par des API distantes.

7. ARRÊTER, DÉPANNER OU DÉSINSTALLER
----------------------------------
Fermer Mio avec la croix. Ne pas lancer les éditions FR et EN simultanément :
elles utilisent les mêmes ports. Logs affiche les journaux ; leurs fichiers
se trouvent aussi dans data\logs du dossier installé.

En cas d'échec d'installation, consulter data\logs\installation.log.
Si le dossier contient déjà une installation, en choisir un autre vide ou
désinstaller d'abord cette installation.

Pour supprimer Mio, fermer l'application, lancer « Uninstall Mio » depuis le
menu Démarrer et confirmer. Les données locales de cette installation sont
supprimées. Les programmes externes, leurs modèles et leurs données sont conservés.

La mémoire est vide au départ ; Mio peut ensuite conserver de nouveaux échanges.
L'anonymisation concerne le paquet. Les services externes connectés conservent
leurs propres données et peuvent renvoyer leurs identités enregistrées.

# Contexte — Brique 2 (work_manager_automation)

Document de reprise pour un autre agent/session : cette conversation est
devenue très longue, ce fichier résume tout ce qui a été construit, décidé,
testé et découvert, plus le point ouvert exact où le travail s'est arrêté.
Lis-le en entier avant de continuer - beaucoup de décisions ont une raison
non évidente (bugs trouvés en cours de route, tests qui ont infirmé une
hypothèse initiale).

Le briefing d'origine de ce projet (vision globale, Brique 1 vs Brique 2,
pièges déjà rencontrés côté `work_manager`) est dans le premier message de
la conversation qui a produit ce repo - non dupliqué ici, mais toujours
valide pour le contexte général.

---

## 1. Ce qui est construit et validé

### 1.1 Intégration Craft (tracker de candidatures)

- `craft/client.py` : wrapper HTTP générique (`httpx`) sur l'API
  multi-documents de Craft. Rate limits confirmés larges (50 req/10s IP,
  100 req/60s espace) - jamais un problème en pratique.
- `craft/tracker.py` : logique métier. **Modèle de données confirmé** (pas
  supposé - vérifié contre les vraies données du tracker "Entreprises
  auquelles je peux Postuler", collection `6785E207-...`, document
  `8C854F99-...`) :
  - Un item de collection = une **entreprise**, pas une offre.
  - Les offres vivent comme blocs imbriqués dans le `content` de l'item :
    un bloc `richUrl` (le lien de l'offre) suivi de deux blocs checklist
    "Commencé la candidature ?" et "Postulé ?" - **deux checkboxes par
    offre, pas une**. L'état coché/décoché est un champ structuré
    `taskInfo.state` (`"todo"`/`"done"`), pas le `[ ]`/`[x]` du markdown
    (qui n'est qu'un rendu).
  - Un bloc `collection` range ses items sous une clé `items`, pas
    `content` comme tous les autres types de blocs - piège trouvé en
    prod (`fetch_new_offers` retournait silencieusement une liste vide
    tant que ce n'était pas su).
  - `fetch_new_offers()` ne retient que les offres où les **deux**
    checkboxes sont encore "todo" (offre jamais touchée) - une offre avec
    "Commencé" coché mais pas "Postulé" a probablement été traitée à la
    main, hors automatisation, et n'est pas reprise pour éviter les
    doublons.
  - `mark_started()`/`mark_applied()` : `PUT /blocks` en changeant le
    markdown du bloc task de `[ ]` à `[x]` (seul `markdown` est documenté
    comme modifiable côté API, pas `taskInfo` directement - Craft
    re-dérive l'état à partir du texte). **Confirmé fonctionnel en
    conditions réelles** (testé manuellement via Bruno, puis via le
    pipeline complet sur une vraie offre Ledger - la case s'est bien
    cochée, vérifié par une lecture API directe après coup, pas juste en
    croyant le 200 OK).
- Collection Bruno (`bruno/craft-api/`, requêtes 01-09) pour explorer
  l'API à la main si besoin - 09 est le test d'écriture, avec procédure de
  reversion.

### 1.2 Génération de la lettre de motivation (LLM local)

- `llm.py` : un seul appel HTTP scoped à LM Studio (API OpenAI-compatible),
  non-agentique (pas d'accès outils, pas de boucle multi-tours) - un
  brouillon que l'humain relit toujours avant export.
- **Modèle retenu : `qwen/qwen3.6-35b-a3b`** (MoE, 35B total / ~3B actifs),
  `reasoning_effort` par défaut (ni forcé à `"none"` ni à `"xhigh"`).
  Choisi après comparatif contre Qwen3.8-27B (dense) - voir
  section 3 pour le détail et pourquoi ce choix a été retourné en cours de
  route.
- Prompt en deux temps (sélection+justification, puis lettre), avec
  garde-fous ajoutés après des échecs concrets observés en test (voir
  section 3) : pas de copie verbatim ni de paraphrase par simple synonymes
  de la motivation fournie, structure argument-puis-fait obligatoire,
  aucune invention de fait non présent dans le corpus, pas de conclusion
  générique passe-partout. La lettre finale est extraite via des marqueurs
  `<<<LETTRE_DEBUT>>>`/`<<<LETTRE_FIN>>>` (fiable, testé en prod).
- **Tout est configurable** (modèle, prompt, température, reasoning_effort,
  timeout) via `Settings`/env - un audit a trouvé que ça ne l'était pas au
  départ (le prompt était une constante Python en dur), corrigé avant de
  construire dessus. Le prompt vit dans `prompts/lm_system_prompt.md`, pas
  dans le code.
- **Pas de RAG** : le corpus (`allExperiences.yaml`) tient entier dans le
  prompt (~5200 tokens) - `search_experiences` a été délibérément reporté,
  voir section 4.
- **Validé deux fois en conditions réelles**, sur deux offres de nature
  très différente (preuve que ça généralise, pas du overfitting sur un
  seul cas) :
  - Capgemini (web/cloud/Agile) → sélection GCP + Mob'INSA.
  - Ledger (hardware wallet, sécurité, bas niveau) → sélection **différente**
    et pertinente : mylibc (gestion mémoire) + remoteDisplay (C++, kernel,
    Thunderbolt) - le modèle a correctement changé de sélection selon le
    contexte plutôt que de recycler les mêmes expériences. Reprend même du
    vocabulaire propre à l'entreprise ("self-custody" pour Ledger).

### 1.3 Serveur MCP `wm_automation`

- `mcp_server.py`, lancé via le script console `wm-automation-mcp`
  (`.venv/bin/wm-automation-mcp` après `pip install -e .` - un host MCP
  externe comme Bionic n'a pas besoin de partager ce venv).
- **Exactement 3 tools exposés**, toolset volontairement restreint :
  `list_untouched_offers` (read-only), `start_application` (crée la
  candidature + génère la LM, jamais l'export), `finalize_application`
  (export + écriture Craft). **Jamais exposés** : administration de preset
  (`add_preset`/`remove_preset` - ce dernier irréversible), édition brute
  de blocs Craft. Ce choix de toolset a été débattu longuement (voir
  section 5) - la conclusion est que le risque réel n'est pas l'export
  (qui ne fait que produire un fichier local, la vraie candidature reste
  un geste humain manuel sur le site de l'entreprise) mais (a) la
  possibilité d'un appel irréversible non voulu et (b) la pollution du
  vrai système de suivi (Craft) si l'agent traite des offres en masse sans
  qu'on le lui demande.
- `start_application` retombe sur `default_automation_preset` ("automation")
  si l'appelant n'en précise pas - le preset "default" de work_manager
  utilise un `.pages` que ce pipeline corromprait en écrivant du texte
  brut dedans.
- **Validé en conditions réelles**, pas juste testé unitairement : serveur
  lancé comme un vrai host MCP le ferait (sous-processus + `ClientSession`
  réel sur stdio), `start_application` + `finalize_application` exécutés
  pour de vrai sur l'offre Ledger (voir 1.1/1.2 pour le résultat).

---

## 2. Bugs réels trouvés et corrigés (tous découverts en testant en conditions
réelles, pas en relisant le code)

1. **`WorkManagerClient._call` utilisait `result.isError`** au lieu de
   `result.is_error` (le SDK `mcp` expose l'attribut en snake_case) -
   provoquait une `AttributeError` à chaque appel, qui se manifestait
   comme un blocage nécessitant Ctrl+C plutôt qu'une erreur claire.
2. **Toute exception non interceptée à l'intérieur d'un `async with
   WorkManagerClient(...)` bloquait indéfiniment** à la fermeture - pas
   spécifique au bug ci-dessus, reproduit délibérément avec une exception
   arbitraire. Cause : `ClientSession.__aexit__` du SDK `mcp` semble
   bloquer quand on lui passe une exception qui ne vient pas de son propre
   groupe de tâches ; un `asyncio.timeout()` autour n'a pas suffi (la
   task-group interne semble résister à l'annulation externe). Corrigé en
   appelant les deux context managers internes avec `(None, None, None)`
   plutôt qu'en leur transmettant l'exception réelle - celle-ci continue
   de se propager normalement après, sans déclencher ce chemin.
3. **`fetch_new_offers` retournait toujours une liste vide** silencieusement
   contre les vraies données - `_iter_collection_items` ne descendait que
   dans `content`, alors qu'un bloc `type: "collection"` range ses lignes
   sous `items`. Trouvé en comparant un `poll` réel (0 résultat) contre une
   offre dont on avait vérifié manuellement qu'elle était "todo"/"todo".
4. **`pipeline.py` utilisait `print()`** pour les avertissements
   d'écriture Craft - aurait corrompu le canal stdio du serveur MCP
   (protocole JSON-RPC), exactement le piège déjà documenté côté
   `work_manager_mcp` en Brique 1. Trouvé en construisant le serveur MCP,
   avant que ça casse en usage réel. Corrigé en passant sur `logging`
   (stderr).
5. **`list_untouched_offers` (valeur de retour `list[dict]`) était éclatée
   par le SDK `mcp` v2 en un bloc `content` par élément** (28 offres → 28
   blocs) plutôt qu'un seul bloc JSON. N'importe quel client qui ne lit
   que `content[0].text` (pattern courant, y compris `WorkManagerClient`
   dans ce repo) ne verrait que la première offre, silencieusement. Trouvé
   en inspectant la vraie forme de la réponse, pas en supposant. Corrigé
   en renvoyant `{"offers": [...]}` plutôt qu'une liste nue.
6. **Le deuxième tour de `generate_application_content` (génération des
   sections CV) pouvait tomber dans une boucle de raisonnement qui ne
   converge jamais** - observé sur une vraie offre Craft (Framatome, peu
   de contexte car Craft ne stocke qu'un blurb court) : plus de 14 minutes
   sans sortie, jusqu'au timeout HTTP de 1200s. Le premier tour (la
   lettre) n'a jamais montré ce problème avec les mêmes réglages -
   probablement parce qu'empiler plusieurs contraintes strictes (pool
   `jobs` figé, schéma YAML exact, limite d'une page) sur une conversation
   déjà longue donne au modèle beaucoup plus à revérifier en boucle que la
   lettre, plus libre. Corrigé en ajoutant `llm_cv_max_tokens` (8000 par
   défaut, seulement sur ce deuxième tour - le premier reste sans limite
   car il termine fiablement seul) et en détectant `finish_reason ==
   "length"` pour lever une `LLMError` claire immédiatement plutôt que
   d'attendre le timeout complet.
7. **Malgré la consigne explicite de recopier `company`/`product`/`tags`/
   `from`/`to`/`location` tels quels, le LLM a modifié un lien** dans le
   même test réel (Framatome) : `company.link` de l'entrée "Participation
   à un exercice de gestion de crise" est passé de
   `insa-centrevaldeloire.fr` (la vraie valeur du corpus) à `insa-cvl.fr`
   (un domaine plausible mais faux, probablement mélangé avec le lien
   d'une autre entrée du corpus qui utilise ce sous-domaine). L'autre
   expérience générée dans le même appel avait son lien parfaitement
   recopié - donc pas systématique, pas quelque chose qu'une reformulation
   de prompt peut garantir de corriger. Corrigé structurellement plutôt
   que par le prompt : `cv.apply_cv_sections`/`_reconcile_entries`
   recale désormais chaque entrée générée sur son entrée d'origine dans le
   corpus (via correspondance exacte sur `position`, le seul champ
   fidèlement reproduit dans les tests) et écrase tous les champs sauf
   `description` avec les valeurs authentiques - le LLM n'est plus jamais
   la source de vérité pour ces champs, seulement pour la sélection et la
   reformulation. Une entrée sans correspondance dans le corpus est
   supprimée plutôt que gardée avec des données non vérifiées (avec un
   `logger.warning`).
8. **Un `template.yml` de preset (`~/workManager/presets/automation/
   template.yml`, hors du repo) rend `output_name` et `export_name`
   identiques pour le template `lm` casse silencieusement l'export** - la
   commande `cp ${self.path}/${self.output_name} ${self.path}/
   ${self.export_name}` échoue si les deux valent le même nom
   (`cp: ... are identical (not copied)`). Découvert en plein test de
   bout en bout : `export_name` était passé de `'LM_${wname}.txt'` à
   `'LM_${wname}_2025.txt'` (édition manuelle involontaire pendant la
   session), cassant `finalize_application` pour n'importe quelle
   candidature utilisant le preset `automation`, indépendamment de tout
   changement côté `wm_automation`. Pas un bug de ce repo, mais à surveiller
   si ce fichier est retouché à la main.
9. **`load_settings()` perdait silencieusement `CRAFT_API_TOKEN` (et tout
   le reste du `.env`) dès que le process était lancé depuis un autre
   répertoire de travail** - `load_dotenv()` sans argument cherche le
   `.env` à partir du cwd, or un host MCP externe (Bionic) lance le
   binaire depuis le sien, pas depuis `work_manager_automation/`. Trouvé
   en le testant explicitement depuis `/tmp` avant de brancher Bionic pour
   de vrai (section 1.3 avait déjà anticipé "un host MCP externe... n'a
   pas besoin de partager ce venv", mais sans tester le cas du `.env`).
   Aucune erreur levée - juste un `craft_api_token` vide, qui aurait fait
   échouer silencieusement `list_untouched_offers` une fois branché.
   Corrigé en pointant `load_dotenv()` explicitement vers le `.env` du
   projet (calculé depuis `__file__`), indépendamment du cwd de lancement.
10. **`start_application` échouait immédiatement (avant même Craft/le LLM)
    dès que le process du serveur MCP redémarrait entre deux appels de
    l'agent** - `offer_index` référençait `_offer_cache`, une variable
    globale en mémoire remplie uniquement par un appel précédent à
    `list_untouched_offers` **dans ce même process**. Un redémarrage du
    serveur (ce qui arrive par exemple en changeant un réglage du serveur
    MCP côté Bionic, comme le timeout - voir plus haut) vide ce cache ;
    `offer_index=0` sur un cache vide lève alors immédiatement
    `ValueError("offer_index 0 out of range...")`. Aggravant : le SDK
    `mcp` écrase systématiquement l'exception réelle (pourtant parfaitement
    claire) par un générique `UnexpectedToolError("Error executing tool
    start_application")` avant de la renvoyer au client - Bionic n'a donc
    jamais vu le vrai message, juste ce texte générique, quelle que soit la
    cause réelle. Reproduit à l'identique (même texte d'erreur) en
    reconnectant un process serveur neuf sans appeler
    `list_untouched_offers` avant `start_application`. Corrigé en rendant
    `start_application` sans état : il prend maintenant `offer_url` (déjà
    renvoyé par `list_untouched_offers`) plutôt qu'un `offer_index`, et
    re-fetch Craft à chaque appel pour retrouver l'offre par son url - plus
    aucun cache partagé entre les deux tools, donc plus aucune dépendance à
    l'ordre/au cycle de vie des appels.

Leçon générale qui s'est confirmée plusieurs fois : **toujours vérifier
directement (lire la vraie donnée, inspecter la vraie structure) avant de
conclure**, y compris sur ses propres suppositions sur le comportement
d'un SDK - plusieurs de ces bugs auraient été manqués par une simple
relecture de code.

---

## 3. Comparatif de modèles LLM (pourquoi Qwen3.6-35B-A3B, pas Qwen3.8-27B)

Testé manuellement via LM Studio (chat Bionic, puis API brute pour
confirmer que la qualité ne dépend pas du harness) sur l'offre Capgemini +
le vrai corpus, avec un prompt en deux temps.

| Modèle | `reasoning_effort` | Temps | Constat |
|---|---|---|---|
| Qwen3.6-35B-A3B | v1 du prompt (sans garde-fou anti-copie) | - | Catastrophe : recopie la motivation mot pour mot malgré une consigne explicite de ne pas le faire |
| Qwen3.8-27B (dense) | medium (Bionic) | ~10 min | Bonne qualité, 1 incohérence logique mineure |
| Qwen3.8-27B (dense) | medium (API) | 857s | Correcte mais clôture répétitive + une phrase d'auto-défense dans la lettre |
| Qwen3.8-27B (dense) | low | 462s | Très bonne - aucune hallucination, honnêteté précise sur les limites du corpus |
| Qwen3.8-27B (dense) | none | 124s | Rapide mais hallucine un fait (ville d'échange incorrecte) + recopie le jargon marketing de l'offre |
| Qwen3.6-35B-A3B | défaut (v2/v3 du prompt) | 80s / 87s / 53s (3 essais) | Qualité comparable ou meilleure que Qwen3.8-27B, 6-10x plus rapide (MoE) |

**Conclusion** : le problème initial de Qwen3.6-35B-A3B était le prompt
(v1), pas le modèle. Sur 3 essais du prompt corrigé, 1 avait quand même
une ouverture trop proche de la motivation (synonymes de surface, pas une
vraie reformulation) - le prompt final interdit maintenant ça
explicitement, revérifié depuis sur Capgemini et Ledger (reformulations
authentiques les deux fois).

Comparé à `artificialanalysis.ai` (Intelligence Index) : les modèles open
weights vraiment "state of the art" (GLM-5.3, Kimi K3, DeepSeek...) sont
tous à plusieurs centaines de milliards de paramètres totaux - inutilisables
sur ce Mac (48GB unifié) quel que soit le nombre de paramètres actifs en
MoE, puisque c'est le total qui doit tenir en mémoire. Qwen3.6-35B-A3B est
le meilleur choix qui rentre réellement.

**Pourquoi Sonnet 5 (Claude) semble proche en score mais rend un résultat
très différent** : l'Intelligence Index (v4.3) agrège 10 évaluations
(code, agentique, raisonnement scientifique, connaissance...) - aucune
n'est de la rédaction ni du respect fin de consignes négatives. Deux
modèles à quelques points d'écart sur cet indice peuvent avoir des profils
de compétence très différents sur ce que ce projet a besoin.

---

## 4. Décisions d'architecture actées, avec le raisonnement

- **RAG (`search_experiences`) reporté, pas abandonné.** Aucune valeur
  réelle tant que le corpus tient dans un seul prompt. Mesuré au 20/09/2026
  après le premier passage d'enrichissement (voir section 8) via l'API
  réelle de LM Studio (pas une estimation) : corpus seul = 14 441 tokens
  (contre ~5200 avant, ×2,8 - l'enrichissement a bien fait grossir le
  fichier comme prévu), pour un contexte chargé de 183 296 tokens (modèle
  qwen3.6-35b-a3b) - soit ~8%, encore loin de toute limite même avec les
  deux tours de conversation (lettre + CV) et le raisonnement du modèle.
  Toujours pas nécessaire, mais à re-mesurer si le corpus retriple. Sa
  vraie justification viendra soit d'une croissance continue du corpus,
  soit de l'étape 5 (comme *tool* que l'agent interactif peut appeler pendant une
  conversation, pas comme optimisation du prompt actuel).
- **La génération LM reste hors chat/agent.** `start_application` fait un
  appel HTTP direct, un seul coup, asynchrone - pas de conversation en
  direct à cette étape précise (10-15 min avec un modèle dense, 1-1,5 min
  avec Qwen3.6-A3B - même le cas rapide n'est pas confortable en tour de
  chat interactif répété).
- **Toolset MCP restreint pour l'agent interactif** (`list_untouched_offers`
  / `start_application` / `finalize_application` seulement). Débat
  résolu : l'export en lui-même n'est pas le vrai risque (aucune action
  externe irréversible - la candidature réelle reste un geste humain
  manuel sur le site de l'entreprise) ; les deux risques réels sont (a)
  `remove_preset` est explicitement irréversible et n'a aucune raison
  d'être appelé en routine, (b) un agent qui traite des offres en masse
  sans qu'on le lui demande fausserait le vrai suivi Craft (checkboxes
  cochées pour des offres jamais réellement décidées).
- **CV : sélection puis réécriture** des expériences pertinentes (pas
  juste sélection), dans la **même session conversationnelle** que la LM
  - pas deux flux séparés.
- **`poll` est un tool agent-appelable**, pas qu'une commande humaine :
  l'agent doit savoir lui-même ce qu'il reste à traiter quand l'utilisateur
  dit "je veux travailler sur mes candidatures".
- **Interface : LM Studio Bionic d'abord**, plutôt qu'une UI maison -
  Bionic supporte MCP + Skills nativement, moins cher à essayer qu'à
  construire. Une UI maison ne serait envisagée que si Bionic s'avère
  limitant à l'usage réel.
- **Craft "work on this" button** : confirmé faisable (un lien markdown à
  schéma personnalisé type `wmauto://...` est bien rendu cliquable par
  Craft), mais explicitement une couche de confort à faire *après* le
  reste, pas un prérequis.

---

## 5. Génération du CV (étape 4) - résolue

**Le "stale template" décrit dans une version antérieure de ce document
était une fausse piste.** Ce n'est pas un bug ni des données périmées à
synchroniser : c'est une décision produit de l'utilisateur. `contacts`,
`skills`, `tools`, `education`, `objective`, `image` dans
`configuration.yaml` changent très rarement et restent **édités à la main
par l'utilisateur, jamais par le pipeline**. Seuls trois champs sont du
ressort de l'automatisation, par ordre de priorité : `jobs` et
`personal_experience` (obligatoire), `tagline` (seulement si le domaine de
l'offre le justifie clairement - sinon laissé identique). L'idée
initialement envisagée (copier tout `allExperiences.yaml.personal_experience`
tel quel dans `configuration.yaml`) a été explicitement écartée : le but
n'est pas une synchronisation but une **sélection + réécriture** adaptée à
chaque offre, exactement ce que fait déjà la lettre de motivation (voir
section 1.2).

### Architecture retenue

- **Une seule conversation LLM en deux tours**, pas deux appels
  indépendants - conforme à la décision déjà actée en section 4 ("même
  session conversationnelle que la LM, pas deux flux séparés") :
  1. Premier tour : inchangé, c'est l'appel lettre déjà validé (section
     1.2/3) avec `lm_system_prompt.md`.
  2. Deuxième tour : la réponse du premier tour est réinjectée comme
     message `assistant`, suivie d'un nouveau message `user` construit à
     partir de `prompts/cv_followup_prompt.md` (nouveau fichier, même
     logique que le prompt système de la lettre : au dehors du code
     Python pour rester éditable sans toucher au code). Ce message
     embarque le pool de `jobs` (voir mise à jour du 26/09/2026 ci-dessous)
     et le `tagline` actuel. Le modèle répond en YAML entre les marqueurs
     `<<<CV_DEBUT>>>`/`<<<CV_FIN>>>` (même pattern fiable que
     `<<<LETTRE_DEBUT>>>`/`<<<LETTRE_FIN>>>`), avec exactement les clés
     `tagline`/`jobs`/`personal_experience`.

  **Mise à jour du 26/09/2026** : `jobs` fonctionne maintenant exactement
  comme `personal_experience` - un pool maître vit dans
  `allExperiences.yaml` (nouvelle clé `jobs`, même schéma que
  `personal_experience`), et le LLM **sélectionne** parmi ce pool plutôt
  que de simplement garder/reformuler/omettre une entrée unique. Ce choix
  initial (`jobs` = une seule entrée figée, le stage INSA) supposait qu'il
  n'existerait jamais qu'un seul vrai job - devenu faux dès qu'un
  deuxième vrai job (un stage) est arrivé. `pipeline.py` lit désormais
  `corpus.get("jobs", [])` (au lieu de `configuration.yaml.jobs`) comme
  pool à passer au LLM et à la réconciliation dans `cv.py`
  (`apply_cv_sections`/`_reconcile_entries`, inchangés sinon - la
  protection contre les champs altérés par le LLM, section 2 bug 7,
  s'applique donc aussi à `jobs` maintenant). Contrainte de page ajustée
  en conséquence : le prompt limite désormais `jobs` + `personal_experience`
  **combinés** à 3 entrées maximum, plutôt que 3 pour `personal_experience`
  seul (`jobs` pouvant désormais en apporter plus d'une). `configuration.yaml`
  garde ses deux clés séparées (rendues sous deux titres différents sur le
  CV) - seule la source change. Point de migration pour l'utilisateur :
  toute entrée déjà présente uniquement dans `configuration.yaml.jobs`
  (ex. le stage INSA) doit être recopiée dans `allExperiences.yaml.jobs`
  pour rester sélectionnable, sinon elle disparaît du pool.
  - Faire ça en deux tours d'une même conversation plutôt qu'un appel
    séparé garantit que la sélection d'expériences pour le CV reste
    cohérente avec celle déjà faite pour la lettre (confirmé en test :
    les mêmes expériences ressortent des deux côtés) au lieu de
    redemander au modèle de refaire ce raisonnement de zéro.
  - `wm_automation.llm.generate_application_content()` fait les deux
    tours et retourne `GeneratedApplication(letter, cv_sections)`.
- **`configuration.yaml` est déjà copié par candidature**, pas partagé
  depuis le preset - confirmé en inspectant les dossiers
  d'applications réels (`~/workManager/applications/CA-.../configuration.yaml`
  existe en copie indépendante à côté de `ATSCV.typ`/`cvPic2025.png`,
  marqués `is_asset: true` dans `template.yml`, donc copiés mais jamais
  passés à `export_command`). Écrire dedans après `create_application` ne
  touche donc jamais le fichier source du preset - même garantie que pour
  `lm_template_key`, juste avec une clé de template différente
  (`cv_config_template_key = "asset1"`, résolue via le même
  `resolve_template_path` que pour la lettre).
- `wm_automation.cv.apply_cv_sections(config_path, cv_sections)` réécrit
  uniquement `tagline`/`jobs`/`personal_experience` dans la copie de
  `configuration.yaml` de la candidature, préserve tout le reste tel quel
  (testé : contacts/education/skills/tools/languages identiques après
  passage). `ATSCV.typ` n'est **jamais** touché par le LLM (toujours
  piloté uniquement par les données, comme prévu avant cette étape).
- **Vérification "une page" en post-traitement, pas en contrainte de
  génération** : rien ne mesure la mise en page pendant que le LLM
  écrit - impossible à faire fiablement sans compiler. `wm_automation.cv.count_pdf_pages()`
  (via `pypdf`) est donc appelé après le vrai export Typst, dans
  `finalize_application`. Si le nombre de pages dépasse `cv_max_pages`
  (1 par défaut, configurable via `WM_CV_MAX_PAGES`), le résultat
  retourné contient `cv_page_warning` (et toujours `cv_page_count`) -
  n'importe qui lit ce résultat (CLI, agent MCP) peut le relayer, mais ça
  ne bloque jamais l'export. Le prompt de suivi reste volontairement
  conservateur de son côté (3 entrées `personal_experience` maximum, 3
  points de description maximum par entrée, ~20 mots par point) pour que
  ce cas reste rare en pratique.

### Validation réelle effectuée

1. **Test isolé** (aucun effet de bord, lecture seule de
   `allExperiences.yaml`/`configuration.yaml`, deux vrais appels LLM) sur
   une fausse offre "stage sécurité offensive" : sélection cohérente et
   sans invention (CTF Inter-INSA, remoteDisplay, mylibc - jamais les
   expériences web/mobile hors-sujet), `jobs` correctement vidé ou laissé
   identique selon le run (jamais inventé), `tagline` laissé identique
   (déjà cohérent avec le domaine sécurité).
2. **Test de bout en bout réel** via `wm_automation.cli prepare` +
   `finalize` (vraie candidature test `ZZTestSecu`, nettoyée après coup -
   dossier, `metadata.json`, `offers.json` et exports) : lettre + CV
   générés de façon cohérente entre eux, `configuration.yaml` de la
   candidature correctement réécrit (seuls `jobs`/`personal_experience`
   changés), export réel via le vrai `cvExportScript.sh`/Typst,
   `cv_page_count: 1` confirmé à la fois par `pypdf` et par relecture
   visuelle du PDF (mise en page propre, pas tassée).
3. Non-déterminisme observé et attendu (température 0.7, même catégorie
   que la variance déjà documentée section 3 pour la lettre) : `jobs` a
   été vidé dans un run et gardé identique dans un autre selon la même
   offre - les deux sont des réponses valides du prompt, pas un bug.
4. **Test de bout en bout sur une vraie offre Craft** (Framatome - Stage
   Cybersécurité F/H, description Craft minimale - juste l'en-tête
   générique de l'offre, pas le texte complet) via `prepare_application` +
   `finalize_application` réels : a directement révélé les bugs 6 et 7 de
   la section 2 (boucle de raisonnement sans fin, lien altéré) - corrigés
   avant de revalider. Une fois corrigés : sélection d'expériences très
   pertinente (l'exercice de gestion de crise avec PLC/SOC, particulièrement
   adapté à un contexte nucléaire/industriel), lettre reformulée fidèlement
   à partir d'une motivation volontairement mal exprimée fournie par
   l'utilisateur, export réel via le vrai `cvExportScript.sh`, `cv_page_count:
   1` confirmé, et écriture Craft réelle confirmée dans les deux sens
   (`mark_started`/`mark_applied` ont bien coché "Commencé"/"Postulé" sur
   la vraie entreprise, vérifié en relisant l'état après écriture - puis
   tout annulé/nettoyé après coup puisqu'il s'agissait d'un test et non
   d'une vraie candidature : checkboxes Craft repassées à "todo" via une
   deuxième écriture, dossier de candidature et fichiers exportés
   supprimés). A aussi révélé le bug 8 (sans rapport avec `wm_automation` -
   un `template.yml` de preset édité par erreur pendant la session).

### Fichiers ajoutés/modifiés

`src/wm_automation/cv.py` (nouveau), `src/wm_automation/prompts/
cv_followup_prompt.md` (nouveau), `src/wm_automation/llm.py`
(`generate_application_content` remplace `generate_lm_content`),
`src/wm_automation/pipeline.py` (`prepare_application` résout aussi le
chemin `configuration.yaml` et y applique les sections CV ;
`finalize_application` calcule `cv_page_count`/`cv_page_warning`),
`src/wm_automation/config.py` (nouveaux settings `cv_config_template_key`,
`cv_template_key`, `cv_max_pages`, `cv_followup_prompt_path`,
`llm_cv_max_tokens` - voir bug 6 section 2), `pyproject.toml` (nouvelle
dépendance `pypdf`).

---

## 6. Nettoyage en attente (non bloquant)

- **5 dossiers de candidatures réelles "Orange" orphelins** dans
  `~/workManager/applications/` (`CA-OR1f1b2d73-6`, `CA-OR1f1b2d76-9`,
  `CA-OR1f1b2d7b-a`, `CA-OR1f1b2d8f-7`, `CA-OR1f1b2d94-2`), restes d'une
  session de débogage (bug `isError`/hang du client MCP). Pas de tool
  `remove_application` (seul `remove_preset` existe côté work_manager) -
  suppression manuelle si voulu (sauvegarder `metadata.json` avant
  d'éditer).
- **Le `export_command` de la LM dans le preset `automation` fait juste un
  `cp` vers un `.txt`**, pas de conversion PDF (contrairement au CV qui
  compile bien via Typst). L'utilisateur a dit vouloir adapter ça
  lui-même plus tard (pandoc suggéré, en miroir de `cvExportScript.sh`) -
  pas bloquant, juste noté.

---

## 7. Séquence d'implémentation (état)

1. [x] Appel LLM câblé dans `pipeline.py`/`llm.py` - voir sections 1.2, 3.
2. [ ] ~~`search_experiences`~~ - reporté, voir section 4.
3. [x] Serveur MCP `wm_automation` - voir section 1.3.
4. [x] Génération du CV - voir section 5.
5. [x] Brancher l'agent (Bionic) sur le serveur MCP pour la vraie session
   interactive - ajouté manuellement via l'interface Bionic (pas en
   éditant `~/.lmstudio/mcp.json` directement, l'utilisateur préférant
   passer par l'UI), avec `load_settings()` corrigé au passage pour ne
   plus dépendre du cwd de lancement (voir section 2, bug 9). Connexion
   confirmée fonctionnelle par l'utilisateur.

## 8. Tâches parallèles (non bloquantes, toujours valides)

- **Enrichissement du corpus** `allExperiences.yaml` - [x] premier passage
  fait le 20/09/2026 (agent Claude séparé, analyse GitHub projet par
  projet + entretien, voir section 4 pour la taille résultante). Toujours
  identifié comme le vrai goulot d'étranglement de qualité, donc à
  reprendre si de nouveaux projets s'ajoutent ou si des lacunes se
  révèlent à l'usage.
- **2-3 lettres de motivation exemples**, écrites spécifiquement pour
  calibrer le style par few-shot (aucune lettre existante réutilisable -
  doivent être authentiquement bonnes, pas génériques, sinon ça
  apprendrait le défaut plutôt que de le corriger).

---

## 9. Itérations qualité après le branchement Bionic (26-28/09/2026)

Une fois l'agent réellement branché (étape 5) et les bugs de plomberie
réglés (section 2, bugs 6-10), les premiers vrais usages ont révélé des
problèmes de **qualité de sortie**, pas de fonctionnement :

- **La lettre dégénérait en un seul bloc de texte, une seule expérience,
  énumération de technologies** (constaté sur une vraie candidature
  Google) - le prompt (`lm_system_prompt.md`) avait été validé (section 3)
  contre un corpus fin ; une fois le corpus enrichi (section 8), une seule
  entrée du corpus contient déjà assez de matière pour que le modèle
  s'arrête à une seule expérience et transcrive sa densité technique telle
  quelle plutôt que de la distiller. Corrigé en renforçant explicitement le
  prompt : viser 2 expériences (pas "jusqu'à 2"), un paragraphe distinct
  par mouvement (accroche/expérience/clôture, jamais fondus), et surtout
  exiger que le fait cité illustre un **impact** (business, utilisateur,
  fiabilité...) plutôt qu'une liste de technologies - une techno n'est
  citée que si elle est nécessaire pour comprendre l'impact. Revalidé sur
  la même offre Google : 4 paragraphes distincts, 2 expériences, faits
  orientés impact plutôt qu'énumération (voir historique de session pour
  le texte complet avant/après).
- **Le CV n'utilisait pas tout le budget de 3 entrées disponible** (2 sur
  3 alors que le corpus en offre largement assez) - identifié mais pas
  encore corrigé, à reprendre si ça persiste.
- **Le CV se retrouvait avec un mélange français/anglais** quand l'offre
  exige l'anglais : les `description` (écrites par le LLM) passaient en
  anglais, mais `tagline`/`skills`/`education`/les titres de section du
  template (jamais touchés par le pipeline, voir section 5) restaient en
  français - un vrai trou d'architecture, pas encore résolu. Le pipeline
  suppose implicitement un CV entièrement en français ; rien ne gère
  aujourd'hui une bascule de langue cohérente sur l'ensemble du document.
- **Nom de candidature plus spécifique** : `create_application` utilisait
  seulement `offer.company` comme nom, ambigu dès qu'une même entreprise a
  plusieurs offres ouvertes (ex. deux offres Datadog). Ajout de
  `llm.generate_application_name()` - un appel LLM séparé, minuscule,
  forcé à `reasoning_effort="none"`, qui extrait un intitulé de rôle court
  (2-4 mots, ex. "SRE Intern") à partir du titre brut de l'offre ; le code
  (pas le LLM) préfixe `offer.company`, donc le nom de l'entreprise reste
  toujours fidèle à Craft. Volontairement hors de la conversation
  lettre/CV pour rester rapide (~0.5-1s mesuré) indépendamment de la durée
  de la génération principale. Effet de bord positif : cet appel se fait
  maintenant **avant** `create_application`, donc si le LLM est
  injoignable, plus aucune candidature orpheline n'est créée (contrairement
  à avant, où `create_application` réussissait puis la génération
  principale échouait, laissant un dossier vide à nettoyer à la main -
  arrivé à plusieurs reprises pendant cette session). Petit accroc corrigé
  en cours de route : avec `reasoning_effort="none"`, le modèle fusionnait
  les deux marqueurs (`<<<SRE Intern>>>` au lieu de
  `<<<NOM_DEBUT>>>SRE Intern<<<NOM_FIN>>>`) - corrigé en ajoutant un
  exemple de réponse littéral dans le prompt.
- **Langue de la lettre/du CV, résolu** : aucune instruction de langue
  n'existait avant - le prompt étant rédigé en français, le LLM écrivait
  toujours en français par défaut, sans mécanisme pour changer. Ajout de
  `JobOffer.language` (défaut `"français"`, comme `motivation` : fourni
  explicitement par l'humain, jamais déduit du texte de l'offre - les
  descriptions Craft sont trop courtes/ambiguës pour fiabiliser une
  détection automatique), exposé via `start_application(language=...)` et
  `cli.py --language`. Injecté dans le prompt de la lettre et dans celui de
  suivi CV (`description` de `jobs`/`personal_experience`, et `tagline`
  s'il est modifié). L'utilisateur gère déjà `tagline`/`skills`/`education`
  via un preset dédié par langue (ex. `"english"`, à utiliser avec le
  `preset` de `start_application`) plutôt que de les faire traduire par le
  pipeline.
  **Limite connue, acceptée volontairement par l'utilisateur plutôt que
  corrigée** : `position`/`company`/`product`/`tags`/`location` de chaque
  entrée `jobs`/`personal_experience` restent toujours en français, même
  en mode `language="anglais"` - `_reconcile_entries` (bug 7, section 2)
  restaure systématiquement ces champs depuis le corpus (monolingue
  français) plutôt que de faire confiance à ce que le LLM écrit, pour
  empêcher les hallucinations de liens/dates. Le champ `language` ne peut
  donc traduire que `description` et `tagline`, jamais ces champs-là. Testé
  réellement (offre Google, vraie génération) : lettre 100% anglaise, CV
  avec `description` en anglais mais `position`/`tags`/`location` en
  français - accepté tel quel le 28/09/2026, à corriger plus tard si
  besoin (options envisagées : miroir anglais du corpus, ou faire confiance
  au LLM sur ces champs en acceptant de perdre la protection anti-lien-altéré).

## 10. Référence rapide

**Fichiers clés** : `src/wm_automation/{config,models,pipeline,llm,cv,
mcp_server,mcp_client,offers_store}.py`, `src/wm_automation/craft/
{client,tracker}.py`, `src/wm_automation/prompts/{lm_system_prompt.md,
cv_followup_prompt.md,application_name_prompt.md}`, `bruno/craft-api/`.

**Env vars** (voir `config.py` pour les valeurs par défaut) :
`CRAFT_API_TOKEN`, `CRAFT_TRACKER_DOCUMENT_ID`, `CRAFT_TRACKER_COLLECTION_ID`,
`LLM_API_BASE`, `LLM_MODEL`, `LLM_SYSTEM_PROMPT_PATH`, `LLM_TEMPERATURE`,
`LLM_REASONING_EFFORT`, `LLM_TIMEOUT_SECONDS`, `LLM_CV_MAX_TOKENS`,
`LLM_LETTER_MAX_TOKENS`, `LLM_APPLICATION_NAME_MAX_TOKENS`,
`APPLICATION_NAME_PROMPT_PATH`, `CV_FOLLOWUP_PROMPT_PATH`, `WM_CORPUS_PATH`,
`WM_CV_CONFIG_TEMPLATE_KEY`, `WM_CV_TEMPLATE_KEY`, `WM_CV_MAX_PAGES`,
`WM_DEFAULT_AUTOMATION_PRESET`, `WM_MCP_BINARY`, `WM_OFFERS_STORE`,
`WM_LM_TEMPLATE_KEY`.

**Commande serveur MCP** : `.venv/bin/wm-automation-mcp` (stdio).

**Fichiers de données réels concernés** (hors repo, sur la machine) :
`~/workManager/allExperiences.yaml` (corpus LM), `~/workManager/presets/
automation/{template.yml,configuration.yaml,ATSCV.typ}` (preset CV/LM
utilisé par l'automatisation), `~/.wm_automation/offers.json` (mapping
application↔offre).

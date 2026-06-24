# Architecture & flux de données

## Vue d'ensemble des modules

lebonparser est découpé en modules à responsabilité unique. Le frontal web
(`app.py`) délègue tout au cœur métier (`core.py`), qui orchestre les briques
bas-niveau (scraping, accès web, LLM).

```plantuml
@startuml
skinparam shadowing false
skinparam componentStyle rectangle
left to right direction

package "Frontal" {
  [app.py\n(interface web Flask)] as APP
}

package "Cœur métier" {
  [core.py\norchestration + stockage] as CORE
}

package "Briques" {
  [scraper.py\nscrape()] as SCRAPE
  [analyze.py\nanalyser_liste()] as ANALYZE
  [web.py\nsession + __NEXT_DATA__] as WEB
  [llm.py\njudge()] as LLM
  [cookies.py] as COOKIES
  [config.py] as CONFIG
}

cloud "leboncoin.fr\n(Next.js + DataDome)" as LBC
node "LLM local\n(Ollama, qwen3:8b)" as OLLAMA
cloud "LLM distant\n(API, ex. Claude Haiku)" as APILLM
database "searches/<slug>/\nsearch.json · seen.json · analyse.log" as STORE
node "Firefox\n(cookies)" as FF

APP --> CORE
CORE --> SCRAPE
CORE --> ANALYZE
CORE --> WEB
CORE --> STORE
SCRAPE --> WEB
ANALYZE --> WEB
ANALYZE --> LLM
WEB --> COOKIES
WEB --> LBC
COOKIES ..> FF
LLM --> OLLAMA : backend "ollama"
LLM ..> APILLM : backend "api"

CONFIG ..> APP
CONFIG ..> CORE
CONFIG ..> WEB
CONFIG ..> LLM
@enduml
```

| Module | Responsabilité |
|---|---|
| `app.py` | serveur Flask : routes, threads de run, polling de progression. |
| `core.py` | stockage des recherches (`searches/`) + `run_search()` incrémental. |
| `scraper.py` | `scrape(session, url)` — parcourt toutes les pages d'une recherche. |
| `web.py` | session HTTP `curl_cffi` (empreinte Firefox) + extraction `__NEXT_DATA__`. |
| `cookies.py` | extrait les cookies leboncoin (dont `datadome`) du navigateur. |
| `analyze.py` | `analyser_liste()` — texte intégral + jugement LLM (séquentiel ou parallèle selon le backend). |
| `llm.py` | `judge()` — **sortie structurée** JSON validée (Pydantic) ; backend **Ollama** (local) ou **API** (distant, via Instructor). |
| `config.py` | réglages globaux (Ollama, seuils, délais, navigateur…) ; charge `.env` où vit toute la config du LLM distant. |

## Stockage : une recherche = un dossier

Tout l'état d'une recherche vit sous `searches/<slug>/`. `seen.json` est la **mémoire
centrale** qui rend les runs incrémentaux.

```plantuml
@startuml
allowmixing
skinparam shadowing false

object "search.json" as S {
  name
  slug
  urls : [url, ...]
  critere
  created
  last_run
}

map "seen.json\n{ ad_id : record }" as SEEN {
 record => titre, url, prix, ville
 .. => score, interessant, raison
 .. => erreur (bool)
 .. => date_found (= run_ts)
}

file "analyse.log\n(journal du dernier run)" as LOG

S -[hidden]-> SEEN
SEEN -[hidden]-> LOG
@enduml
```

- **Historique retenu** = entrées de `seen.json` avec `score ≥ SCORE_MIN`.
- **Nouveautés du run** = entrées dont `date_found == search.last_run`.
- Une entrée marquée `erreur: true` (jugement LLM échoué) est **rejugée** au prochain
  run tant qu'elle réapparaît, au lieu d'être figée à 0.

## Flux d'un run (le cœur)

`core.run_search(slug)` enchaîne scraping → diff → analyse → sauvegarde. Le diff par
`id` est ce qui évite de rejuger l'existant.

```plantuml
@startuml
skinparam shadowing false
start
:charger search.json + seen.json;
:llm.check_ready()\n(Ollama + modèle dispo ?);

partition "1. Scraping (toutes les URL)" {
  repeat :pour chaque URL source;
    :scraper.scrape() — toutes les pages;
    :fusionner + dédoublonner par id;
  repeat while (URL suivante ?) is (oui)
  -> non;
}

partition "2. Diff incrémental" {
  :nouveaux = annonces jamais vues\n+ annonces précédemment en erreur;
}

partition "3. Analyse LLM (nouveaux seulement)" {
  repeat :pour chaque nouvelle annonce;
    :web.fetch_body() — description complète;
    :llm.judge(texte, critère);
    :enregistrer dans seen.json\n(sauvegarde incrémentale);
  repeat while (annonce suivante ?) is (oui)
  -> non;
}

partition "4. Finalisation" {
  :search.last_run = run_ts;
  :sauver search.json + seen.json;
  :résumé {n_scraped, n_new, n_retenues_new};
}
stop
@enduml
```

## Séquence : un clic sur « Run »

L'app web lance le run dans un **thread d'arrière-plan** et publie l'avancement dans
un dictionnaire en mémoire (`RUNS`). Le navigateur **interroge** (polling) l'état
toutes les ~1 s — pas de Celery/Redis, inutile pour un usage local mono-utilisateur.

```plantuml
@startuml
skinparam shadowing false
actor Utilisateur as U
participant "Navigateur" as B
participant "app.py\n(Flask)" as F
participant "Thread\n_worker" as W
participant "core.run_search" as C
participant "leboncoin" as LBC
participant "Ollama" as O

U -> B : clic « Run »
B -> F : POST /searches/<slug>/run
F -> W : démarre le thread
F --> B : { task_id }

activate W
W -> C : run_search(slug, progress_cb)
loop scraping pages
  C -> LBC : GET page
  LBC --> C : __NEXT_DATA__
  C -> W : progress_cb(scraping)
end
loop nouvelles annonces
  C -> LBC : GET détail
  C -> O : judge(texte, critère)
  O --> C : {interessant, score, raison}
  C -> W : progress_cb(analyse)
end
C --> W : résumé
deactivate W

loop toutes les ~1 s
  B -> F : GET /api/run/<task_id>
  F --> B : { phase, current, total, message, eta, done }
end
B -> U : barre de progression\n+ temps restant estimé (ETA)\npuis « Terminé »
@enduml
```

!!! tip "Temps restant estimé (ETA)"
    Pendant l'analyse, `core` estime le temps **restant** (temps écoulé ÷ annonces
    traitées × annonces restantes) et le joint à l'état (`eta`). Comme une annonce
    n'est comptée qu'une fois **téléchargée *et* jugée**, l'estimation reflète le
    **cycle complet**. Recalculée seulement **toutes les 10 annonces** pour un
    affichage stable, elle apparaît collée à droite de la ligne de progression.

## Jugement d'une annonce — backend Ollama (sortie structurée + filet anti-troncature)

`llm.judge()` demande à qwen3 un JSON conforme au schéma `Jugement`
(`interessant`, `score` 0-10, `raison`). En mode *thinking*, le raisonnement peut
épuiser le budget `num_predict` **avant** d'écrire le JSON (réponse vide,
`done_reason=length`) : dans ce cas, l'annonce est **rejugée sans thinking** pour
obtenir un verdict plutôt que de la perdre. *(Ce diagramme décrit le backend local
Ollama ; le backend API est décrit juste en dessous.)*

```plantuml
@startuml
skinparam shadowing false
start
:texte de l'annonce + critère;
:chat Ollama (think = config.OLLAMA_THINK)\nformat = schéma JSON Jugement;
if (réponse vide ET done_reason = length\nET thinking activé ?) then (oui)
  :re-chat SANS thinking;
  note right: le JSON est produit\nimmédiatement
endif
:journaliser les tokens\n(prompt + génération / num_ctx);
if (total > 75 % de num_ctx ?) then (oui)
  :⚠ avertissement\ncontexte faible;
endif
if (contenu présent ?) then (oui)
  :valider en Jugement (Pydantic);
  stop
else (non)
  :erreur → annonce marquée\n« erreur » (rejugée + tard);
  stop
endif
@enduml
```

## Backend LLM : local (Ollama) ou distant (API parallélisable)

`config.LLM_BACKEND` choisit comment juger les annonces. `llm.judge()` masque la
différence ; c'est `analyze.analyser_liste()` qui adapte le **régime d'exécution**.

| | Backend `ollama` (local) | Backend `api` (distant) |
|---|---|---|
| Modèle | qwen3:8b via Ollama (GPU recommandé) | ex. Claude Haiku 4.5 via Instructor |
| Clé / coût | aucune | clé d'API (`.env` : `LLM_API_KEY`), ~1 €/run complet |
| Sortie structurée | `format` = schéma JSON | `response_model=Jugement` (retries auto) |
| Exécution | séquentielle, entrelacée | **pipeline : 1 téléchargeur séquentiel → N jugements parallèles** |
| Débit | latence GPU | **plafonné à `LLM_RPM`** (départs espacés) → aucun 429 |

Le point clé : aujourd'hui la **latence du LLM espace** naturellement les requêtes
vers leboncoin. Avec un LLM distant rapide et parallèle, ce garde-fou disparaît — il
faut donc **découpler** le téléchargement (seul accès à leboncoin, qui doit rester
séquentiel et throttlé contre DataDome) du jugement (sans accès réseau au site, donc
parallélisable sans risque). Les deux tournent en **pipeline** : un unique producteur
télécharge pendant que N consommateurs jugent les annonces déjà prêtes, si bien que la
durée totale ≈ **max**(téléchargement, jugement) au lieu de leur **somme**.

```plantuml
@startuml
skinparam shadowing false
start
if (config.LLM_BACKEND) then (ollama)
  partition "Séquentiel (entrelacé)" {
    repeat :annonce suivante;
      :fetch_body() — description;
      :llm.judge() — jugement;
      :MIN_FETCH_INTERVAL;
    repeat while (reste des annonces ?) is (oui)
    -> non;
  }
else (api)
  partition "Pipeline (téléchargement et jugement se recouvrent)" {
    fork
      :**1 producteur**;
      repeat :annonce suivante;
        :fetch_body() — description;
        :pousser dans la file;
        :MIN_FETCH_INTERVAL\n(anti-DataDome);
      repeat while (reste des annonces ?) is (oui)
      -> non;
    fork again
      :**N consommateurs**\n(LLM_CONCURRENCY);
      repeat :tirer de la file;
        :llm.judge();
        :progress_cb sous verrou\n(seen.json + ETA);
      repeat while (file non vide ?) is (oui)
      -> non;
    end fork
  }
endif
stop
@enduml
```

!!! note "Sécurité de l'incrémental"
    Le **producteur** n'appelle **pas** `progress_cb` : une annonce téléchargée mais pas
    encore jugée donnerait un enregistrement incomplet dans `seen.json`. Seul le
    **consommateur** persiste, après le verdict — un crash pendant le téléchargement se
    traduit donc par des annonces simplement **rejugées** au run suivant.

## Accès à leboncoin (contournement DataDome)

leboncoin est un site **Next.js** protégé par **DataDome**. La méthode retenue ne
pilote pas un navigateur : elle **réutilise la session Firefox** de l'utilisateur.

```plantuml
@startuml
skinparam shadowing false
participant "cookies.py" as CK
participant "Firefox\n(profil local)" as FF
participant "web.py" as WEB
participant "leboncoin" as LBC

CK -> FF : lire cookies leboncoin.fr
FF --> CK : { datadome, session, ... }
CK --> WEB : cookies
WEB -> WEB : Session curl_cffi\nimpersonate="firefox"\n+ User-Agent Firefox
WEB -> LBC : GET (cookies injectés)
LBC --> WEB : HTML avec <script id="__NEXT_DATA__">
WEB -> WEB : parse JSON __NEXT_DATA__\n→ annonces / description
@enduml
```

Si `__NEXT_DATA__` est absent, la page est probablement un *challenge* DataDome : il
faut recharger leboncoin dans Firefox (connecté) puis réessayer.

## Cycle de vie d'une annonce

C'est `seen.json` qui porte l'état d'une annonce d'un run à l'autre. Ce cycle
explique pourquoi un run quotidien ne juge que quelques annonces — et pourquoi une
annonce dont le jugement a échoué est automatiquement réessayée.

```plantuml
@startuml
skinparam shadowing false
[*] --> Inconnue
Inconnue --> Jugée : apparaît dans le scraping\n→ envoyée au LLM
state Jugée {
  state "Retenue (score ≥ SCORE_MIN)" as R
  state "Écartée (score < SCORE_MIN)" as E
  state "Erreur (jugement échoué)" as ERR
  [*] --> R
  [*] --> E
  [*] --> ERR
}
R --> R : run suivant\n(déjà vue → non rejugée)
E --> E : run suivant\n(déjà vue → non rejugée)
ERR --> Jugée : run suivant\n(rejugée tant qu'elle réapparaît)
@enduml
```

- **Retenue / Écartée** : enregistrée dans `seen.json`, elle ne sera **jamais
  rejugée** (économie de temps LLM au quotidien).
- **Erreur** : marquée `erreur: true`, elle est **rejugée** au prochain run tant
  qu'elle réapparaît dans les résultats — un échec transitoire (LLM, réseau) n'est
  donc pas figé à 0.
- L'**historique** affiché = toutes les *Retenue* ; les **nouveautés** = les
  *Retenue* dont `date_found` == `last_run`.

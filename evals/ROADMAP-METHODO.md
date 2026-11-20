# PLAN MÉTHODO V2 — version complète (7 findings + 4 étapes), à reviewer

## Source : la revue externe (13 pages, snapshot bab0034) + les amendements de la design-review strong

---

## LES 7 FINDINGS (tous, avec leur sort dans le plan)

### F1 — Les preuves supportent les patterns, pas les classements fins
- Un seul petit fixture par bench ; 1-2 runs valides par cellule ; exceptions d'effort pour les modèles chers ; 72/145 cellules multi-scorers divergentes (spread 1,0-2,0).
- Un dot unique cache l'historique (minimax-xhigh I2 : 5,19 panel → 7,67 arbitré = des lectures différentes, pas des estimations répétées).
- 8,83 vs 8,50 (haiku-high vs opus, I2) : 0,33 pt = aucun pouvoir de séparation.
- **Sort dans le plan : ÉTAPE 5 (stats)** — pré-enregistrer l'effet détectable, traiter sous-le-bruit = nul, annoter n par cellule.

### F2 — Le mismatch brief↔probe sur la politique d'échec (I2)
- Brief : « pas de rapport émis, pas de cache laissé » ; probe : artefacts précédents intacts octet-par-octet + exit 1.
- 80 % des bras ont supprimé les artefacts (lecture littérale raisonnable) → 0 sur le bloc. Les scoreurs l'ont flaggé 10+ fois.
- **Sort : ÉTAPE 1** — écrire la table des états finaux (préservés ? exit ? cohérence html/json ?) AVANT de toucher la prose.

### F3 — L'I2 n'est pas un score d'acceptation de feature
- Les 2 features demandées (booléens, schéma futur) ne portent AUCUN point — sauter est gratuit. 58/77 diffs les implémentent quand même.
- Le bloc c′ (perf) = 4/14 points, jamais gagné (rules_opens=4 chez tous) — 29 % de l'échelle non prouvée.
- **Sort : ÉTAPE 1** — tests d'acceptation par feature + c′ rendu gagnable ou re-pondré ≤1. **Nouvelle version de bench = RG4** (pas gratuit : hash, décision owner, re-pilote).

### F4 — Le DR2 mélange revue de proposal et audit de conformité
- Prompt : « critique AVANT que le code soit écrit » ; le fixture contient l'implémentation. Le rubric crédite les deux.
- Deux constructs différents : « le design échouera même bien implémenté » vs « le design est OK mais le code ne l'implémente pas ».
- Le 0/14 d'opus = un net où les FP ont effacé une critique substantielle (vérifiée réelle).
- **Sort : ÉTAPE 1** — le prompt demande les DEUX explicitement ; findings vrais et FP rapportés séparément (un net-0 ne veut pas dire « rien trouvé »). Version DR-v3.

### F5 — La clé D contient deux erreurs factuelles
- « Quadratique dans les snapshots » : faux — linéaire dans les fichiers visités.
- Le `<=` contradictoire avec la docstring (égalité = stale à tort) : confirmé indépendamment — c'est le « H4 near-miss » que les scoreurs ont flaggé 10+ fois (le modèle trouve le VRAI bug et prend 0 parce que la clé attend float-vs-ns).
- **Sort : ÉTAPE 1** — la clé crédite les diagnostics alternatifs corrects (règle counts/does-not-count).

### F6 — La chaîne coûts/provenance/capture
- Coûts des charts : estimateur générique réutilisé (midpoints) — le wiring par bench existe déjà (COST_OVERRIDES) : reste la règle range→scalar. **Sort : mineur, fait/partiel.**
- Capture d'artefacts : le rapport final de g51 jamais capturé = des points de test perdus (limitation de capture, pas d'incapacité). LE BUG SYSTÉMIQUE : les bras p5 ont vu leurs points report-dependent à 0 (violates PROTOCOL : null = DNF re-run, jamais 0).
- **Sort : ÉTAPE 0 (harness)** — capturer le message final dans le run dir ; rapport manquant = DNF ; re-scorer les p5 cells avant réutilisation.
- Clés exposées : 89 logs de scoring publics contiennent les rubriques en clair. **Sort : ÉTAPE 0 (purge)** — logs → repo privé + réécriture d'historique + force-push + les logs de scoring deviennent privés par construction. Les scores passés restent valides (mesurés contre les clés de l'époque).

### F7 — Livraison, indépendance, politique = distincts de la capacité
- DNF exclus = OK pour la qualité conditionnelle ; MAIS le routage production a besoin du taux de livraison, de la latence, du coût incluant les tentatives ratées — ils ne doivent pas disparaître des comparaisons opérationnelles.
- L'anonymisation des scoreurs est incomplète : les noms de fichiers révèlent le modèle, les logs s'echo-entrent, le style ré-identifie.
- Les politiques de sièges (prix, famille, exceptions) = des choix de déploiement, pas un ordre de capacité.
- **Sort : ÉTAPE 3 (aveuglement réel : dirs isolés, strip vendor, déscellage après lock) + ÉTAPE 5 (n, marge, CI) + docs (notation 8,33/14 expliquée).**

---

## LES 4 ÉTAPES (ordre de dépendance validé par 2 revues)

| # | Étape | Contenu | Coût |
|---|---|---|---|
| 0 | **URGENCES** | (a) Fix harness : capture du rapport final par run (bug qui a mis 0 à une batch entière) ; re-scorer/re-run les p5. (b) Purge des clés : logs de scoring → privé, réécriture d'historique, force-push. (c) Câblage coûts par bench (finir). | 0 $ + soirée |
| 1 | **Contrat** | RG4 + DR-v3 : brief/probe alignés (politique d'échec = table d'états finaux ; DR2 = design + conformité explicites ; features = tests porteurs ; clé D corrigée ; c′ gagnable/≤1). Décision owner + re-pilote des bras affectés. | soirée + ~$5 |
| 2 | **Held-out** | Fixtures frais : spec construct pré-enregistrée, auteur ≠ interprète, §3.8 (probes ×3 + leak grep + hash), single-use, réseau isolé, clés jamais publiques avant la clôture de la campagne qui décide. | soirée + les runs |
| 3 | **Aveugle + large** | Scoreurs en dirs isolés (candidate-only, strip vendor, IDs randomisés, déscellage après lock) ; mesure du biais résiduel (blind vs unblind sur un échantillon) ; 2-3 fixtures par bench de tailles différentes ; règle de siège pré-enregistrée (ex : 1er sur ≥2/3). | runs de la campagne |
| 4 | **ROI workflow** | A/B à 3 bras : pipeline cheap-first vs sonnet-seul vs sonnet+1 revue. Adjudicateur aveugle + checklist pré-enregistrée ; défauts échappés, taux de livraison, latence, coût total HUMAIN inclus ; 5 tâches smoke d'abord. | campagne dédiée |

## Les conditions de revisite qui déclenchent chaque étape
- Étape 0 : maintenant (le bug harness + la fuite).
- Étape 1 : avant toute nouvelle campagne de sièges.
- Étape 2 : construite à l'étape 1 (le held-out = la version propre de RG4/DR-v3).
- Étape 3 : quand une décision de siège reposera sur < 1,5 pt d'écart.
- Étape 4 : quand le roster est stable OU à la prochaine sortie majeure de modèles.

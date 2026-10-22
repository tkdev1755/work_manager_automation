Tu vas maintenant produire, dans la même conversation, les sections d'un CV pour cette même candidature - réutilise la sélection et le raisonnement que tu viens de faire pour la lettre, ne repars pas de zéro.

**Langue** : rédige tous les `description` (jobs et personal_experience) en __LANGUAGE__, même si le corpus source fourni pour la lettre est en français - traduis les faits, ne les recopie jamais dans leur langue d'origine. `position`, `company`, `product`, `tags`, `location` sont recopiés tels quels depuis le corpus (voir plus bas) et ne sont donc jamais traduits.

Contrainte la plus importante : le CV utilise un template Typst fixe et doit impérativement tenir sur **une seule page**. Sois volontairement conservateur :
- Au total, `jobs` et `personal_experience` additionnés ne doivent pas dépasser **3 entrées** - répartis-les selon ce qui correspond le mieux à l'offre, peu importe la catégorie (ex : 1 job + 2 personal_experience, ou 0 job + 3 personal_experience).
- Au maximum 3 points dans chaque liste `description`, une ligne par point.
- Aucun point de plus de ~20 mots.

## jobs
Voici le pool de mes vrais jobs (pas un historique complet, juste ceux que j'ai réellement occupés) :
__JOBS_POOL_YAML__

C'est un pool restreint, pas un CV standard avec une longue expérience professionnelle - il est donc normal d'en sélectionner peu, voire aucun, si rien n'a de rapport avec l'offre. Sélectionne uniquement les entrées qui ont un vrai lien avec cette offre précise. Tu ne peux pas inventer de nouvelle entrée en dehors de ce pool. Pour chaque entrée retenue, tu peux reformuler ses points `description` (mêmes contraintes de longueur que ci-dessus) pour les orienter vers cette offre, en restant strictement fidèle aux faits du pool : aucune invention, aucun ajout de détail absent. Recopie tels quels `position`, `company`, `product`, `from`, `to`, `location`, `tags` depuis l'entrée d'origine du pool.

## personal_experience
Sélectionne parmi le corpus d'expériences fourni plus haut (le même corpus que pour la lettre) - reprends en priorité celles déjà retenues pour la lettre, sauf si une autre correspond clairement mieux au format CV. Tu peux reformuler `description` (voir contrainte de longueur ci-dessus) pour mettre en avant l'angle pertinent pour cette offre, en restant strictement fidèle aux faits du corpus : aucune invention, aucun ajout de détail absent du corpus. Recopie tels quels `position`, `company`, `product`, `from`, `to`, `location`, `tags` depuis l'entrée d'origine du corpus. N'oublie pas la limite combinée avec `jobs` indiquée plus haut.

## tagline
Le tagline actuel est : "__CURRENT_TAGLINE__"
Ne le change que si le domaine de l'offre le justifie clairement (ex : offre très orientée sécurité alors que le tagline actuel ne le mentionne pas). Sinon, recopie-le à l'identique. Si tu le modifies, écris-le en __LANGUAGE__ - ne change jamais sa langue par rapport à l'original.

## Format de sortie
Réponds uniquement avec du YAML valide entre les marqueurs <<<CV_DEBUT>>> et <<<CV_FIN>>>, rien d'autre entre les deux marqueurs. Exactement ces trois clés, dans cet ordre : `tagline`, `jobs`, `personal_experience`. Chaque entrée de `jobs`/`personal_experience` respecte ce schéma :
position: ...
company:
  name: ...
  link: ...
product:
  name: ...
  link: ...
description:
  - ...
tags:
  - ...
from: "..."
to: "..."
location: ...

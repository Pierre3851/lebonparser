# Politique de sécurité

## Signaler une vulnérabilité

Merci de **ne pas ouvrir d'issue publique** pour une faille de sécurité.

Utilise le canal privé de GitHub :

1. Onglet **« Security »** du dépôt → **« Report a vulnerability »**
   (*Private vulnerability reporting*).
2. Décris la faille, son impact, et les étapes pour la reproduire.

Tu recevras un accusé de réception dès que possible. Une fois le problème confirmé et
corrigé, le correctif sera publié et le mérite te sera reconnu si tu le souhaites.

## Périmètre

Points de vigilance propres à ce projet :

- **Cookies de navigateur** : l'outil lit les cookies leboncoin (dont `datadome`) de
  ta session locale. Ils ne quittent jamais ta machine et ne doivent jamais être
  journalisés, affichés ou commités.
- **Application web locale** : le serveur Flask n'écoute que `127.0.0.1` et n'est pas
  conçu pour être exposé sur un réseau public.
- **Données scrapées** : stockées en local uniquement (`data/`, `searches/`, `runs/`),
  exclues du dépôt par `.gitignore`.

Voir aussi l'[avertissement légal](DISCLAIMER.md).

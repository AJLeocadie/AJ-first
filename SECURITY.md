# Politique de sécurité

## Versions supportées

| Version | Supportée |
|---------|-----------|
| 1.x     | Oui       |

## Signaler une vulnérabilité

Si vous découvrez une vulnérabilité de sécurité, **ne créez pas d'issue publique**.

Envoyez un email à **admin@normacheck.fr** avec :

- Description de la vulnérabilité
- Étapes pour reproduire
- Impact potentiel

Nous nous engageons à :
- Accuser réception sous 48h
- Fournir une évaluation sous 7 jours
- Publier un correctif dans les meilleurs délais

## Bonnes pratiques

- Ne commitez jamais de secrets (`.env`, clés API, mots de passe)
- Utilisez `.env.example` comme référence de configuration
- Les dépendances sont auditées régulièrement
